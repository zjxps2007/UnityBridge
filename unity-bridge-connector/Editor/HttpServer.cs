using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;

namespace UnityBridgeConnector
{
    /// <summary>
    /// Lightweight HTTP server on localhost. Receives CLI commands as POST /command,
    /// dispatches via CommandRouter, returns JSON responses.
    /// Uses ConcurrentQueue + EditorApplication.update for main-thread marshaling.
    /// Background editor throttling can still delay command execution.
    /// Survives domain reloads via InitializeOnLoad.
    /// </summary>
    [InitializeOnLoad]
    public static class HttpServer
    {
        const int DEFAULT_PORT = 8090;
        const int MAX_PORT_ATTEMPTS = 10;
        const double AUTO_RESTART_INTERVAL = 1.0;
        const double FAILURE_LOG_INTERVAL = 5.0;

        static HttpListener s_Listener;
        static CancellationTokenSource s_Cts;
        static int s_Port;
        static SynchronizationContext s_MainContext;
        static double s_NextStartAttemptTime;
        static string s_LastFailureMessage;
        static double s_LastFailureLogTime;
        static bool s_Stopping;
        static int s_QueueDrainPosted;

        static readonly ConcurrentQueue<WorkItem> s_Queue = new ConcurrentQueue<WorkItem>();
        static readonly ConcurrentQueue<HttpListener> s_FailedListeners = new ConcurrentQueue<HttpListener>();

        struct WorkItem
        {
            public string Command;
            public JObject Parameters;
            public BridgeRequestContext Request;
            public TaskCompletionSource<string> Tcs;
        }

        static HttpServer()
        {
            // Import workers load editor assemblies but must not expose a command server.
            if (AssetDatabase.IsAssetImportWorkerProcess()) return;

            s_MainContext = SynchronizationContext.Current;
            Start();
            EditorApplication.quitting += Stop;
            AssemblyReloadEvents.beforeAssemblyReload += StopListener;
            AssemblyReloadEvents.afterAssemblyReload += Start;
            EditorApplication.update += ProcessQueue;
        }

        public static int Port => s_Port;
        public static bool IsRunning => s_Listener != null && s_Listener.IsListening;

        static void Start()
        {
            s_Stopping = false;
            if (IsRunning) return;
            if (s_Listener != null) StopListener();
            s_Stopping = false;

            for (var attempt = 0; attempt < MAX_PORT_ATTEMPTS; attempt++)
            {
                var port = DEFAULT_PORT + attempt;
                if (TryStartOnPort(port))
                    return;
            }

            Heartbeat.MarkStopped();
            ScheduleRetry();
            LogStartFailure("[UnityBridge] Failed to start HTTP server — no available port", true);
        }

        static bool TryStartOnPort(int port)
        {
            try
            {
                var listener = new HttpListener();
                listener.Prefixes.Add($"http://127.0.0.1:{port}/");
                listener.Start();

                s_Listener = listener;
                s_Port = port;
                var cts = new CancellationTokenSource();
                s_Cts = cts;
                ClearRetry();
                ClearStartFailure();

                // Network continuations must not wait for another Editor update.
                // Only dispatch and result serialization cross to the main thread.
                var token = cts.Token;
                _ = Task.Run(() => ListenLoop(listener, token));

                Heartbeat.PublishServerStarted();
                Debug.Log($"[UnityBridge] HTTP server started on port {port}");
                return true;
            }
            catch (HttpListenerException)
            {
                return false;
            }
            catch (System.Net.Sockets.SocketException)
            {
                // Windows/Mono throws SocketException instead of HttpListenerException
                return false;
            }
            catch (Exception ex)
            {
                ScheduleRetry();
                LogStartFailure($"[UnityBridge] Failed to start HTTP server on port {port}: {ex.Message}", true);
                return false;
            }
        }

        static void ScheduleRetry()
        {
            s_NextStartAttemptTime = EditorApplication.timeSinceStartup + AUTO_RESTART_INTERVAL;
        }

        static void ClearRetry()
        {
            s_NextStartAttemptTime = 0;
        }

        static void LogStartFailure(string message, bool error = false)
        {
            var now = EditorApplication.timeSinceStartup;
            if (s_LastFailureMessage == message && now - s_LastFailureLogTime < FAILURE_LOG_INTERVAL)
                return;

            s_LastFailureMessage = message;
            s_LastFailureLogTime = now;
            if (error) Debug.LogError(message);
            else Debug.LogWarning(message);
        }

        static void ClearStartFailure()
        {
            s_LastFailureMessage = null;
            s_LastFailureLogTime = 0;
        }

        static void StopListener()
        {
            s_Stopping = true;
            ClearRetry();

            s_Cts?.Cancel();
            s_Cts?.Dispose();
            s_Cts = null;

            while (s_Queue.TryDequeue(out var pending))
                CompleteItem(pending, BridgeProtocol.Reject("not_ready", "Unity connector is stopping."));

            if (s_Listener == null) return;

            try
            {
                s_Listener.Stop();
                s_Listener.Close();
            }
            catch
            {
            }

            s_Listener = null;
        }

        static void Stop()
        {
            var port = s_Port;
            StopListener();
            Heartbeat.MarkStopped();
            Debug.Log($"[UnityBridge] HTTP server stopped (was port {port})");
        }

        static void ForceEditorUpdate()
        {
            var context = s_MainContext;
            if (context == null || Interlocked.Exchange(ref s_QueueDrainPosted, 1) != 0)
                return;

            try
            {
                context.Post(_ =>
                {
                    Interlocked.Exchange(ref s_QueueDrainPosted, 0);
                    ProcessQueue();
                }, null);
            }
            catch
            {
                Interlocked.Exchange(ref s_QueueDrainPosted, 0);
            }
        }

