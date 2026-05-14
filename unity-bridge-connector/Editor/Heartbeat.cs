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
        const double REFRESH_GRACE_SECONDS = 1.0;
        const double COMPILE_GRACE_SECONDS = 5.0;
        const double PLAYMODE_GRACE_SECONDS = 5.0;
        const string CONNECTOR_VERSION = "0.1.2";
        static string s_ForcedState;
        static double s_RefreshRequestTime;
        static double s_CompileRequestTime;
        static double s_PlayModeTransitionTime;
        static string s_FilePath;

        static Heartbeat()
        {
            EditorApplication.update += Tick;
            EditorApplication.quitting += Cleanup;
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

        static void Tick()
        {
            if (!HttpServer.IsRunning) return;

            var now = EditorApplication.timeSinceStartup;
            if (now - s_LastWrite < INTERVAL) return;
            s_LastWrite = now;

            if (s_PlayModeTransitionTime > 0 &&
                (s_ForcedState == "entering_playmode" || s_ForcedState == "exiting_playmode"))
            {
                if (now - s_PlayModeTransitionTime < PLAYMODE_GRACE_SECONDS)
                {
                    Write();
                    return;
                }
                s_PlayModeTransitionTime = 0;
            }

            if (s_CompileRequestTime > 0)
            {
                if (now - s_CompileRequestTime < COMPILE_GRACE_SECONDS && EditorApplication.isCompiling == false)
                {
                    Write();
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
                    Write();
                    return;
                }
                s_RefreshRequestTime = 0;
            }

            s_ForcedState = null;
            Write();
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
            var projectPath = GetProjectPath();
            var status = new
            {
                state = s_ForcedState ?? GetState(),
                projectPath,
                port = HttpServer.Port,
                pid = System.Diagnostics.Process.GetCurrentProcess().Id,
                unityVersion = Application.unityVersion,
                connectorVersion = GetConnectorVersion(),
                timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                compileErrors = EditorUtility.scriptCompilationFailed,
            };

            try
            {
                Directory.CreateDirectory(s_Dir);
                AtomicFile.WriteAllText(GetFilePath(), JsonConvert.SerializeObject(status));
            }
            catch
            {
            }
        }

        static string GetConnectorVersion()
        {
            return CONNECTOR_VERSION;
        }

        static string GetState()
        {
            if (EditorApplication.isCompiling) return "compiling";
            if (EditorApplication.isUpdating) return "refreshing";
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
