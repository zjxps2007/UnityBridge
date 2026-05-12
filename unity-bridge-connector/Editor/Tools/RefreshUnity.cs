using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.Compilation;
using UnityEngine;

namespace UnityBridgeConnector.Tools
{
    [UnityBridgeTool(Description = "Refresh Unity assets and optionally request script compilation.")]
    public static class RefreshUnity
    {
        public class Parameters
        {
            [ToolParameter("Refresh mode: if_dirty (default) or force")]
            public string Mode { get; set; }

            [ToolParameter("Allow refresh while the editor is in or entering play mode.")]
            public bool Force { get; set; }

            [ToolParameter("Single asset path to import. Accepts Assets/..., Packages/..., or an absolute project path.")]
            public string Path { get; set; }

            [ToolParameter("Asset paths to import. Accepts Assets/..., Packages/..., or absolute project paths.")]
            public string[] Paths { get; set; }

            [ToolParameter("Compile mode: none (default) or request")]
            public string Compile { get; set; }
        }

        public static object HandleCommand(JObject @params)
        {
            var p = new ToolParams(@params ?? new JObject());
            string mode = p.Get("mode", "if_dirty");
            string compile = p.Get("compile", "none");
            bool force = p.GetBool("force");
            var pathsResult = GetRequestedPaths(p);
            if (!pathsResult.IsSuccess)
                return new ErrorResponse(pathsResult.ErrorMessage);
            var requestedPaths = pathsResult.Value;
            var explicitCompileRequested = string.Equals(compile, "request", StringComparison.OrdinalIgnoreCase);

            bool compileRequested = false;

            if (!force && EditorApplication.isPlayingOrWillChangePlaymode)
            {
                return new ErrorResponse("Cannot refresh while Unity is in or entering play mode. Exit play mode first, or pass --force if this is intentional.");
            }

            var options = string.Equals(mode, "force", StringComparison.OrdinalIgnoreCase)
                ? ImportAssetOptions.ForceUpdate | ImportAssetOptions.ForceSynchronousImport
                : ImportAssetOptions.ForceSynchronousImport;

            var importedPaths = new List<string>();
            if (requestedPaths.Count > 0)
            {
                var seenComparer = Application.platform == RuntimePlatform.WindowsEditor
                    ? StringComparer.OrdinalIgnoreCase
                    : StringComparer.Ordinal;
                var seen = new HashSet<string>(seenComparer);
                foreach (var path in requestedPaths)
                {
                    var normalized = NormalizeAssetPath(path);
                    if (!normalized.IsSuccess)
                        return new ErrorResponse(normalized.ErrorMessage, new { path });

                    var assetPath = normalized.Value;
                    if (!seen.Add(assetPath))
                        continue;

                    importedPaths.Add(assetPath);
                }
            }

            var compilePending = explicitCompileRequested || ContainsScriptCompilationPath(importedPaths);
            if (compilePending)
                Heartbeat.MarkCompileRequested();
            else
                Heartbeat.MarkRefreshRequested();

            if (importedPaths.Count == 0)
            {
                AssetDatabase.Refresh(options);
            }
            else
            {
                foreach (var assetPath in importedPaths)
                {
                    var importOptions = AssetDatabase.IsValidFolder(assetPath)
                        ? options | ImportAssetOptions.ImportRecursive
                        : options;
                    AssetDatabase.ImportAsset(assetPath, importOptions);
                }
            }

            if (explicitCompileRequested)
            {
                CompilationPipeline.RequestScriptCompilation();
                compileRequested = true;
            }

            return new SuccessResponse("Refresh requested.", new
            {
                refresh_triggered = true,
                scope = importedPaths.Count == 0 ? "all" : "paths",
                paths = importedPaths,
                mode = mode,
                compile_requested = compileRequested,
                compile_pending = compilePending,
                force = force,
            });
        }