        static void ProcessQueue()
        {
            while (s_FailedListeners.TryDequeue(out var failedListener))
            {
                if (!s_Stopping && ReferenceEquals(s_Listener, failedListener))
                {
                    StopListener();
                    Heartbeat.MarkStopped();
                    ScheduleRetry();
                }
            }

            if (!IsRunning && s_NextStartAttemptTime > 0 && EditorApplication.timeSinceStartup >= s_NextStartAttemptTime)
                Start();

            while (s_Queue.TryDequeue(out var item))
                ProcessItem(item);
        }

        static async void ProcessItem(WorkItem item)
        {
            try
            {
                var r = await CommandRouter.Dispatch(item.Command, item.Parameters, item.Request);
                CompleteItem(item, r);
            }
            catch (Exception ex)
            {
                CompleteItem(item, new ErrorResponse(ex.Message));
            }
        }

        static void CompleteItem(WorkItem item, object result)
        {
            // Custom tools may return objects whose properties/converters use
            // Unity APIs. Keep their serialization on the dispatch thread.
            try { item.Tcs.TrySetResult(JsonConvert.SerializeObject(result)); }
            catch (Exception ex) { item.Tcs.TrySetException(ex); }
        }

        static async Task ListenLoop(HttpListener listener, CancellationToken ct)
        {
            try
            {
                while (!ct.IsCancellationRequested)
                {
                    if (listener == null || !listener.IsListening) break;

                    try
                    {
                        var context = await listener.GetContextAsync().ConfigureAwait(false);
                        _ = HandleRequest(context, ct);
                    }
                    catch (ObjectDisposedException)
                    {
                        break;
                    }
                    catch (HttpListenerException)
                    {
                        break;
                    }
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"[UnityBridge] ListenLoop crashed: {ex.Message}");
            }
            finally
            {
                // Lifecycle changes stay on the main thread; identify the
                // failed listener so an old loop cannot stop its replacement.
                if (!ct.IsCancellationRequested) s_FailedListeners.Enqueue(listener);
            }
        }

        static async Task HandleRequest(HttpListenerContext context, CancellationToken listenerToken)
        {
            var request = context.Request;
            var response = context.Response;

            response.ContentType = "application/json";

            // Block browser cross-origin requests; native CLI clients do not use CORS.
            if (request.HttpMethod == "OPTIONS")
            {
                response.StatusCode = 204;
                response.Close();
                return;
            }

            var origin = request.Headers["Origin"];
            if (origin != null)
            {
                response.StatusCode = 403;
                var buf = Encoding.UTF8.GetBytes("{\"error\":\"Browser requests are not allowed\"}");
                response.ContentLength64 = buf.Length;
                await response.OutputStream.WriteAsync(buf, 0, buf.Length).ConfigureAwait(false);
                response.Close();
                return;
            }

            object result = null;
            string responseJson = null;

            try
            {
                if (request.HttpMethod != "POST" || request.Url.AbsolutePath != "/command")
                {
                    result = new ErrorResponse($"Expected POST /command, got {request.HttpMethod} {request.Url.AbsolutePath}");
                    response.StatusCode = 400;
                }
                else
                {
                    using var reader = new StreamReader(request.InputStream, Encoding.UTF8);
                    var body = await reader.ReadToEndAsync().ConfigureAwait(false);
                    var json = JObject.Parse(body);

                    var command = json["command"]?.ToString();
                    var parameters = json["params"] as JObject;
                    var suppliedToken = request.Headers["X-UnityBridge-Token"];
                    var authenticated = BridgeHostConfiguration.Authenticate(suppliedToken);

                    if (string.IsNullOrEmpty(command))
                    {
                        result = new ErrorResponse("Missing 'command' field");
                        response.StatusCode = 400;
                    }
                    else if ((BridgeProtocol.IsInternalCommand(command) || suppliedToken != null) && !authenticated)
                    {
                        result = BridgeProtocol.Reject("unauthorized", "Host authentication required.");
                        response.StatusCode = 403;
                    }
                    else
                    {
                        var metadata = new BridgeRequestContext
                        {
                            RequestId = json["request_id"]?.ToString(),
                            DeadlineUnixMs = (long?)json["deadline_unix_ms"],
                            DomainId = json["domain_id"]?.ToString(),
                            ReferenceGeneration = (long?)json["reference_generation"],
                            Authenticated = authenticated,
                            ListenerCancellation = listenerToken,
                        };
                        if (BridgeProtocol.IsInternalCommand(command) && !metadata.DeadlineUnixMs.HasValue)
                        {
                            result = BridgeProtocol.Reject("invalid_request", "deadline_unix_ms is required.");
                            response.StatusCode = 400;
                        }
                        else
                        {
                            var tcs = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
                            s_Queue.Enqueue(new WorkItem
                            {
                                Command = command,
                                Parameters = parameters,
                                Request = metadata,
                                Tcs = tcs,
                            });
                            ForceEditorUpdate();
                            responseJson = await tcs.Task.ConfigureAwait(false);
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                result = new ErrorResponse($"Request error: {ex.Message}");
                response.StatusCode = 500;
            }

            if (responseJson == null) responseJson = JsonConvert.SerializeObject(result);
            var buffer = Encoding.UTF8.GetBytes(responseJson);
            response.ContentLength64 = buffer.Length;
            await response.OutputStream.WriteAsync(buffer, 0, buffer.Length).ConfigureAwait(false);
            response.Close();
        }
    }
}
