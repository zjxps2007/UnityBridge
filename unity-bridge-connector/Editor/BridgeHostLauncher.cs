using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using UnityEditor;

namespace UnityBridgeConnector
{
    // Authentication is also read by the HTTP thread and must not initialize Unity APIs.
    internal static class BridgeHostConfiguration
    {
        internal static string HostHome => Environment.GetEnvironmentVariable("UNITY_BRIDGE_HOST_HOME") ??
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".unity-bridge", "host");

        internal static bool Authenticate(string supplied)
        {
            if (string.IsNullOrEmpty(supplied)) return false;
            try
            {
                var expected = ReadLauncher()?["token"]?.ToString();
                if (string.IsNullOrEmpty(expected) || expected.Length < 32 || supplied.Length != expected.Length)
                    return false;
                var difference = 0;
                for (var index = 0; index < expected.Length; index++)
                    difference |= supplied[index] ^ expected[index];
                return difference == 0;
            }
            catch (Exception) { return false; }
        }

        internal static JObject ReadLauncher()
        {
            var path = Path.Combine(HostHome, "launcher.json");
            if (!File.Exists(path)) return null;
            var launcher = JObject.Parse(File.ReadAllText(path));
            return (int?)launcher["protocol"] == BridgeProtocol.Version ? launcher : null;
        }
    }

    [InitializeOnLoad]
    internal static class BridgeHostLauncher
    {
        static double s_NextCheck;
        static int s_CheckRunning;
        static int s_NotifyRunning;
        static int s_NotifyPending;

        internal static void NotifyStateChanged()
        {
            Interlocked.Exchange(ref s_NotifyPending, 1);
            if (Interlocked.CompareExchange(ref s_NotifyRunning, 1, 0) != 0) return;
            _ = Task.Run(() =>
            {
                try
                {
                    while (Interlocked.Exchange(ref s_NotifyPending, 0) != 0)
                    {
                        try
                        {
                            var launcher = BridgeHostConfiguration.ReadLauncher();
                            var runtimeId = launcher?["runtimeId"]?.ToString();
                            if (runtimeId == null || runtimeId.Length != 32 || !runtimeId.All(Uri.IsHexDigit)) continue;
                            var path = Path.Combine(BridgeHostConfiguration.HostHome, "instances", runtimeId + ".json");
                            if (!File.Exists(path)) continue;
                            var endpoint = JObject.Parse(File.ReadAllText(path));
                            var port = (int?)endpoint["port"] ?? 0;
                            if (port <= 0 || port > 65535 || endpoint["runtimeId"]?.ToString() != runtimeId ||
                                endpoint["token"]?.ToString() != launcher["token"]?.ToString()) continue;
                            var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + port + "/changed");
                            request.Method = "POST";
                            request.ContentType = "application/json";
                            request.ContentLength = 2;
                            request.Proxy = null;
                            request.AllowAutoRedirect = false;
                            request.KeepAlive = false;
                            request.Timeout = request.ReadWriteTimeout = 1000;
                            request.Headers["X-UnityBridge-Token"] = launcher["token"].ToString();
                            using (var stream = request.GetRequestStream())
                                stream.Write(new byte[] { (byte)'{', (byte)'}' }, 0, 2);
                            using (request.GetResponse()) { }
                        }
                        catch (Exception) { /* Older/unavailable hosts retain periodic discovery. */ }
                    }
                }
                finally
                {
                    Interlocked.Exchange(ref s_NotifyRunning, 0);
                    if (Volatile.Read(ref s_NotifyPending) != 0) NotifyStateChanged();
                }
            });
        }

        static BridgeHostLauncher()
        {
            if (AssetDatabase.IsAssetImportWorkerProcess()) return;
            EditorApplication.delayCall += Check;
            EditorApplication.update += Check;
        }

        static void Check()
        {
            if (EditorApplication.timeSinceStartup < s_NextCheck || EditorApplication.isCompiling || EditorApplication.isUpdating)
                return;
            s_NextCheck = EditorApplication.timeSinceStartup + 5;
            if (Interlocked.Exchange(ref s_CheckRunning, 1) != 0) return;
            // No filesystem probes or process startup waits run on the Editor thread.
            _ = Task.Run(() =>
            {
                try { EnsureHost(); }
                catch (Exception) { /* Missing/unavailable hosts retain the direct CLI path. */ }
                finally { Interlocked.Exchange(ref s_CheckRunning, 0); }
            });
        }

        static void EnsureHost()
        {
            var launcher = BridgeHostConfiguration.ReadLauncher();
            if (launcher == null) return;
            var runtimeId = launcher["runtimeId"]?.ToString();
            if (runtimeId == null || runtimeId.Length != 32 || !runtimeId.All(Uri.IsHexDigit)) return;
            var argv = (launcher["argv"] as JArray)?.Values<string>().ToArray();
            if (argv == null || argv.Length == 0 || !Path.IsPathRooted(argv[0]) || !File.Exists(argv[0])) return;
            var registryPath = Path.Combine(BridgeHostConfiguration.HostHome, "instances", runtimeId + ".json");
            if (File.Exists(registryPath))
            {
                try
                {
                    var registry = JObject.Parse(File.ReadAllText(registryPath));
                    if (registry["runtimeId"]?.ToString() == runtimeId && (int?)registry["pid"] > 0)
                    {
                        using (var process = Process.GetProcessById((int)registry["pid"]))
                            if (!process.HasExited && IsResponsiveHost(registry, launcher)) return;
                    }
                }
                catch (Exception) { }
            }
            var info = new ProcessStartInfo
            {
                FileName = argv[0],
                Arguments = string.Join(" ", argv.Skip(1).Select(QuoteArgument)),
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
                WorkingDirectory = Path.GetDirectoryName(argv[0]),
            };
            // The host owns its singleton lock; simultaneous Editors can safely race.
            using (Process.Start(info)) { }
        }

        static bool IsResponsiveHost(JObject registry, JObject launcher)
        {
            // A stale PID can have been reused by an unrelated process. Probe only
            // on this background watchdog, never in status or normal command paths.
            try
            {
                var port = (int?)registry["port"] ?? 0;
                if (port <= 0 || port > 65535 || (int?)registry["protocol"] != BridgeProtocol.Version ||
                    registry["version"]?.ToString() != launcher["version"]?.ToString() ||
                    registry["token"]?.ToString() != launcher["token"]?.ToString()) return false;
                var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + port + "/health");
                request.Method = "POST";
                request.ContentType = "application/json";
                request.ContentLength = 2;
                request.Proxy = null;
                request.AllowAutoRedirect = false;
                request.KeepAlive = false;
                request.Timeout = 1000;
                request.ReadWriteTimeout = 1000;
                request.Headers["X-UnityBridge-Token"] = launcher["token"].ToString();
                using (var stream = request.GetRequestStream())
                    stream.Write(new byte[] { (byte)'{', (byte)'}' }, 0, 2);
                using (var response = (HttpWebResponse)request.GetResponse())
                using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                {
                    if (response.StatusCode != HttpStatusCode.OK) return false;
                    var buffer = new char[16385];
                    var length = 0;
                    int count;
                    while (length < buffer.Length && (count = reader.Read(buffer, length, buffer.Length - length)) > 0)
                        length += count;
                    if (length == buffer.Length) return false;
                    var health = JObject.Parse(new string(buffer, 0, length));
                    return (int?)health["protocol"] == BridgeProtocol.Version &&
                        (int?)health["pid"] == (int?)registry["pid"] &&
                        health["runtimeId"]?.ToString() == launcher["runtimeId"]?.ToString() &&
                        health["version"]?.ToString() == launcher["version"]?.ToString();
                }
            }
            catch (Exception) { return false; }
        }

        static string QuoteArgument(string value)
        {
            if (value == null) value = "";
            var result = new StringBuilder("\"");
            var slashes = 0;
            foreach (var ch in value)
            {
                if (ch == '\\') { slashes++; continue; }
                if (ch == '"') result.Append('\\', slashes * 2 + 1);
                else result.Append('\\', slashes);
                result.Append(ch);
                slashes = 0;
            }
            result.Append('\\', slashes * 2);
            return result.Append('"').ToString();
        }
    }
}
