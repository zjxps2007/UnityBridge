using System.Collections.Immutable;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.Text;

namespace UnityBridge.Compiler;

// This process only parses/emits bytes. It must never load or execute user assemblies.
public sealed class CompilerEngine
{
    public const string CompilerVersion = "roslyn-5.0.0/wrapper-1";
    private static readonly string[] DefaultUsings =
    [
        "System", "System.Collections.Generic", "System.IO", "System.Linq", "System.Reflection",
        "System.Threading.Tasks", "UnityEngine", "UnityEngine.SceneManagement", "UnityEditor",
        "UnityEditor.SceneManagement", "UnityEditorInternal",
    ];
    private readonly BoundedCache<ReferenceEntry> references = new(512, 256L * 1024 * 1024);
    // Weight includes references (conservatively counting shared images more than once).
    private readonly BoundedCache<CompilationEntry> compilations = new(64, 256L * 1024 * 1024);

    public CompileResponse Process(CompileRequest request)
    {
        try
        {
            if (request.Protocol != 1)
                return Fail(request, "unsupported_protocol", "Compiler protocol 1 is required.");
            if (request.Operation == "ping")
                return new CompileResponse { RequestId = request.RequestId, Success = true };
            if (request.Operation != "compile")
                return Fail(request, "invalid_request", "Unknown compiler operation.");
            if (string.IsNullOrEmpty(request.Code) || request.Code.Length > 1024 * 1024)
                return Fail(request, "invalid_request", "Code must contain between 1 and 1048576 characters.");
            if (request.Usings is null || request.Usings.Length > 256 || request.Usings.Any(value => value is null))
                return Fail(request, "invalid_request", "Invalid using directives.");
            if (request.References is null || request.References.Length is 0 or > 4096)
                return Fail(request, "invalid_request", "Supply between 1 and 4096 Unity metadata references.");
            if (string.IsNullOrEmpty(request.LanguageVersion)
                || !LanguageVersionFacts.TryParse(request.LanguageVersion, out var languageVersion)
                || languageVersion is LanguageVersion.Default or LanguageVersion.Latest or LanguageVersion.LatestMajor or LanguageVersion.Preview)
                return Fail(request, "unsupported_language_version", "Supply an explicit language version supported by the Unity project.");

            return Compile(request, languageVersion);
        }
        catch (StaleReferenceException ex)
        {
            return Fail(request, "stale_reference", ex.Message);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or BadImageFormatException)
        {
            return Fail(request, "stale_reference", "Unity metadata references are unavailable: " + ex.Message);
        }
        catch (Exception ex)
        {
            // A malformed request must not corrupt the stream or stop the persistent worker.
            return Fail(request, "compiler_error", ex.GetType().Name + ": " + ex.Message);
        }
    }

    private CompileResponse Compile(CompileRequest request, LanguageVersion languageVersion)
    {
        var source = BuildSource(request.Code!, request.Usings);
        var referenceEntries = new List<ReferenceEntry>(request.References.Length);
        var identities = new List<string>(request.References.Length);
        foreach (var reference in request.References)
        {
            if (reference is null || string.IsNullOrEmpty(reference.Path)
                || !Guid.TryParse(reference.Mvid, out var expectedMvid))
                return Fail(request, "invalid_request", "Each Unity reference requires a path and valid MVID.");
            if (!Path.IsPathFullyQualified(reference.Path))
                return Fail(request, "invalid_request", "Unity reference paths must be absolute.");
            var path = Path.GetFullPath(reference.Path);
            var key = (OperatingSystem.IsWindows() ? path.ToUpperInvariant() : path) + "|" + expectedMvid.ToString("N");
            // Always read the actual MVID, including cache hits: timestamps can be preserved by a rebuild.
            using (var stream = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (var pe = new PEReader(stream))
            {
                if (!pe.HasMetadata || ReadMvid(pe) != expectedMvid)
                    throw new StaleReferenceException("Unity reference changed: " + path);
            }
            if (!references.TryGet(key, out var entry))
            {
                var bytes = File.ReadAllBytes(path);
                using (var pe = new PEReader(ImmutableArray.Create(bytes)))
                {
                    if (!pe.HasMetadata || ReadMvid(pe) != expectedMvid)
                        throw new StaleReferenceException("Unity reference changed while reading: " + path);
                }
                entry = new ReferenceEntry(MetadataReference.CreateFromImage(ImmutableArray.Create(bytes), filePath: path), bytes.LongLength);
                references.Add(key, entry, entry.Weight);
            }
            referenceEntries.Add(entry);
            identities.Add(key);
        }

        var keyBytes = Encoding.UTF8.GetBytes(string.Join("\0", new[]
        {
            CompilerVersion, request.ProjectId ?? "", source, ((int)languageVersion).ToString(System.Globalization.CultureInfo.InvariantCulture),
            "library;debug;unsafe=false;nullable=disable;nowarn=0105,1701,1702", string.Join("\0", identities),
        }));
        var compilationKey = Convert.ToHexString(SHA256.HashData(keyBytes));
        var cacheHit = compilations.TryGet(compilationKey, out var cached);
        if (!cacheHit)
        {
            var tree = CSharpSyntaxTree.ParseText(SourceText.From(source, Encoding.UTF8), new CSharpParseOptions(languageVersion), path: "snippet.cs");
            var options = new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary,
                optimizationLevel: OptimizationLevel.Debug, allowUnsafe: false,
                nullableContextOptions: NullableContextOptions.Disable,
                assemblyIdentityComparer: DesktopAssemblyIdentityComparer.Default,
                specificDiagnosticOptions: new Dictionary<string, ReportDiagnostic>
                {
                    ["CS0105"] = ReportDiagnostic.Suppress,
                    ["CS1701"] = ReportDiagnostic.Suppress,
                    ["CS1702"] = ReportDiagnostic.Suppress,
                });
            var compilation = CSharpCompilation.Create(NewAssemblyName(), [tree], referenceEntries.Select(entry => entry.Reference), options);
            cached = new CompilationEntry(compilation, referenceEntries.Sum(entry => entry.Weight) + source.Length * 2L);
            compilations.Add(compilationKey, cached, cached.Weight);
        }

        if (!request.FreshIdentity && cached!.EmittedBytes is not null)
            return Succeed(request, cached.Compilation.AssemblyName!, cached.EmittedBytes, cached.Diagnostics, cacheHit, true);

        var target = request.FreshIdentity ? cached!.Compilation.WithAssemblyName(NewAssemblyName()) : cached!.Compilation;
        using var output = new MemoryStream();
        var result = target.Emit(output);
        var diagnostics = result.Diagnostics.Where(diagnostic => !diagnostic.IsSuppressed)
            .Select(FormatDiagnostic).ToArray();
        if (!result.Success)
        {
            var messages = diagnostics.Where(diagnostic => diagnostic.Severity == "error")
                .Select(diagnostic => diagnostic.Line is { } line ? $"L{line}: {diagnostic.Message}" : diagnostic.Message);
            return Fail(request, "compile_error", "Compile error:\n" + string.Join("\n", messages), diagnostics);
        }

        var image = output.ToArray();
        if (!request.FreshIdentity)
        {
            cached.EmittedBytes = image;
            cached.Diagnostics = diagnostics;
            compilations.Add(compilationKey, cached, cached.Weight + image.LongLength);
        }
        return Succeed(request, target.AssemblyName!, image, diagnostics, cacheHit, false);
    }

