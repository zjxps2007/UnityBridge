// Copied into an isolated Unity validation project; never shipped in the package.
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Reflection.Emit;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityBridgeConnector;

[InitializeOnLoad]
public static class StartupDiscoveryAudit
{
    static readonly string Root = Path.GetDirectoryName(Application.dataPath);
    static readonly string Domain = Guid.NewGuid().ToString("N");
    static double lastWrite;
    public static int ParameterConstructions;

    static StartupDiscoveryAudit()
    {
        if (AssetDatabase.IsAssetImportWorkerProcess()) return;
        EditorApplication.update += Tick;
    }

    public static void Start() { Tick(); }

    static void Tick()
    {
        if (File.Exists(Path.Combine(Root, "audit-stop")) || EditorApplication.timeSinceStartup > 240)
        {
            EditorApplication.Exit(0);
            return;
        }
        if (EditorApplication.timeSinceStartup - lastWrite < .1) return;
        lastWrite = EditorApplication.timeSinceStartup;
        File.WriteAllText(Path.Combine(Root, "audit-status.json"), JsonConvert.SerializeObject(new {
            domain = Domain, pid = System.Diagnostics.Process.GetCurrentProcess().Id,
            port = HttpServer.Port, http_running = HttpServer.IsRunning,
            is_compiling = EditorApplication.isCompiling, is_updating = EditorApplication.isUpdating,
            compile_errors = EditorUtility.scriptCompilationFailed, unity = Application.unityVersion
        }));
    }

    public static object Validate()
    {
        Require(ParameterConstructions == 0, "A handler lookup constructed parameter schemas");
        var first = ToolDiscovery.GetToolSchemas();
        Require(ParameterConstructions > 0, "Parameter schema was not generated on list");
        var constructions = ParameterConstructions;
        ToolDiscovery.GetToolSchemas();
        Require(ParameterConstructions == constructions, "Schema cache was rebuilt on repeat list");
        var expectedCount = first.Count;
        first.Clear();
        Require(ToolDiscovery.GetToolSchemas().Count == expectedCount, "Caller changed cached list");

        // Assembly.Load/Reflection.Emit tools must appear even outside TypeCache.
        string command = "dynamic_" + Guid.NewGuid().ToString("N");
        var assembly = AppDomain.CurrentDomain.DefineDynamicAssembly(new AssemblyName(command), AssemblyBuilderAccess.Run);
        var module = assembly.DefineDynamicModule(command);
        AddTool(module, "NoHandler", command, false);
        var valid = AddTool(module, "ValidHandler", command, true);
        Require(ToolDiscovery.FindHandler(command)?.DeclaringType == valid, "First valid duplicate handler was lost");
        var before = ToolDiscovery.GetToolSchemas();
        var schema = JArray.FromObject(before).OfType<JObject>().Single(x => (string)x["name"] == command);
        Require((string)schema["description"] == "NoHandler", "First duplicate schema changed");

        var legacy = JArray.FromObject(LegacyToolDiscovery.GetToolSchemas());
        var current = JArray.FromObject(ToolDiscovery.GetToolSchemas());
        Require(JToken.DeepEquals(legacy, current), "Schema order or contents differ from previous implementation");
        foreach (var entry in current.OfType<JObject>())
        {
            var name = (string)entry["name"];
            Require(ToolDiscovery.FindHandler(name) == LegacyToolDiscovery.FindHandler(name), "Handler changed: " + name);
        }
        Require(ToolDiscovery.FindHandler(null) == null, "Null lookup should return null");
        Require(ToolDiscovery.FindHandler("missing_startup_audit") == null, "Unknown command should return null");
        return new SuccessResponse("Discovery checks passed", new { schemas = current.Count, domain = Domain, revision = StartupRevision.Value });
    }

    static Type AddTool(ModuleBuilder module, string typeName, string command, bool handler)
    {
        var builder = module.DefineType(typeName, TypeAttributes.Public | TypeAttributes.Abstract | TypeAttributes.Sealed);
        builder.SetCustomAttribute(new CustomAttributeBuilder(typeof(UnityBridgeToolAttribute).GetConstructor(Type.EmptyTypes),
            new object[0], new[] { typeof(UnityBridgeToolAttribute).GetProperty("Name"), typeof(UnityBridgeToolAttribute).GetProperty("Description") },
            new object[] { command, typeName }));
        if (handler)
        {
            var method = builder.DefineMethod("HandleCommand", MethodAttributes.Public | MethodAttributes.Static,
                typeof(object), new[] { typeof(JObject) });
            var il = method.GetILGenerator();
            il.Emit(OpCodes.Ldnull);
            il.Emit(OpCodes.Ret);
        }
        return builder.CreateType();
    }

    static void Require(bool value, string message)
    {
        if (!value) throw new Exception(message);
    }
}

public class CountingParameterAttribute : ToolParameterAttribute
{
    public CountingParameterAttribute() : base("Lazy schema probe") { StartupDiscoveryAudit.ParameterConstructions++; }
}

[UnityBridgeTool(Name = "startup_discovery_audit")]
public static class StartupDiscoveryAuditTool
{
    public class Parameters { [CountingParameter] public int Probe { get; set; } }
    public static object HandleCommand(JObject parameters) => StartupDiscoveryAudit.Validate();
}
