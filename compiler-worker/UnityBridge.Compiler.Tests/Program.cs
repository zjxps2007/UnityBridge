using System.Reflection.Metadata;
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

    Test("Ping and protocol negotiation", () =>
    {
        var ping = engine.Process(new CompileRequest { Protocol = 1, Operation = "ping", RequestId = "ping-1" });
        Check(ping.Success && ping.RequestId == "ping-1" && ping.CompilerVersion.StartsWith("roslyn-5.0.0/"), "Ping correlation/version.");
        Check(engine.Process(new CompileRequest { Protocol = 2, Operation = "ping" }).ErrorCode == "unsupported_protocol", "Reject incompatible protocols.");
    });

    Test("Compile explicit Unity references and unicode source", () =>
    {
        var result = engine.Process(Request("return new UnityEngine.Object();"));
        Check(result.Success && result.AssemblyBase64 is not null, result.Error ?? "DLL expected.");
        Check(ReadAssemblyName(Convert.FromBase64String(result.AssemblyBase64!)) == result.AssemblyName, "Emitted identity is accurate.");
        Check(result.ReferenceGeneration == "generation-1" && result.RequestId == "request-1", "Request metadata preserved.");
        Check(engine.Process(Request("return \"한글🧪\";")).Success, "Unicode source is compiled.");
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
