using System;
using System.Diagnostics;
using System.IO;
using Newtonsoft.Json.Linq;

namespace UnityBridgeConnector
{
    // Explicit diagnostics only. Performance gates run with this disabled.
    // No Unity API, request parameters, source code, results or tokens are logged.
    internal static class BridgeTiming
    {
        static readonly string DirectoryPath = Environment.GetEnvironmentVariable("UNITY_BRIDGE_TIMING_DIR");
        static readonly object Gate = new object();
        static readonly int Pid = Process.GetCurrentProcess().Id;

        internal static void Mark(string stage, string requestId)
        {
            if (string.IsNullOrEmpty(DirectoryPath)) return;
            try
            {
                var value = new JObject
                {
                    ["stage"] = stage, ["pid"] = Pid, ["request_id"] = requestId,
                    ["ticks"] = Stopwatch.GetTimestamp(), ["frequency"] = Stopwatch.Frequency,
                    ["unix_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                };
                lock (Gate)
                {
                    Directory.CreateDirectory(DirectoryPath);
                    File.AppendAllText(Path.Combine(DirectoryPath, "unity-" + Pid + ".jsonl"),
                        value.ToString(Newtonsoft.Json.Formatting.None) + "\n");
                }
            }
            catch (Exception) { /* Timing output must not alter command behavior. */ }
        }
    }
}
