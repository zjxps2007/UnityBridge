// Copied into disposable native validation projects; never shipped in the package.
using System;
using System.Reflection;
using System.IO;
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
    }

    public static object Validate()
    {
        var domain = (string)Protocol.GetField("DomainId", InternalStatic).GetValue(null);
        var generation = (long)Protocol.GetProperty("ReferenceGeneration", InternalStatic).GetValue(null, null);
        Require(!string.IsNullOrEmpty(domain), "Missing domain id");
        CheckRejection("expired", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - 1, domain, generation);
        CheckRejection("stale_domain", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 10000, "previous-domain", generation);
        CheckRejection("stale_references", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 10000, domain, generation - 1);
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
