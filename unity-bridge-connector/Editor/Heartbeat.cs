using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json;
using UnityEditor;
using UnityEngine;

namespace UnityBridgeConnector
{
    [InitializeOnLoad]
    public static class Heartbeat
    {
        static readonly string s_Dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".unity-bridge", "instances");

        static double s_LastWrite;
        const double INTERVAL = 0.5;
        static string s_LastAttemptedState;
        static bool s_LastAttemptedCompileErrors;
        static int s_LastAttemptedPort;
        static long s_LastAttemptedReferenceGeneration = -1;
        const double REFRESH_GRACE_SECONDS = 1.0;
        const double COMPILE_GRACE_SECONDS = 5.0;
        const double PLAYMODE_GRACE_SECONDS = 5.0;
        static string s_ConnectorVersion;
        static string s_ForcedState;
        static double s_RefreshRequestTime;
        static double s_CompileRequestTime;
        static double s_PlayModeTransitionTime;
        static string s_FilePath;

        static Heartbeat()
        {
            // Only the main editor owns this project's instance file and lifecycle events.
            if (AssetDatabase.IsAssetImportWorkerProcess()) return;

            EditorApplication.update += Tick;
            EditorApplication.quitting += Cleanup;
            UnityEditor.PackageManager.Events.registeredPackages += _ => s_ConnectorVersion = null;
            AssemblyReloadEvents.beforeAssemblyReload += OnBeforeAssemblyReload;
            AssemblyReloadEvents.afterAssemblyReload += () =>
            {
                s_ForcedState = null;
                s_RefreshRequestTime = 0;
                s_CompileRequestTime = 0;
                s_PlayModeTransitionTime = 0;
                s_LastWrite = 0;
            };
            EditorApplication.playModeStateChanged += OnPlayModeChanged;
            EditorApplication.pauseStateChanged += _ => Write();
        }

        static void OnBeforeAssemblyReload()
        {
            WriteState("reloading");
        }

        static void OnPlayModeChanged(PlayModeStateChange change)
        {
            if (change == PlayModeStateChange.ExitingEditMode)
                MarkEnteringPlayMode();
            else if (change == PlayModeStateChange.ExitingPlayMode)
                MarkExitingPlayMode();
            else if (change == PlayModeStateChange.EnteredPlayMode || change == PlayModeStateChange.EnteredEditMode)
            {
                s_PlayModeTransitionTime = 0;
                s_ForcedState = null;
                Write();
            }
        }

        static void WriteState(string state)
        {
            s_ForcedState = state;
            Write();
        }

        /// <summary>
        /// Marks that asset refresh/import was requested. Keeps "refreshing"
        /// visible briefly so external waiters do not pass an older "ready".
        /// </summary>
        public static void MarkRefreshRequested()
        {
            s_RefreshRequestTime = EditorApplication.timeSinceStartup;
            WriteState("refreshing");
        }

        /// <summary>
        /// Marks that a compile was requested. Keeps "compiling" state forced
        /// for a grace period so the CLI poller never sees a premature "ready".
        /// </summary>
        public static void MarkCompileRequested()
        {
            s_CompileRequestTime = EditorApplication.timeSinceStartup;
            WriteState("compiling");
        }

        public static void MarkEnteringPlayMode()
        {
            s_PlayModeTransitionTime = EditorApplication.timeSinceStartup;
            WriteState("entering_playmode");
        }

        public static void MarkExitingPlayMode()
        {
            s_PlayModeTransitionTime = EditorApplication.timeSinceStartup;
            WriteState("exiting_playmode");
        }

        internal static void PublishServerStarted()
        {
            // Discovery should not wait for the first periodic Editor update.
            Write();
        }

        internal static void PublishCompletedOperation()
        {
            s_ForcedState = null;
            s_RefreshRequestTime = s_CompileRequestTime = s_PlayModeTransitionTime = 0;
            Write();
        }

        static void Tick()
        {
            if (!HttpServer.IsRunning) return;

            var now = EditorApplication.timeSinceStartup;
            UpdatePendingState(now);
            var state = s_ForcedState ?? GetState();
            var compileErrors = EditorUtility.scriptCompilationFailed;
            var port = HttpServer.Port;
            // Check cheap state fields each tick; serialize/write only when due or changed.
            if (now - s_LastWrite < INTERVAL && state == s_LastAttemptedState &&
                compileErrors == s_LastAttemptedCompileErrors && port == s_LastAttemptedPort &&
                BridgeProtocol.ReferenceGeneration == s_LastAttemptedReferenceGeneration)
                return;
            Write(state, compileErrors, port);
        }

