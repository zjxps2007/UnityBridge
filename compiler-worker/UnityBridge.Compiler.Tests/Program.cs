using System.Buffers.Binary;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using UnityBridge.Compiler;

var temporary = Path.Combine(Path.GetTempPath(), "unity-bridge-compiler-tests-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(temporary);
try
{
    var platformAssemblies = ((string?)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") ?? "").Split(Path.PathSeparator);
    var framework = platformAssemblies.Where(path => new[]
    {
        "System.Private.CoreLib", "System.Runtime", "System.Linq", "System.Collections", "System.Console",
        "System.Reflection", "System.IO", "System.Threading.Tasks",
    }.Contains(Path.GetFileNameWithoutExtension(path), StringComparer.Ordinal)).Distinct().ToArray();
    Check(framework.Length >= 3, "Test runtime provides framework references.");
    var fixturePath = Path.Combine(temporary, "UnityFixture.dll");
    WriteFixture(fixturePath, framework, 17);
    var references = framework.Append(fixturePath).Select(Identity).ToArray();
    var engine = new CompilerEngine();
    var passed = 0;

    Test("Shared metadata is charged once and released after its last cache owner", () =>
    {
        var cache = new BoundedCache<object>(4, 100);
        var x = new[] { new KeyValuePair<string, long>("image-x", 80) };
        cache.Add("a", new object(), 5, x);
        cache.Add("b", new object(), 5, x);
        Check(cache.TryGet("a", out _) && cache.TryGet("b", out _), "Shared images must not evict each other.");
        cache.Add("c", new object(), 30, [new KeyValuePair<string, long>("image-y", 60)]);
        Check(!cache.TryGet("a", out _) && !cache.TryGet("b", out _) && cache.TryGet("c", out _), "Unique images remain bounded.");
        cache.Add("d", new object(), 10);
        cache.Add("e", new object(), 11);
        Check(!cache.TryGet("c", out _) && cache.TryGet("d", out _) && cache.TryGet("e", out _), "Evicting the last image owner releases its accounting.");
        cache.Add("e", new object(), 5, x);
        Check(cache.TryGet("d", out _) && cache.TryGet("e", out _), "Replacement updates shared retention.");
        cache.Add("oversized", new object(), 21, x);
        Check(!cache.TryGet("oversized", out _), "An oversized entry is never cached.");
    });

    Test("Ping and protocol negotiation", () =>
    {
        var ping = engine.Process(new CompileRequest { Protocol = 1, Operation = "ping", RequestId = "ping-1" });
        Check(ping.Success && ping.RequestId == "ping-1" && ping.CompilerVersion.StartsWith("roslyn-5.0.0/"), "Ping correlation/version.");
        Check(engine.Process(new CompileRequest { Protocol = 2, Operation = "ping" }).ErrorCode == "unsupported_protocol", "Reject incompatible protocols.");
    });

    Test("Reloaded metadata images are not undercounted as shared allocations", () =>
    {
        var metadata = new MetadataReferenceCache(capacity: 1);
        var identity = Identity(fixturePath);
        var old = metadata.Get(identity.Path, Guid.Parse(identity.Mvid));
        Check(ReferenceEquals(old, metadata.Get(identity.Path, Guid.Parse(identity.Mvid))), "A retained image is shared.");
        var other = Identity(framework[0]);
        metadata.Get(other.Path, Guid.Parse(other.Mvid));
        var reloaded = metadata.Get(identity.Path, Guid.Parse(identity.Mvid));
        Check(old.Identity == reloaded.Identity && old.RetentionId != reloaded.RetentionId, "Reloaded bytes have separate retention identities.");
        var cache = new BoundedCache<object>(4, old.Weight + 20);
        cache.Add("old", old, 5, [new KeyValuePair<string, long>(old.RetentionId, old.Weight)]);
        cache.Add("new", reloaded, 5, [new KeyValuePair<string, long>(reloaded.RetentionId, reloaded.Weight)]);
        Check(!cache.TryGet("old", out _) && cache.TryGet("new", out _), "Duplicated live images are charged separately.");
    });

    Test("Compile explicit Unity references and unicode source", () =>
    {
        var result = engine.Process(Request("return new UnityEngine.Object();"));
        Check(result.Success && result.AssemblyBase64 is not null, result.Error ?? "DLL expected.");
        Check(ReadAssemblyName(Convert.FromBase64String(result.AssemblyBase64!)) == result.AssemblyName, "Emitted identity is accurate.");
        Check(result.ReferenceGeneration == "generation-1" && result.RequestId == "request-1", "Request metadata preserved.");
        Check(engine.Process(Request("return \"한글🧪\";")).Success, "Unicode source is compiled.");
    });

    Test("Framework warmup never leaks implicit references or an executable result", () =>
    {
        var warmEngine = new CompilerEngine();
        var warm = warmEngine.Process(new CompileRequest { Protocol = 1, Operation = "warmup", RequestId = "warm" });
        Check(warm.Success && warm.AssemblyBase64 is null && warm.AssemblyName is null, "Warmup produces no loadable result.");
        Check(warmEngine.Process(new CompileRequest { Protocol = 1, Operation = "warmup" }).Success, "Warmup is idempotent.");
        Check(!warmEngine.Process(Request("return 42;", providedReferences: [Identity(fixturePath)])).Success, "Runtime references never become implicit Unity references.");
        Check(warmEngine.Process(Request("return new UnityEngine.Object();")).Success, "Actual project references still compile after warmup.");
    });

    Test("Different snippets reuse only a compatible base compilation", () =>
    {
        var baseEngine = new CompilerEngine(reuseBaseCompilation: true);
        var first = baseEngine.Process(Request("return 7101;"));
        var second = baseEngine.Process(Request("return 7102;"));
        Check(first.Success && second.Success && !first.BaseCacheHit && second.BaseCacheHit && !second.CacheHit, "New source reuses its reference context.");
        Check(first.AssemblyName != second.AssemblyName && first.AssemblyBase64 != second.AssemblyBase64, "Base sharing never reuses a result or assembly identity.");
        Check(!baseEngine.Process(Request("return 7103;", language: "8.0")).BaseCacheHit, "Language configuration is isolated.");
        var missing = baseEngine.Process(Request("return 7104;", providedReferences: [Identity(fixturePath)]));
        Check(!missing.Success && missing.ErrorCode == "compile_error", "A base cannot supply missing references.");
    });

    Test("Base compilation remains opt in after its latency experiment", () =>
    {
        var defaultEngine = new CompilerEngine();
        var first = defaultEngine.Process(Request("return 8101;"));
        var second = defaultEngine.Process(Request("return 8102;"));
        Check(first.Success && second.Success && !first.BaseCacheHit && !second.BaseCacheHit,
            "The default path does not retain an unproven base compilation.");
    });

    Test("Cached emission is byte identical only when explicitly requested", () =>
    {
        var first = engine.Process(Request("return 7123;", freshIdentity: false));
        var second = engine.Process(Request("return 7123;", freshIdentity: false));
        Check(first.Success && second.Success, first.Error ?? second.Error ?? "Expected successful compilation.");
        Check(!first.EmitReused && second.CacheHit && second.EmitReused, "Second request reuses emitted bytes.");
        Check(first.AssemblyBase64 == second.AssemblyBase64 && first.AssemblyName == second.AssemblyName, "Cached DLL remains identical.");
    });

    Test("Default fresh identity keeps independent types across repeated calls", () =>
    {
        var first = engine.Process(Request("return typeof(__CliDynamic).Assembly.FullName;"));
        var second = engine.Process(Request("return typeof(__CliDynamic).Assembly.FullName;"));
        Check(first.Success && second.Success && second.CacheHit, "Compilation is reusable.");
        Check(!second.EmitReused && first.AssemblyName != second.AssemblyName && first.AssemblyBase64 != second.AssemblyBase64,
            "Every fresh request emits a distinct identity.");
    });

    Test("Syntax diagnostics and worker reuse after failure", () =>
    {
        var invalid = engine.Process(Request("return ; int broken = ;"));
        Check(!invalid.Success && invalid.ErrorCode == "compile_error" && invalid.Diagnostics.Any(item => item.Severity == "error" && item.Line > 0), "Structured compiler diagnostic.");
        Check(engine.Process(Request("return 91;")).Success, "Error does not poison worker state.");
    });

    Test("No implicit .NET framework or Unity references", () =>
    {
        var result = engine.Process(Request("return 42;", providedReferences: [Identity(fixturePath)]));
        Check(!result.Success && result.ErrorCode == "compile_error", "Missing framework references are not silently added.");
    });

    Test("Explicit language version is honored", () =>
    {
        Check(engine.Process(Request("return 4;", language: "latest")).ErrorCode == "unsupported_language_version", "latest is not a Unity compatibility contract.");
        var oldLanguage = engine.Process(Request("System.Collections.Generic.List<int> values = new(); return values.Count;", language: "8.0"));
        Check(!oldLanguage.Success && oldLanguage.ErrorCode == "compile_error", "C# 9 syntax rejected for C# 8.");
        Check(engine.Process(Request("System.Collections.Generic.List<int> values = new(); return values.Count;", language: "9.0")).Success, "C# 9 syntax accepted for C# 9.");
    });

    Test("Reference replacement invalidates even already compiled code", () =>
    {
        var before = engine.Process(Request("return Fixture.Value;", freshIdentity: false));
        Check(before.Success, before.Error ?? "Initial fixture compile.");
        var timestamp = File.GetLastWriteTimeUtc(fixturePath);
        WriteFixture(fixturePath, framework, 18);
        File.SetLastWriteTimeUtc(fixturePath, timestamp);
        var stale = engine.Process(Request("return Fixture.Value;", freshIdentity: false));
        Check(stale.ErrorCode == "stale_reference", "Actual MVID checked despite preserved timestamp and compilation cache hit.");
        references = framework.Append(fixturePath).Select(Identity).ToArray();
        var updated = engine.Process(Request("return Fixture.Value;", freshIdentity: false));
        Check(updated.Success && !updated.CacheHit && before.AssemblyBase64 != updated.AssemblyBase64, "New reference identity recompiles.");
    });

    Test("Invalid reference identity is rejected", () =>
    {
        Check(engine.Process(Request("return 1;", providedReferences: [new ReferenceIdentity(fixturePath, "bad")])).ErrorCode == "invalid_request", "Malformed MVID rejected.");
        Check(engine.Process(Request("return 1;", providedReferences: [new ReferenceIdentity("relative.dll", Guid.NewGuid().ToString())])).ErrorCode == "invalid_request", "Relative path rejected.");
        Check(engine.Process(Request("return 1;", providedReferences: [new ReferenceIdentity(Path.Combine(temporary, "missing.dll"), Guid.NewGuid().ToString())])).ErrorCode == "stale_reference", "Deleted references require refresh.");
    });

    Test("Uncached references reject a stale identity before emission", () =>
    {
        var staleReferences = references.Select(reference => reference.Path == fixturePath
            ? new ReferenceIdentity(reference.Path, Guid.NewGuid().ToString()) : reference).ToArray();
        var result = new CompilerEngine().Process(Request("return Fixture.Value;", providedReferences: staleReferences));
        Check(result.ErrorCode == "stale_reference" && result.AssemblyBase64 is null, "Cold reference load validates the image sent to Roslyn.");
        Check(result.Error == "Unity reference changed: " + fixturePath, "Reference-change diagnostic is preserved.");
    });

    Test("Cached references release files and reject deletion or corruption", () =>
    {
        const string code = "return Fixture.Value + 3;";
        Check(engine.Process(Request(code, freshIdentity: false)).Success, "Fixture is cached before mutation.");
        var original = File.ReadAllBytes(fixturePath);
        var timestamp = File.GetLastWriteTimeUtc(fixturePath);
        using (File.Open(fixturePath, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { }
        File.Delete(fixturePath);
        Check(engine.Process(Request(code, freshIdentity: false)).ErrorCode == "stale_reference", "Compilation cache cannot hide a deleted reference.");
        File.WriteAllBytes(fixturePath, [0, 1, 2, 3]);
        File.SetLastWriteTimeUtc(fixturePath, timestamp);
        Check(engine.Process(Request(code, freshIdentity: false)).ErrorCode == "stale_reference", "Compilation cache cannot hide a corrupt reference with the same timestamp.");
        File.WriteAllBytes(fixturePath, original);
        File.SetLastWriteTimeUtc(fixturePath, timestamp);
        var restored = engine.Process(Request(code, freshIdentity: false));
        Check(restored.Success && restored.CacheHit && restored.EmitReused, "Restoring the same identity safely reuses cached compilation bytes.");
    });

    Test("Parallel validation preserves order, fresh identities and deterministic failures", () =>
    {
        foreach (var degree in new[] { 1, 2, 4 })
        {
            var parallel = new CompilerEngine(reuseBaseCompilation: false, referenceParallelism: degree);
            var cache = new MetadataReferenceCache();
            var reversed = references.Reverse().ToArray();
            var entries = cache.GetMany(reversed, degree);
            Check(entries.Select(entry => entry.Reference.FilePath).SequenceEqual(reversed.Select(reference => reference.Path)), "References remain in input order.");
            Check(entries.Select(entry => entry.Identity).SequenceEqual(cache.GetMany(reversed, degree).Select(entry => entry.Identity)), "Reference ordering survives cache hits.");
            var first = parallel.Process(Request("return Fixture.Value;"));
            var second = parallel.Process(Request("return Fixture.Value;"));
            Check(first.Success && second.Success && first.AssemblyName != second.AssemblyName, "Every degree preserves independent assembly identity.");
            Check(new CompilerEngine(false, degree).Process(Request("return Fixture.Value;", providedReferences: references.Concat(references).ToArray())).Success, "Repeated reference identities remain valid on a cold cache.");
            var missing = new ReferenceIdentity(Path.Combine(temporary, "missing-first.dll"), Guid.NewGuid().ToString());
            var malformed = new ReferenceIdentity(fixturePath, "invalid");
            Check(parallel.Process(Request("return 1;", providedReferences: [missing, malformed])).ErrorCode == "stale_reference", "First input error wins over a later preflight error.");
            Check(parallel.Process(Request("return 1;", providedReferences: [malformed, missing])).ErrorCode == "invalid_request", "Reversed input errors retain their order.");
        }
    });

    Test("Cached MVID probes reread values and reject changed PE or metadata layouts", () =>
    {
        var path = Path.Combine(temporary, "ProbeFixture.dll");
        WriteFixture(path, framework, 25);
        var identity = Identity(path);
        var mvid = Guid.Parse(identity.Mvid);
        var cache = new MetadataReferenceCache();
        var cached = cache.Get(path, mvid);
        Check(cached.Probe is not null, "Ordinary compiler references support bounded layout validation.");
        var original = File.ReadAllBytes(path);
        var timestamp = File.GetLastWriteTimeUtc(path);
        using var pe = new PEReader(System.Collections.Immutable.ImmutableArray.Create(original));
        var metadata = pe.GetMetadataReader();
        var start = pe.PEHeaders.MetadataStartOffset;
        var moduleOffset = start + metadata.GetTableMetadataOffset(TableIndex.Module);
        var mvidIndexOffset = moduleOffset + 2 + (metadata.GetHeapSize(HeapIndex.String) > ushort.MaxValue ? 4 : 2);
        var mvidOffset = start + metadata.GetHeapMetadataOffset(HeapIndex.Guid)
            + (MetadataTokens.GetHeapOffset(metadata.GetModuleDefinition().Mvid) - 1) * 16;
        foreach (var mutation in new Action<byte[]>[]
        {
            bytes => bytes[mvidOffset] ^= 1,
            bytes => BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(mvidIndexOffset, 2), 0),
            bytes => BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(pe.PEHeaders.CorHeaderStartOffset + 8, 4), 0),
            bytes => bytes[0] = 0,
            bytes => bytes[start] = 0,
        })
        {
            var changed = (byte[])original.Clone();
            mutation(changed);
            File.WriteAllBytes(path, changed);
            File.SetLastWriteTimeUtc(path, timestamp);
            var rejected = false;
            try { cache.Get(path, mvid); }
            catch (Exception ex) when (ex is StaleReferenceException or BadImageFormatException) { rejected = true; }
            Check(rejected, "Same-size, same-timestamp MVID/layout mutations cannot return cached metadata.");
            File.WriteAllBytes(path, original);
            Check(ReferenceEquals(cached, cache.Get(path, mvid)), "A restored image still uses its original cache entry.");
        }
        // A harmless change to a probed header must use the full reader, rather
        // than rejecting a valid reference just because the fast layout differs.
        var validChange = (byte[])original.Clone();
        validChange[pe.PEHeaders.CoffHeaderStartOffset + 4] ^= 1; // COFF timestamp.
        File.WriteAllBytes(path, validChange);
        Check(ReferenceEquals(cached, cache.Get(path, mvid)), "Valid changed headers retain full-reader compatibility.");
        File.WriteAllBytes(path, original[..(mvidOffset + 8)]);
        var truncated = false;
        try { cache.Get(path, mvid); }
        catch (Exception ex) when (ex is StaleReferenceException or BadImageFormatException or IOException) { truncated = true; }
        Check(truncated, "A shortened file is never accepted from the saved layout.");
        using (File.Open(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { }
    });

    Test("Validation-only requests check cached MVIDs without emitting executable bytes", () =>
    {
        var validating = new CompilerEngine(reuseBaseCompilation: false, referenceParallelism: 4);
        var request = new CompileRequest { Protocol = 1, Operation = "validate", References = references,
            RequestId = "validation", ReferenceGeneration = "generation-1" };
        var result = validating.Process(request);
        Check(result.Success && result.AssemblyBase64 is null && result.AssemblyName is null && result.RequestId == "validation", "Validation has no execution artifact.");
        var original = File.ReadAllBytes(fixturePath);
        var timestamp = File.GetLastWriteTimeUtc(fixturePath);
        WriteFixture(fixturePath, framework, 91);
        File.SetLastWriteTimeUtc(fixturePath, timestamp);
        Check(validating.Process(request).ErrorCode == "stale_reference", "Cached reference with unchanged timestamp still validates actual MVID.");
        File.WriteAllBytes(fixturePath, original);
        File.SetLastWriteTimeUtc(fixturePath, timestamp);
        Check(validating.Process(request).Success, "Failed validation does not poison the cache.");
        using (File.Open(fixturePath, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { }
    });

    Test("Worker never executes compiled code", () =>
    {
        var sentinel = Path.Combine(temporary, "must-not-exist.txt");
        var code = "System.IO.File.WriteAllText(" + JsonSerializer.Serialize(sentinel) + ", \"executed\"); return 0;";
        Check(engine.Process(Request(code)).Success && !File.Exists(sentinel), "Only DLL generation occurs.");
    });

    var output = new StringWriter();
    var pingRequest = JsonSerializer.Serialize(new CompileRequest { Protocol = 1, Operation = "ping", RequestId = "after-malformed" }, WireJson.Options);
    await UnityBridge.Compiler.Program.ServeAsync(new StringReader("{broken\nnull\n" + pingRequest + "\n"), output);
    var lines = output.ToString().Split('\n', StringSplitOptions.RemoveEmptyEntries);
    Check(lines.Length == 3, "Exactly one JSONL response per request, with no stdout logging.");
    Check(JsonSerializer.Deserialize<CompileResponse>(lines[0], WireJson.Options)?.ErrorCode == "invalid_request", "Malformed JSON response.");
    Check(JsonSerializer.Deserialize<CompileResponse>(lines[1], WireJson.Options)?.ErrorCode == "invalid_request", "Null request response.");
    Check(JsonSerializer.Deserialize<CompileResponse>(lines[2], WireJson.Options) is { Success: true, RequestId: "after-malformed" }, "JSONL server survives malformed requests.");
    passed++;
    Console.WriteLine("PASS JSONL malformed input recovery");
    Console.WriteLine($"All {passed} compiler regression scenarios passed.");

    CompileRequest Request(string code, bool freshIdentity = true, ReferenceIdentity[]? providedReferences = null, string language = "9.0")
        => new()
        {
            Protocol = 1, Operation = "compile", RequestId = "request-1", Code = code,
            References = providedReferences ?? references, LanguageVersion = language, FreshIdentity = freshIdentity,
            ProjectId = temporary, ReferenceGeneration = "generation-1",
        };

    void Test(string name, Action action)
    {
        action();
        passed++;
        Console.WriteLine("PASS " + name);
    }
}
finally
{
    Directory.Delete(temporary, recursive: true);
}

static void Check(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}

static ReferenceIdentity Identity(string path)
{
    using var stream = File.OpenRead(path);
    using var pe = new PEReader(stream);
    var metadata = pe.GetMetadataReader();
    return new ReferenceIdentity(Path.GetFullPath(path), metadata.GetGuid(metadata.GetModuleDefinition().Mvid).ToString("D"));
}

static string ReadAssemblyName(byte[] image)
{
    using var stream = new MemoryStream(image);
    using var pe = new PEReader(stream);
    var metadata = pe.GetMetadataReader();
    return metadata.GetString(metadata.GetAssemblyDefinition().Name);
}

static void WriteFixture(string path, IEnumerable<string> framework, int value)
{
    var code = $$"""
        namespace UnityEngine { public class Object {} }
        namespace UnityEngine.SceneManagement { public class Fixture {} }
        namespace UnityEditor { public class Fixture {} }
        namespace UnityEditor.SceneManagement { public class Fixture {} }
        namespace UnityEditorInternal { public class Fixture {} }
        public static class Fixture { public const int Value = {{value}}; }
        """;
    var compilation = CSharpCompilation.Create("UnityFixture", [CSharpSyntaxTree.ParseText(code)],
        framework.Select(item => MetadataReference.CreateFromFile(item)), new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));
    using var stream = File.Create(path);
    var result = compilation.Emit(stream);
    Check(result.Success, "Fixture compilation failed: " + string.Join("\n", result.Diagnostics));
}
