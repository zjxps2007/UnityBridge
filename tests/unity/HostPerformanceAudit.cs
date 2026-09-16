// Disposable-project measurement only; never shipped with the Connector.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityBridgeConnector;

[InitializeOnLoad]
public static class HostPerformanceAudit
{
    static readonly string Root = Path.GetDirectoryName(Application.dataPath);
    static readonly Stopwatch Clock = Stopwatch.StartNew();
    static readonly List<double> Gaps = new List<double>();
    static double last;
    static bool recording;
    static HostPerformanceAudit() { EditorApplication.update += Tick; }
    public static void Start() { Tick(); }
    static void Tick()
    {
        double now = Clock.Elapsed.TotalMilliseconds;
        // Batch-mode Editors may spin at tens of thousands of updates/second.
        // Keep only gaps above 1 ms so the sample covers the whole command run,
        // rather than truncating after the first few hundred milliseconds.
        if (recording && last > 0 && now - last > 1) Gaps.Add(now - last);
        last = now;
        if (File.Exists(Path.Combine(Root, "audit-stop"))) EditorApplication.Exit(0);
    }
    public static object Measure(JObject parameters)
    {
        string action = (string)parameters["action"];
        if (action == "start") { Gaps.Clear(); recording = true; last = Clock.Elapsed.TotalMilliseconds; }
        if (action == "stop") recording = false;
        return new SuccessResponse("Editor update intervals", new { gaps_ms = Gaps.ToArray() });
    }
}

[UnityBridgeTool(Name = "host_performance_audit")]
public static class HostPerformanceAuditTool
{
    public static object HandleCommand(JObject parameters) => HostPerformanceAudit.Measure(parameters);
}
