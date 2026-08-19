using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;

namespace UnityBridgeConnector
{
    /// <summary>
    /// Finds [UnityBridgeTool] handlers via a lazily built domain cache.
    /// The cache is invalidated when a new assembly is loaded so tools added
    /// at runtime are still discovered without rescanning on every command.
    /// </summary>
    public static class ToolDiscovery
    {
        sealed class DiscoveryCache
        {
            public readonly Dictionary<string, MethodInfo> Handlers;
            public readonly List<object> Schemas;

            public DiscoveryCache(Dictionary<string, MethodInfo> handlers, List<object> schemas)
            {
                Handlers = handlers;
                Schemas = schemas;
            }
        }

        static readonly object s_CacheLock = new object();
        static volatile DiscoveryCache s_Cache;
        static int s_AssemblyGeneration;

        static ToolDiscovery()
        {
            AppDomain.CurrentDomain.AssemblyLoad += OnAssemblyLoad;
        }

        public static MethodInfo FindHandler(string command)
        {
            if (command == null) return null;
            var handlers = GetCache().Handlers;
            return handlers.TryGetValue(command, out var handler) ? handler : null;
        }

        public static List<object> GetToolSchemas()
        {
            // Preserve the previous API contract: callers receive their own list.
            return new List<object>(GetCache().Schemas);
        }

        static void OnAssemblyLoad(object sender, AssemblyLoadEventArgs args)
        {
            lock (s_CacheLock)
            {
                s_AssemblyGeneration++;
                s_Cache = null;
            }
        }

        static DiscoveryCache GetCache()
        {
            var cache = s_Cache;
            if (cache != null) return cache;

            lock (s_CacheLock)
            {
                cache = s_Cache;
                while (cache == null)
                {
                    var generation = s_AssemblyGeneration;
                    cache = BuildCache();

                    // Reflection can lazily load another assembly while the cache
                    // is being built. Rebuild once more so that assembly is included.
                    if (generation != s_AssemblyGeneration)
                    {
                        cache = null;
                        continue;
                    }

                    s_Cache = cache;
                }
            }

            return cache;
        }

        static DiscoveryCache BuildCache()
        {
            var handlers = new Dictionary<string, MethodInfo>(StringComparer.Ordinal);
            var tools = new List<object>();
            var nameToType = new Dictionary<string, Type>(StringComparer.Ordinal);

            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                Type[] types;
                try { types = assembly.GetTypes(); }
                catch (ReflectionTypeLoadException) { continue; }

                foreach (var type in types)
                {
                    if (type.IsClass == false) continue;
                    var attr = type.GetCustomAttribute<UnityBridgeToolAttribute>();
                    if (attr == null) continue;

                    var name = attr.Name ?? StringCaseUtility.ToSnakeCase(type.Name);

                    if (nameToType.TryGetValue(name, out var existing))
                    {
                        UnityEngine.Debug.LogError(
                            $"[UnityBridge] Duplicate tool name '{name}': " +
                            $"{existing.FullName} and {type.FullName}. " +
                            $"Rename one or remove the duplicate.");
                    }
                    else
                    {
                        nameToType[name] = type;
                        var paramsType = type.GetNestedType("Parameters");

                        tools.Add(new
                        {
                            name,
                            description = attr.Description ?? "",
                            group = attr.Group ?? "",
                            parameters = GetParameterSchema(paramsType),
                        });
                    }

                    var method = type.GetMethod("HandleCommand",
                        BindingFlags.Public | BindingFlags.Static, null,
                        new[] { typeof(JObject) }, null);

                    // Match the old lookup behavior: the first valid handler wins,
                    // even if an earlier attributed type had no HandleCommand method.
                    if (method != null && !handlers.ContainsKey(name))
                        handlers[name] = method;
                }
            }

            return new DiscoveryCache(handlers, tools);
        }

        public static List<object> GetParameterSchema(Type paramsType)
        {
            if (paramsType == null) return new List<object>();

            return paramsType.GetProperties()
                .Select(p =>
                {
                    var attr = p.GetCustomAttribute<ToolParameterAttribute>();
                    return new
                    {
                        name = StringCaseUtility.ToSnakeCase(p.Name),
                        type = p.PropertyType.Name,
                        description = attr?.Description ?? "",
                        required = attr?.Required ?? false,
                    };
                })
                .Cast<object>()
                .ToList();
        }
    }
}
