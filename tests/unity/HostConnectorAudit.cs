// Copied into disposable native validation projects; never shipped in the package.
using System;
using System.Reflection;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityBridgeConnector;

[InitializeOnLoad]
public static class HostConnectorAudit
{
    static readonly Assembly Connector = typeof(CommandRouter).Assembly;
    static readonly Type Protocol = Connector.GetType("UnityBridgeConnector.BridgeProtocol", true);
    static readonly Type Context = Connector.GetType("UnityBridgeConnector.BridgeRequestContext", true);
    const BindingFlags InternalStatic = BindingFlags.Static | BindingFlags.NonPublic;
    public static int Executions;
    public static readonly int MainThreadId = Thread.CurrentThread.ManagedThreadId;

    static HostConnectorAudit()
    {
        if (AssetDatabase.IsAssetImportWorkerProcess()) return;
        var root = Path.GetDirectoryName(UnityEngine.Application.dataPath);
        EditorApplication.update += () =>
        {
            var requestPath = Path.Combine(root, "host-audit-readiness-request");
            if (!File.Exists(requestPath)) return;
            File.Delete(requestPath);
            try
            {
                var request = Activator.CreateInstance(Context, true);
                Context.GetField("Authenticated", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(request, true);
                var rejection = Protocol.GetMethod("Validate", InternalStatic).Invoke(null, new object[] { request, true });
                var capture = typeof(Heartbeat).GetMethod("CaptureState", InternalStatic, null, Type.EmptyTypes, null);
                File.WriteAllText(Path.Combine(root, "host-audit-readiness.json"), JsonConvert.SerializeObject(new
                {
                    accepted = rejection == null, instance = capture.Invoke(null, null), rejection,
                }));
            }
            catch (Exception error)
            {
                File.WriteAllText(Path.Combine(root, "host-audit-readiness.json"), JsonConvert.SerializeObject(new { error = error.ToString() }));
            }
        };
        EditorApplication.update += () =>
        {
            var requestPath = Path.Combine(root, "host-audit-listener-restart-request");
            if (!File.Exists(requestPath)) return;
            File.Delete(requestPath);
            _ = CheckQueuedListenerCancellation(root);
        };
    }

    static async Task CheckQueuedListenerCancellation(string root)
    {
        object result;
        try
        {
            Require(HostConnectorListenerGateTool.Waiting, "The real HTTP gate did not acquire the execution lock");
            var before = Executions;
            var source = (CancellationTokenSource)typeof(HttpServer).GetField("s_Cts", InternalStatic).GetValue(null);
            var previousListener = typeof(HttpServer).GetField("s_Listener", InternalStatic).GetValue(null);
            var token = source.Token;
            Require(!token.IsCancellationRequested, "Listener was already stopped before queuing");
            var request = Activator.CreateInstance(Context, true);
            Context.GetField("ListenerCancellation", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(request, token);
            Context.GetField("DeadlineUnixMs", BindingFlags.Instance | BindingFlags.NonPublic)
                .SetValue(request, (long?)(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 10000));
            // Invoke on the main thread with the actual accepting listener's token.
            // The real HTTP gate above holds the lock, so this call deterministically
            // passes initial validation and suspends at the execution lock.
            var dispatch = typeof(CommandRouter).GetMethod("Dispatch", InternalStatic, null,
                new[] { typeof(string), typeof(JObject), Context }, null);
            var waiting = (Task<object>)dispatch.Invoke(null,
                new object[] { "host_audit_counter", new JObject { ["increment"] = true }, request });
            Require(!waiting.IsCompleted, "Counter mutation did not wait behind the HTTP gate");

            typeof(HttpServer).GetMethod("StopListener", InternalStatic).Invoke(null, null);
            Require(token.IsCancellationRequested, "Stopping the listener did not cancel its requests");
            typeof(HttpServer).GetMethod("Start", InternalStatic).Invoke(null, null);
            Require(HttpServer.IsRunning && !ReferenceEquals(previousListener,
                typeof(HttpServer).GetField("s_Listener", InternalStatic).GetValue(null)), "Listener did not restart");
            HostConnectorListenerGateTool.Release();
            var rejected = JObject.FromObject(await waiting);
            Require((bool)rejected["success"] == false &&
                (string)rejected["data"]["reason"] == "not_ready" &&
                (string)rejected["data"]["completion"] == "not_started", "Old listener waiter was not rejected after acquiring the lock");
            Require(Executions == before, "Old listener waiter mutated state after restart");
            result = new { before, after = Executions, queuedBeforeStop = true, listenerRestarted = true,
                gateEntries = HostConnectorListenerGateTool.Entries, rejected };
        }
        catch (Exception error)
        {
            result = new { error = error.ToString() };
        }
        finally
        {
            HostConnectorListenerGateTool.Release();
        }
        File.WriteAllText(Path.Combine(root, "host-audit-listener-restart.json"), JsonConvert.SerializeObject(result));
    }

    public static object Validate()
    {
        var domain = (string)Protocol.GetField("DomainId", InternalStatic).GetValue(null);
        var generation = (long)Protocol.GetProperty("ReferenceGeneration", InternalStatic).GetValue(null, null);
        Require(!string.IsNullOrEmpty(domain), "Missing domain id");
        CheckRejection("expired", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - 1, domain, generation);
        CheckRejection("stale_domain", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 10000, "previous-domain", generation);
        CheckRejection("stale_references", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 10000, domain, generation - 1);
        using (var cancellation = new CancellationTokenSource())
        {
            var stoppedRequest = Activator.CreateInstance(Context, true);
            Context.GetField("ListenerCancellation", BindingFlags.Instance | BindingFlags.NonPublic)
                .SetValue(stoppedRequest, cancellation.Token);
            cancellation.Cancel();
            var rejected = JObject.FromObject(Protocol.GetMethod("Validate", InternalStatic)
                .Invoke(null, new object[] { stoppedRequest, false }));
            Require((string)rejected["data"]["reason"] == "not_ready" &&
                (string)rejected["data"]["completion"] == "not_started", "Stopped listener allowed execution");
        }
        var captured = JObject.FromObject(Protocol.GetMethod("CaptureContext", InternalStatic).Invoke(null, null));
        Require((bool)captured["success"], "Context failed");
        Require((int)captured["data"]["protocol"] == 1, "Protocol mismatch");
        Require((string)captured["data"]["domainId"] == domain, "Context domain mismatch");
        Require(((JArray)captured["data"]["references"]).Count > 0, "Empty compiler references");
        return new SuccessResponse("Host Connector audit passed", new { domainId = domain, referenceGeneration = generation });
    }

    // Supply a PE whose Execute returns ++StaticCounter. Counts must be 1,1 for
    // cached PE reuse; if the runtime returns 1,2 the host must emit a fresh identity.
    public static object InspectRepeatedAssembly(string encoded)
    {
        var bytes = Convert.FromBase64String(encoded);
        var loader = Connector.GetType("UnityBridgeConnector.Tools.ExecuteCsharp", true)
            .GetMethod("ExecuteAssembly", InternalStatic);
        var before = (long)Protocol.GetProperty("ReferenceGeneration", InternalStatic).GetValue(null, null);
        var first = JObject.FromObject(loader.Invoke(null, new object[] { bytes }));
        var second = JObject.FromObject(loader.Invoke(null, new object[] { bytes }));
        Require((bool)first["success"] && (bool)second["success"], "Repeated assembly invocation failed");
        var after = (long)Protocol.GetProperty("ReferenceGeneration", InternalStatic).GetValue(null, null);
        Require(after == before, "Locationless snippets changed reference generation");
        return new SuccessResponse("Repeated PE behavior", new { first = first["data"], second = second["data"], referenceGeneration = after });
    }

    public static object LoadReference(string path)
    {
        var before = (long)Protocol.GetProperty("ReferenceGeneration", InternalStatic).GetValue(null, null);
        Assembly.LoadFile(Path.GetFullPath(path));
        var after = (long)Protocol.GetProperty("ReferenceGeneration", InternalStatic).GetValue(null, null);
        Require(after > before, "A new location-bearing assembly did not change reference generation");
        return new SuccessResponse("Reference generation changed", new { before, after });
    }

    static void CheckRejection(string expected, long deadline, string domain, long generation)
    {
        var request = Activator.CreateInstance(Context, true);
        Context.GetField("DeadlineUnixMs", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(request, (long?)deadline);
        Context.GetField("DomainId", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(request, domain);
        Context.GetField("ReferenceGeneration", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(request, (long?)generation);
        var result = JObject.FromObject(Protocol.GetMethod("Validate", InternalStatic).Invoke(null, new object[] { request, false }));
        Require(!(bool)result["success"] && (string)result["data"]["completion"] == "not_started" &&
            (string)result["data"]["reason"] == expected, "Wrong rejection for " + expected);
    }

    static void Require(bool valid, string message)
    {
        if (!valid) throw new Exception(message);
    }
}

[UnityBridgeTool(Name = "host_audit_listener_gate")]
public static class HostConnectorListenerGateTool
{
    static TaskCompletionSource<bool> s_Release;
    public static bool Waiting { get; private set; }
    public static int Entries { get; private set; }

    public static async Task<object> HandleCommand(JObject parameters)
    {
        s_Release = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        Waiting = true;
        Entries++;
        var root = Path.GetDirectoryName(UnityEngine.Application.dataPath);
        File.WriteAllText(Path.Combine(root, "host-audit-listener-gate-ready"), Entries.ToString());
        try
        {
            // Bound a broken fixture so the audit cannot hold the execution lock forever.
            if (await Task.WhenAny(s_Release.Task, Task.Delay(15000)) != s_Release.Task)
                throw new Exception("Listener restart audit did not release the HTTP gate.");
            return new SuccessResponse("Listener gate released");
        }
        finally { Waiting = false; }
    }

    public static void Release() => s_Release?.TrySetResult(true);
}

[UnityBridgeTool(Name = "host_audit_main_thread")]
public static class HostConnectorMainThreadTool
{
    public static async Task<object> HandleCommand(JObject parameters)
    {
        RequireMainThread();
        await Task.Delay(20);
        RequireMainThread();
        return new SuccessResponse("Main-thread result", new MainThreadResult());
    }

    static void RequireMainThread()
    {
        if (Thread.CurrentThread.ManagedThreadId != HostConnectorAudit.MainThreadId)
            throw new Exception("Tool execution or serialization left the Unity main thread.");
    }

    sealed class MainThreadResult
    {
        public string projectDataPath
        {
            get
            {
                RequireMainThread();
                // A custom result getter is allowed to use Unity APIs.
                return UnityEngine.Application.dataPath;
            }
        }
        public int threadId
        {
            get { RequireMainThread(); return Thread.CurrentThread.ManagedThreadId; }
        }
    }
}

[UnityBridgeTool(Name = "host_connector_audit")]
public static class HostConnectorAuditTool
{
    public static object HandleCommand(JObject parameters)
    {
        var assembly = parameters?["assembly"]?.ToString();
        var reference = parameters?["referencePath"]?.ToString();
        if (!string.IsNullOrEmpty(reference)) return HostConnectorAudit.LoadReference(reference);
        return string.IsNullOrEmpty(assembly) ? HostConnectorAudit.Validate() : HostConnectorAudit.InspectRepeatedAssembly(assembly);
    }
}

[UnityBridgeTool(Name = "host_audit_delay")]
public static class HostConnectorDelayTool
{
    public static async Task<object> HandleCommand(JObject parameters)
    {
        await Task.Delay((int?)parameters?["milliseconds"] ?? 500);
        return new SuccessResponse("Delay finished", ++HostConnectorAudit.Executions);
    }
}

[UnityBridgeTool(Name = "host_audit_counter")]
public static class HostConnectorCounterTool
{
    public static object HandleCommand(JObject parameters)
    {
        if ((bool?)parameters?["increment"] == true) HostConnectorAudit.Executions++;
        return new SuccessResponse("Execution count", HostConnectorAudit.Executions);
    }
}