        static void UpdatePendingState(double now)
        {
            if (s_PlayModeTransitionTime > 0 &&
                (s_ForcedState == "entering_playmode" || s_ForcedState == "exiting_playmode"))
            {
                if (now - s_PlayModeTransitionTime < PLAYMODE_GRACE_SECONDS)
                {
                    return;
                }
                s_PlayModeTransitionTime = 0;
            }

            if (s_CompileRequestTime > 0)
            {
                if (now - s_CompileRequestTime < COMPILE_GRACE_SECONDS && EditorApplication.isCompiling == false)
                {
                    return;
                }
                s_CompileRequestTime = 0;
            }

            if (s_RefreshRequestTime > 0)
            {
                if (now - s_RefreshRequestTime < REFRESH_GRACE_SECONDS &&
                    EditorApplication.isUpdating == false &&
                    EditorApplication.isCompiling == false)
                {
                    return;
                }
                s_RefreshRequestTime = 0;
            }

            s_ForcedState = null;
        }

        static string GetFilePath()
        {
            if (s_FilePath != null) return s_FilePath;
            var projectPath = GetProjectPath();
            using var md5 = MD5.Create();
            var hash = BitConverter.ToString(md5.ComputeHash(Encoding.UTF8.GetBytes(projectPath)))
                .Replace("-", "").Substring(0, 16).ToLower();
            s_FilePath = Path.Combine(s_Dir, $"{hash}.json");
            return s_FilePath;
        }

        static string GetProjectPath()
        {
            var projectPath = Path.GetDirectoryName(Application.dataPath);
            if (string.IsNullOrEmpty(projectPath))
                projectPath = Application.dataPath;
            return projectPath.Replace('\\', '/');
        }

        static void Write()
        {
            if (AssetDatabase.IsAssetImportWorkerProcess()) return;
            Write(s_ForcedState ?? GetState(), EditorUtility.scriptCompilationFailed, HttpServer.Port);
        }

        static void Write(string state, bool compileErrors, int port)
        {
            // Public state/cleanup methods can also be called directly from import code.
            if (AssetDatabase.IsAssetImportWorkerProcess()) return;

            // Failed writes also count as attempts so transient I/O failures cannot busy-loop.
            var changed = state != s_LastAttemptedState || compileErrors != s_LastAttemptedCompileErrors ||
                port != s_LastAttemptedPort || BridgeProtocol.ReferenceGeneration != s_LastAttemptedReferenceGeneration;
            s_LastWrite = EditorApplication.timeSinceStartup;
            s_LastAttemptedState = state;
            s_LastAttemptedCompileErrors = compileErrors;
            s_LastAttemptedPort = port;
            s_LastAttemptedReferenceGeneration = BridgeProtocol.ReferenceGeneration;
            try
            {
                Directory.CreateDirectory(s_Dir);
                AtomicFile.WriteAllText(GetFilePath(), JsonConvert.SerializeObject(CaptureState(state, compileErrors, port)));
                if (changed) BridgeHostLauncher.NotifyStateChanged();
            }
            catch
            {
            }
        }

        // Called on the editor main thread. Pending refresh/compile/play transitions
        // remain visible even before Unity's corresponding busy flag becomes true.
        internal static object CaptureState()
        {
            return CaptureState(s_ForcedState ?? GetState(), EditorUtility.scriptCompilationFailed, HttpServer.Port);
        }

        static object CaptureState(string state, bool compileErrors, int port)
        {
            return new
            {
                state,
                projectPath = GetProjectPath(),
                port,
                pid = System.Diagnostics.Process.GetCurrentProcess().Id,
                unityVersion = Application.unityVersion,
                connectorVersion = GetConnectorVersion(),
                timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                compileErrors,
                bridgeProtocol = BridgeProtocol.Version,
                domainId = BridgeProtocol.DomainId,
                referenceGeneration = BridgeProtocol.ReferenceGeneration,
            };
        }

        static string GetConnectorVersion()
        {
            if (s_ConnectorVersion != null) return s_ConnectorVersion;

            // Package metadata is the version source for Git, local, and embedded installs.
            // Resolve it once per domain/package change, not on every heartbeat or request.
            var version = UnityEditor.PackageManager.PackageInfo.FindForAssembly(typeof(Heartbeat).Assembly)?.version;
            s_ConnectorVersion = string.IsNullOrEmpty(version) ? "unknown" : version;
            return s_ConnectorVersion;
        }

        static string GetState()
        {
            if (EditorApplication.isCompiling) return "compiling";
            if (EditorApplication.isUpdating) return "refreshing";
            if (EditorOperations.PendingState != null) return EditorOperations.PendingState;
            if (EditorApplication.isPlaying)
                return EditorApplication.isPaused ? "paused" : "playing";
            return "ready";
        }

        public static void Cleanup()
        {
            MarkStopped();
        }

        public static void MarkStopped()
        {
            s_ForcedState = "stopped";
            Write();
        }
    }
}
