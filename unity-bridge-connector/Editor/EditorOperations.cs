using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json;
using UnityEditor;
using UnityEditor.Compilation;

namespace UnityBridgeConnector
{
    // Editor-thread receipts distinguish a completed operation from an older ready
    // snapshot. SessionState carries in-flight receipts across a domain reload.
    [InitializeOnLoad]
    internal static class EditorOperations
    {
        const string Key = "UnityBridge.OperationReceipts";
        sealed class Receipt
        {
            public string Id, Kind, Domain;
            public bool Finished, ExplicitCompile, Compiling, Compiled, CompileFailed, Reload, CodeImported, PlayEvent, Completed, Cancelled;
        }
        static readonly List<Receipt> Receipts;
        static string s_PendingState;

        static EditorOperations()
        {
            try { Receipts = JsonConvert.DeserializeObject<List<Receipt>>(SessionState.GetString(Key, "[]")) ?? new List<Receipt>(); }
            catch { Receipts = new List<Receipt>(); }
            UpdatePendingState();
            if (AssetDatabase.IsAssetImportWorkerProcess()) return;
            EditorApplication.update += Tick;
            CompilationPipeline.compilationStarted += _ =>
            {
                foreach (var item in ActiveImports())
                {
                    item.Compiling = true;
                    item.Compiled = item.CompileFailed = item.Reload = false;
                }
                Save();
            };
            CompilationPipeline.assemblyCompilationFinished += (_, messages) =>
            {
                foreach (var item in ActiveImports().Where(item => item.Compiling))
                    if (messages.Any(message => message.type == CompilerMessageType.Error)) item.CompileFailed = true;
                    else item.Reload = true;
                Save();
            };
            CompilationPipeline.compilationFinished += _ =>
            {
                foreach (var item in ActiveImports().Where(item => item.Compiling))
                {
                    item.Compiled = true;
                    if (item.CompileFailed || EditorUtility.scriptCompilationFailed) item.Reload = false;
                }
                Save();
            };
            AssemblyReloadEvents.afterAssemblyReload += () =>
            {
                // A no-change RequestScriptCompilation can reload the domain
                // without compilationStarted/Finished callbacks. The completed
                // reload itself is evidence; Tick still checks Unity is idle.
                foreach (var item in ActiveImports().Where(item => item.Domain != BridgeProtocol.DomainId))
                    item.Finished = item.Compiled = true;
                Save();
            };
            EditorApplication.playModeStateChanged += state =>
            {
                var cancelled = false;
                foreach (var item in Receipts.Where(item => !item.Completed))
                {
                    if ((item.Kind == "play" && state == PlayModeStateChange.EnteredPlayMode) ||
                        (item.Kind == "stop" && state == PlayModeStateChange.EnteredEditMode)) item.PlayEvent = true;
                    else if ((item.Kind == "play" && state == PlayModeStateChange.EnteredEditMode) ||
                             (item.Kind == "stop" && state == PlayModeStateChange.EnteredPlayMode))
                        item.Completed = item.Cancelled = cancelled = true;
                }
                Save();
                if (cancelled && PendingState == null) Heartbeat.PublishCompletedOperation();
            };
        }

        static IEnumerable<Receipt> ActiveImports() => Receipts.Where(item => !item.Completed &&
            (item.Kind == "refresh" || item.Kind == "reserialize"));

        internal static string Begin(string kind, bool explicitCompile = false)
        {
            while (Receipts.Count >= 64)
            {
                var completed = Receipts.FindIndex(item => item.Completed);
                if (completed < 0) throw new InvalidOperationException("Too many unfinished editor operations.");
                Receipts.RemoveAt(completed);
            }
            var receipt = new Receipt { Id = Guid.NewGuid().ToString("N"), Kind = kind,
                Domain = BridgeProtocol.DomainId, ExplicitCompile = explicitCompile };
            Receipts.Add(receipt);
            Save();
            return receipt.Id;
        }

        internal static string FinishSynchronous(string id)
        {
            var item = Receipts.Find(receipt => receipt.Id == id);
            if (item == null) return null;
            item.Finished = true;
            // Imported code can request a deferred reload without a compilation
            // callback (e.g. DLLs). Retain the existing conservative wait in that
            // case instead of manufacturing a completion receipt.
            if (item.CodeImported && !item.Compiling && !item.ExplicitCompile)
            {
                Abandon(id);
                return null;
            }
            Save();
            return id;
        }

        internal static void Abandon(string id)
        {
            Receipts.RemoveAll(item => item.Id == id && !item.Completed);
            Save();
        }

        internal static void CodeImported()
        {
            var active = ActiveImports().ToArray();
            if (active.Length == 0) return;
            foreach (var item in active)
            {
                item.CodeImported = true;
                // A late code import may schedule a reload without compilation.
                // Withdraw an already-returned receipt instead of confirming it
                // on the next idle frame. Its caller must not replay the action.
                if (item.Finished && !item.Compiling && !item.ExplicitCompile)
                    Receipts.Remove(item);
            }
            Save();
        }

        internal static object Snapshot(string id)
        {
            if (string.IsNullOrEmpty(id)) return null;
            var item = Receipts.Find(receipt => receipt.Id == id);
            return new { id, state = item == null ? "unknown" : item.Cancelled ? "cancelled" : item.Completed ? "completed" : "pending" };
        }

        internal static string PendingState => s_PendingState;

        static void UpdatePendingState()
        {
            var item = Receipts.FirstOrDefault(receipt => !receipt.Completed);
            s_PendingState = item == null ? null : item.Kind == "play" ? "entering_playmode" :
                item.Kind == "stop" ? "exiting_playmode" : item.ExplicitCompile || item.Compiling ? "compiling" : "refreshing";
        }

        static void Tick()
        {
            if (s_PendingState == null || EditorApplication.isCompiling || EditorApplication.isUpdating) return;
            var changed = false;
            foreach (var item in Receipts.Where(item => !item.Completed))
            {
                var newDomain = item.Domain != BridgeProtocol.DomainId;
                var isPlay = item.Kind == "play" || item.Kind == "stop";
                if (isPlay ? !item.PlayEvent : !item.Finished ||
                    (item.ExplicitCompile && !item.Compiled) ||
                    (item.Compiling && !item.Compiled) || (item.Reload && !newDomain)) continue;
                item.Completed = true;
                changed = true;
            }
            if (!changed) return;
            Save();
            if (PendingState == null) Heartbeat.PublishCompletedOperation();
        }

        static void Save()
        {
            UpdatePendingState();
            SessionState.SetString(Key, JsonConvert.SerializeObject(Receipts));
        }
    }

    internal sealed class OperationImportObserver : AssetPostprocessor
    {
        static void OnPostprocessAllAssets(string[] imported, string[] deleted, string[] moved, string[] movedFrom)
        {
            if (AssetDatabase.IsAssetImportWorkerProcess()) return;
            if (imported.Concat(deleted).Concat(moved).Concat(movedFrom).Any(path =>
                new[] { ".cs", ".asmdef", ".asmref", ".rsp", ".dll" }.Any(extension =>
                    path.EndsWith(extension, StringComparison.OrdinalIgnoreCase)))) EditorOperations.CodeImported();
        }
    }
}
