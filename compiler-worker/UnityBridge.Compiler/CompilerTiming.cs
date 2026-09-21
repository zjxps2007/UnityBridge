using System.Diagnostics;
using System.Text.Json;

namespace UnityBridge.Compiler;

// Explicit local diagnostics only. No source, results, paths or tokens are recorded.
internal static class CompilerTiming
{
    private static readonly string? DirectoryPath = Environment.GetEnvironmentVariable("UNITY_BRIDGE_TIMING_DIR");

    internal static void Mark(string stage, CompileRequest request)
    {
        if (string.IsNullOrEmpty(DirectoryPath)) return;
        try
        {
            Directory.CreateDirectory(DirectoryPath);
            var value = new { stage, pid = Environment.ProcessId, request_id = request.RequestId,
                parent_request_id = request.ParentRequestId, ticks = Stopwatch.GetTimestamp(), frequency = Stopwatch.Frequency,
                unix_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() };
            File.AppendAllText(Path.Combine(DirectoryPath, $"compiler-{Environment.ProcessId}.jsonl"),
                JsonSerializer.Serialize(value) + "\n");
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        catch (ArgumentException) { }
        catch (NotSupportedException) { }
    }
}
