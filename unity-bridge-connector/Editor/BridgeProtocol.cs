using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Threading;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.Compilation;
using ReflectionAssembly = System.Reflection.Assembly;

namespace UnityBridgeConnector
{
    // Metadata belongs to the transport envelope, never to public tool parameters.
    internal sealed class BridgeRequestContext
    {
        internal string RequestId;
        internal long? DeadlineUnixMs;
        internal string DomainId;
        internal long? ReferenceGeneration;
        internal bool Authenticated;
        internal CancellationToken ListenerCancellation;
    }

    internal static class BridgeProtocol
    {
        internal const int Version = 1;
        internal static readonly string DomainId = Guid.NewGuid().ToString("N");
        static long s_ReferenceGeneration;
        static long s_CachedGeneration = -1;
        static object[] s_References;
        static string s_LanguageVersion;

        static BridgeProtocol()
        {
            AppDomain.CurrentDomain.AssemblyLoad += (_, args) =>
            {
                // A snippet loaded from bytes has no location and cannot be a compiler
                // reference. It must not invalidate its own cached compilation context.
                if (HasLocation(args.LoadedAssembly))
                    Interlocked.Increment(ref s_ReferenceGeneration);
            };
        }

        internal static long ReferenceGeneration => Interlocked.Read(ref s_ReferenceGeneration);

        internal static bool IsInternalCommand(string command) =>
            command == "bridge_context" || command == "bridge_exec_assembly";

        internal static ErrorResponse Reject(string reason, string message) => new ErrorResponse(message, new
        {
            completion = "not_started",
            reason,
            domainId = DomainId,
            referenceGeneration = ReferenceGeneration,
        });

        internal static ErrorResponse Validate(BridgeRequestContext request, bool requireReady = false)
        {
            if (request == null) return null;
            // Parsing can overlap a listener restart, or a command can still be
            // waiting for the execution lock. Its old connection cannot authorize
            // execution after the listener that accepted it has stopped.
            if (request.ListenerCancellation.IsCancellationRequested)
                return Reject("not_ready", "Unity connector is stopping.");
            if (request.DeadlineUnixMs.HasValue &&
                DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() >= request.DeadlineUnixMs.Value)
                return Reject("expired", "Request deadline expired before execution.");
            if (request.DomainId != null && request.DomainId != DomainId)
                return Reject("stale_domain", "Unity reloaded before the request could execute.");
            if (request.ReferenceGeneration.HasValue && request.ReferenceGeneration.Value != ReferenceGeneration)
                return Reject("stale_references", "Unity assembly references changed before execution.");
            if (requireReady && !IsReady())
                return Reject("not_ready", "Unity is not ready to execute this request.");
            return null;
        }

        internal static bool IsReady()
        {
            var state = JObject.FromObject(Heartbeat.CaptureState())["state"]?.ToString();
            return HttpServer.IsRunning && (state == "ready" || state == "playing" || state == "paused");
        }

        // Invoked only on the Editor main thread. The compiler receives Unity's
        // references rather than the framework assemblies of its own runtime.
        internal static object CaptureContext()
        {
            if (s_LanguageVersion == null) s_LanguageVersion = GetLanguageVersion();
            var generation = ReferenceGeneration;
            if (s_References == null || s_CachedGeneration != generation)
            {
                var references = new List<object>();
                var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
                {
                    try
                    {
                        if (!HasLocation(assembly)) continue;
                        var name = assembly.GetName().Name;
                        if (!names.Add(name)) continue;
                        references.Add(new
                        {
                            path = Path.GetFullPath(assembly.Location),
                            name,
                            mvid = assembly.ManifestModule.ModuleVersionId.ToString("D"),
                        });
                    }
                    catch (NotSupportedException) { }
                    catch (IOException) { }
                }
                s_References = references.ToArray();
                s_CachedGeneration = generation;
            }
            var instance = JObject.FromObject(Heartbeat.CaptureState());
            return new SuccessResponse("Unity compilation context", new
            {
                protocol = Version,
                domainId = DomainId,
                referenceGeneration = s_CachedGeneration,
                projectPath = instance["projectPath"]?.ToString(),
                pid = (int)instance["pid"],
                languageVersion = s_LanguageVersion,
                references = s_References,
                instance,
            });
        }

        internal static object ExecuteAssembly(JObject parameters, BridgeRequestContext request)
        {
            if (request == null || !request.Authenticated)
                return Reject("unauthorized", "Host authentication required.");
            if (string.IsNullOrEmpty(request.DomainId) || !request.ReferenceGeneration.HasValue)
                return Reject("invalid_request", "domain_id and reference_generation are required.");
            var rejected = Validate(request, true);
            if (rejected != null) return rejected;
            var encoded = parameters?["assembly"]?.ToString();
            if (string.IsNullOrEmpty(encoded) || encoded.Length > 32 * 1024 * 1024)
                return Reject("invalid_request", "A base64 assembly of at most 24 MiB is required.");
            byte[] bytes;
            try { bytes = Convert.FromBase64String(encoded); }
            catch (FormatException) { return Reject("invalid_request", "Invalid base64 assembly."); }
            // Decoding can take time; the final check precedes Assembly.Load, which
            // itself may run user module initializers and must count as dispatch.
            rejected = Validate(request, true);
            return rejected ?? Tools.ExecuteCsharp.ExecuteAssembly(bytes);
        }

        static bool HasLocation(ReflectionAssembly assembly)
        {
            try { return !assembly.IsDynamic && !string.IsNullOrEmpty(assembly.Location); }
            catch (NotSupportedException) { return false; }
        }

        static string GetLanguageVersion()
        {
            try
            {
                var ownName = typeof(BridgeProtocol).Assembly.GetName().Name;
                foreach (var assembly in CompilationPipeline.GetAssemblies(AssembliesType.Editor))
                {
                    if (assembly.name != ownName) continue;
                    // Reflection keeps older supported Editor API surfaces compatible.
                    object options = assembly.compilerOptions;
                    var property = options.GetType().GetProperty("LanguageVersion");
                    var value = property?.GetValue(options, null)?.ToString();
                    if (string.IsNullOrEmpty(value))
                        value = options.GetType().GetField("LanguageVersion")?.GetValue(options)?.ToString();
                    if (!string.IsNullOrEmpty(value) && value != "latest" && value != "default") return value;
                }
            }
            catch (Exception) { }
#if UNITY_2021_2_OR_NEWER
            return "9.0";
#else
            return "8.0";
#endif
        }
    }
}
