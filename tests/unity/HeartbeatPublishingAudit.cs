// Copied into disposable validation projects only; never shipped in the package.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityBridgeConnector;

[InitializeOnLoad]
[UnityBridgeTool(Name = "heartbeat_publishing_audit")]
public static class HeartbeatPublishingAudit
{
    static readonly string Root = Path.GetDirectoryName(UnityEngine.Application.dataPath);
    static readonly MethodInfo Write = typeof(Heartbeat).GetMethod("Write",
        BindingFlags.Static | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
    static readonly MethodInfo GetFilePath = typeof(Heartbeat).GetMethod("GetFilePath",
        BindingFlags.Static | BindingFlags.NonPublic);

    static HeartbeatPublishingAudit()
    {
        if (AssetDatabase.IsAssetImportWorkerProcess()) return;
        EditorApplication.update += () =>
        {
            var request = Path.Combine(Root, "audit-pause-request");
            if (!File.Exists(request)) return;
            File.Delete(request);
            try { HandleCommand(new JObject { ["action"] = "pause" }); }
            catch (Exception error)
            {
                File.WriteAllText(Path.Combine(Root, "audit-pause.json"),
                    JsonConvert.SerializeObject(new { error = error.ToString() }));
            }
        };
    }

    public static object HandleCommand(JObject parameters)
    {
        var path = (string)GetFilePath.Invoke(null, null);
        if ((string)parameters["action"] == "cost")
        {
            const int count = 100;
            for (var i = 0; i < 5; i++) Write.Invoke(null, null);
            var samples = new double[count];
            var stopwatch = new Stopwatch();
            var start = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            for (var i = 0; i < count; i++)
            {
                stopwatch.Restart();
                Write.Invoke(null, null);
                stopwatch.Stop();
                samples[i] = stopwatch.Elapsed.TotalMilliseconds;
            }
            var published = JObject.Parse(File.ReadAllText(path));
            if ((long)published["timestamp"] < start)
                throw new Exception("Timed heartbeat writes did not reach the instance file");
            return new SuccessResponse("Warm heartbeat write costs (includes reflection)", new
            {
                write_ms = samples, file_bytes = new FileInfo(path).Length,
                component_profile = ProfileWrite(path),
            });
        }

        if ((string)parameters["action"] != "pause" || !EditorApplication.isPlaying)
            return new ErrorResponse("Use cost, or pause while in Play Mode");

        // Start from a freshly published old state. Observe the real pause event,
        // before a later periodic tick can conceal a missing event publication.
        Write.Invoke(null, null);
        var expected = EditorApplication.isPaused ? "playing" : "paused";
        var resultPath = Path.Combine(Root, "audit-pause.json");
        File.Delete(resultPath);
        var elapsed = Stopwatch.StartNew();
        void OnPause(PauseState state)
        {
            try
            {
                var published = JObject.Parse(File.ReadAllText(path));
                File.WriteAllText(resultPath, JsonConvert.SerializeObject(new
                {
                    expected, observed = (string)published["state"],
                    matches = (string)published["state"] == expected,
                    event_ms = elapsed.Elapsed.TotalMilliseconds,
                }));
            }
            finally { EditorApplication.pauseStateChanged -= OnPause; }
        }

        EditorApplication.pauseStateChanged += OnPause;
        try
        {
            EditorApplication.isPaused = !EditorApplication.isPaused;
            // Unity 2021 batch-mode pauses can suspend HTTP async continuations.
            // File requests on Editor.update keep this audit focused on heartbeat state.
            return new SuccessResponse("Pause change requested", new { expected });
        }
        catch
        {
            EditorApplication.pauseStateChanged -= OnPause;
            throw;
        }
    }

    static object ProfileWrite(string path)
    {
        var capture = typeof(Heartbeat).GetMethod("CaptureState",
            BindingFlags.Static | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
        var captureTimes = new double[30];
        var atomicTimes = new double[30];
        var processTimes = new double[30];
        var directoryTimes = new double[30];
        var workerTimes = new double[30];
        for (var index = 0; index < captureTimes.Length; index++)
        {
            var watch = Stopwatch.StartNew();
            var contents = JsonConvert.SerializeObject(capture.Invoke(null, null));
            captureTimes[index] = watch.Elapsed.TotalMilliseconds;
            watch.Restart();
            // Use the real instance path and payload, just like the timed full writes.
            AtomicFile.WriteAllText(path, contents);
            atomicTimes[index] = watch.Elapsed.TotalMilliseconds;
            watch.Restart();
            using (var process = Process.GetCurrentProcess()) { var pid = process.Id; }
            processTimes[index] = watch.Elapsed.TotalMilliseconds;
            watch.Restart();
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            directoryTimes[index] = watch.Elapsed.TotalMilliseconds;
            watch.Restart();
            AssetDatabase.IsAssetImportWorkerProcess();
            workerTimes[index] = watch.Elapsed.TotalMilliseconds;
        }
        return new { capture_ms = captureTimes, atomic_ms = atomicTimes,
            process_ms = processTimes, directory_ms = directoryTimes, worker_ms = workerTimes };
    }
}