    public static string BuildSource(string code, IEnumerable<string> extraUsings)
    {
        var builder = new StringBuilder();
        foreach (var value in DefaultUsings.Concat(extraUsings))
            builder.Append("using ").Append(value).Append(";\n");
        return builder.Append("\npublic static class __CliDynamic {\n  public static object Execute() {\n")
            .Append(code).Append("\n  }\n}\n").ToString();
    }

    private static Guid ReadMvid(PEReader pe)
    {
        var metadata = pe.GetMetadataReader();
        return metadata.GetGuid(metadata.GetModuleDefinition().Mvid);
    }

    private static string NewAssemblyName() => "UnityBridgeExec_" + Guid.NewGuid().ToString("N");

    private static CompilerDiagnostic FormatDiagnostic(Diagnostic diagnostic)
    {
        var span = diagnostic.Location.IsInSource ? diagnostic.Location.GetLineSpan().StartLinePosition : (LinePosition?)null;
        return new CompilerDiagnostic(diagnostic.Id, diagnostic.Severity.ToString().ToLowerInvariant(),
            diagnostic.GetMessage(System.Globalization.CultureInfo.InvariantCulture), span?.Line + 1, span?.Character + 1);
    }

    private static CompileResponse Succeed(CompileRequest request, string name, byte[] bytes, CompilerDiagnostic[] diagnostics, bool cacheHit, bool emitReused)
        => new()
        {
            RequestId = request.RequestId, Success = true, AssemblyName = name,
            AssemblyBase64 = Convert.ToBase64String(bytes), ReferenceGeneration = request.ReferenceGeneration,
            CacheHit = cacheHit, EmitReused = emitReused, Diagnostics = diagnostics,
        };

    private static CompileResponse Fail(CompileRequest request, string code, string error, CompilerDiagnostic[]? diagnostics = null)
        => new()
        {
            RequestId = request.RequestId, Success = false, ErrorCode = code, Error = error,
            ReferenceGeneration = request.ReferenceGeneration, Diagnostics = diagnostics ?? [],
        };

    private sealed record ReferenceEntry(PortableExecutableReference Reference, long Weight);

    private sealed class CompilationEntry(CSharpCompilation compilation, long weight)
    {
        public CSharpCompilation Compilation { get; } = compilation;
        public long Weight { get; } = weight;
        public byte[]? EmittedBytes { get; set; }
        public CompilerDiagnostic[] Diagnostics { get; set; } = [];
    }

    private sealed class StaleReferenceException(string message) : Exception(message);
}

internal sealed class BoundedCache<T>(int capacity, long maxBytes) where T : class
{
    private readonly Dictionary<string, LinkedListNode<(string Key, T Value, long Weight)>> entries = new(StringComparer.Ordinal);
    private readonly LinkedList<(string Key, T Value, long Weight)> lru = new();
    private long bytes;

    public bool TryGet(string key, out T value)
    {
        if (entries.TryGetValue(key, out var node))
        {
            lru.Remove(node);
            lru.AddLast(node);
            value = node.Value.Value;
            return true;
        }
        value = null!;
        return false;
    }

    public void Add(string key, T value, long weight)
    {
        if (entries.Remove(key, out var existing))
        {
            bytes -= existing.Value.Weight;
            lru.Remove(existing);
        }
        if (weight > maxBytes) return;
        while (entries.Count >= capacity || bytes + weight > maxBytes)
        {
            var oldest = lru.First!;
            bytes -= oldest.Value.Weight;
            entries.Remove(oldest.Value.Key);
            lru.RemoveFirst();
        }
        entries[key] = lru.AddLast((key, value, weight));
        bytes += weight;
    }
}