        static Result<List<string>> GetRequestedPaths(ToolParams p)
        {
            var paths = new List<string>();
            var singlePath = p.Get("path");
            if (!string.IsNullOrWhiteSpace(singlePath))
                paths.Add(singlePath);

            var rawPaths = p.GetRaw("paths");
            if (rawPaths != null)
            {
                if (rawPaths.Type == JTokenType.Array)
                {
                    foreach (var token in (JArray)rawPaths)
                    {
                        var value = token?.ToString();
                        if (!string.IsNullOrWhiteSpace(value))
                            paths.Add(value);
                    }
                }
                else if (rawPaths.Type == JTokenType.String)
                {
                    var value = rawPaths.ToString();
                    if (!string.IsNullOrWhiteSpace(value))
                        paths.Add(value);
                }
                else
                {
                    return Result<List<string>>.Error("'paths' must be a string or an array of strings.");
                }
            }

            var legacyScope = p.Get("scope");
            if (!string.IsNullOrWhiteSpace(legacyScope) &&
                !legacyScope.Equals("all", StringComparison.OrdinalIgnoreCase))
            {
                return Result<List<string>>.Error("'scope' is not supported for partial refresh. Use 'path' or 'paths' instead.");
            }

            return Result<List<string>>.Success(paths);
        }

        static Result<string> NormalizeAssetPath(string input)
        {
            if (string.IsNullOrWhiteSpace(input))
                return Result<string>.Error("Asset path cannot be empty.");

            var trimmed = input.Trim().Trim('"').Trim('\'');
            var slashPath = trimmed.Replace('\\', '/');
            while (slashPath.StartsWith("./", StringComparison.Ordinal))
                slashPath = slashPath.Substring(2);
            slashPath = slashPath.TrimEnd('/');

            if (IsUnityAssetPath(slashPath))
                return Result<string>.Success(slashPath);

            if (slashPath == ".." || slashPath.StartsWith("../", StringComparison.Ordinal) || slashPath.Contains("/../"))
                return Result<string>.Error($"Path is outside the Unity project: {input}");

            try
            {
                if (!Path.IsPathRooted(trimmed))
                    return Result<string>.Error($"Path must be Assets/..., Packages/..., or an absolute path inside the Unity project: {input}");

                var projectRoot = Path.GetFullPath(Path.GetDirectoryName(Application.dataPath) ?? Application.dataPath);
                var fullPath = Path.GetFullPath(trimmed);
                var comparison = Application.platform == RuntimePlatform.WindowsEditor
                    ? StringComparison.OrdinalIgnoreCase
                    : StringComparison.Ordinal;

                if (!IsSameOrChild(fullPath, projectRoot, comparison))
                    return Result<string>.Error($"Path is outside the Unity project: {input}");

                var relative = fullPath.Substring(projectRoot.Length)
                    .TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                    .Replace('\\', '/')
                    .TrimEnd('/');

                if (!IsUnityAssetPath(relative))
                    return Result<string>.Error($"Path must resolve under Assets or Packages: {input}");

                return Result<string>.Success(relative);
            }
            catch (Exception ex)
            {
                return Result<string>.Error($"Invalid asset path '{input}': {ex.Message}");
            }
        }

        static bool IsUnityAssetPath(string path)
        {
            return path == "Assets" ||
                   path.StartsWith("Assets/", StringComparison.Ordinal) ||
                   path == "Packages" ||
                   path.StartsWith("Packages/", StringComparison.Ordinal);
        }

        static bool IsSameOrChild(string path, string parent, StringComparison comparison)
        {
            var normalizedParent = parent.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            return path.Equals(normalizedParent, comparison) ||
                   path.StartsWith(normalizedParent + Path.DirectorySeparatorChar, comparison) ||
                   path.StartsWith(normalizedParent + Path.AltDirectorySeparatorChar, comparison);
        }

        static bool ContainsScriptCompilationPath(List<string> assetPaths)
        {
            foreach (var path in assetPaths)
            {
                if (MayTriggerScriptCompilation(path))
                    return true;
            }
            return false;
        }

        static bool MayTriggerScriptCompilation(string assetPath)
        {
            return AssetDatabase.IsValidFolder(assetPath) ||
                   assetPath.EndsWith(".cs", StringComparison.OrdinalIgnoreCase) ||
                   assetPath.EndsWith(".asmdef", StringComparison.OrdinalIgnoreCase) ||
                   assetPath.EndsWith(".asmref", StringComparison.OrdinalIgnoreCase) ||
                   assetPath.EndsWith(".rsp", StringComparison.OrdinalIgnoreCase) ||
                   assetPath.EndsWith(".dll", StringComparison.OrdinalIgnoreCase);
        }
    }
}
