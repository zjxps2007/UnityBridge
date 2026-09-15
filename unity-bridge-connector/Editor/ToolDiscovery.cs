using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using UnityEditor;

namespace UnityBridgeConnector
{
    /// <summary>
    /// Finds [UnityBridgeTool] handlers via a lazily built domain cache.
    /// The cache is invalidated when a new assembly is loaded so tools added
    /// at runtime are still discovered without rescanning on every command.
    /// </summary>
    [InitializeOnLoad]
    public static class ToolDiscovery
    {
        sealed class ToolEntry
        {
            public Type Type;
            public string Name;
            public UnityBridgeToolAttribute Attribute;
        }

        sealed class DiscoveryCache
        {
            public readonly Dictionary<string, MethodInfo> Handlers;
            public readonly List<ToolEntry> Tools;
            public List<object> Schemas;

            public DiscoveryCache(Dictionary<string, MethodInfo> handlers, List<ToolEntry> tools)
            {
                Handlers = handlers;
                Tools = tools;
            }
        }

        static readonly object s_CacheLock = new object();
        static volatile DiscoveryCache s_Cache;
        static int s_AssemblyGeneration;
        static readonly HashSet<Assembly> s_LoadedAssemblies = new HashSet<Assembly>();

        static ToolDiscovery()
        {
            // Subscribe during domain initialization, before the first CLI request.
            // TypeCache covers Unity's indexed assemblies; later Assembly.Load calls
            // also need reflection because they need not be in that native index.
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
            lock (s_CacheLock)
            {
                while (true)
                {
                    var cache = GetCache();
                    if (cache.Schemas == null)
                    {
                        var generation = s_AssemblyGeneration;
                        var schemas = cache.Tools.Select(tool => (object)new
                        {
                            name = tool.Name,
                            description = tool.Attribute.Description ?? "",
                            group = tool.Attribute.Group ?? "",
                            parameters = GetParameterSchema(tool.Type.GetNestedType("Parameters")),
                        }).ToList();
                        if (generation != s_AssemblyGeneration) continue;
                        cache.Schemas = schemas;
                    }
                    // Callers may change the list without changing the cached list.
                    return new List<object>(cache.Schemas);
                }
            }
        }

        static void OnAssemblyLoad(object sender, AssemblyLoadEventArgs args)
        {
            lock (s_CacheLock)
            {
                s_LoadedAssemblies.Add(args.LoadedAssembly);
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
            var tools = new List<ToolEntry>();
            var nameToType = new Dictionary<string, Type>(StringComparer.Ordinal);

            foreach (var type in GetToolTypes())
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
                    tools.Add(new ToolEntry
                    {
                        Type = type,
                        Name = name,
                        Attribute = attr,
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

            return new DiscoveryCache(handlers, tools);
        }

        static IEnumerable<Type> GetToolTypes()
        {
            var assemblies = AppDomain.CurrentDomain.GetAssemblies();
            var types = new HashSet<Type>(TypeCache.GetTypesWithAttribute<UnityBridgeToolAttribute>());
            // Match GetCustomAttribute's inherited-attribute behavior as well.
            foreach (var type in types.ToArray())
                if (!type.IsSealed)
                    types.UnionWith(TypeCache.GetTypesDerivedFrom(type));

            var extra = new HashSet<Assembly>(s_LoadedAssemblies);
            foreach (var assembly in assemblies)
                if (assembly.IsDynamic || string.IsNullOrEmpty(assembly.Location))
                    extra.Add(assembly);
            foreach (var assembly in extra)
            {
                Type[] loadedTypes;
                try { loadedTypes = assembly.GetTypes(); }
                catch (ReflectionTypeLoadException) { continue; }
                foreach (var type in loadedTypes)
                    if (type.IsClass && type.IsDefined(typeof(UnityBridgeToolAttribute), true))
                        types.Add(type);
            }

            // TypeCache's result is unordered. Preserve domain assembly order and
            // metadata declaration order, including first-valid duplicate handlers.
            return types.OrderBy(type => Array.IndexOf(assemblies, type.Assembly))
                .ThenBy(type => type.MetadataToken);
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
