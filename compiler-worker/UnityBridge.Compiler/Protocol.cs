using System.Text.Json;
using System.Text.Json.Serialization;

namespace UnityBridge.Compiler;

public sealed record ReferenceIdentity(string Path, string Mvid);

public sealed class CompileRequest
{
    public int Protocol { get; init; }
    public string? Operation { get; init; }
    public string? RequestId { get; init; }
    public string? ParentRequestId { get; init; }
    public string? Code { get; init; }
    public string[] Usings { get; init; } = [];
    public string? LanguageVersion { get; init; }
    public ReferenceIdentity[] References { get; init; } = [];
    public string? ProjectId { get; init; }
    public string? ReferenceGeneration { get; init; }
    // Fresh names preserve per-call type/static isolation on every supported Unity runtime.
    public bool FreshIdentity { get; init; } = true;
}

public sealed record CompilerDiagnostic(string Id, string Severity, string Message, int? Line, int? Column);

public sealed class CompileResponse
{
    public int Protocol { get; init; } = 1;
    public string? RequestId { get; init; }
    public bool Success { get; init; }
    public string CompilerVersion { get; init; } = CompilerEngine.CompilerVersion;
    public string? AssemblyBase64 { get; init; }
    public string? AssemblyName { get; init; }
    public string? ReferenceGeneration { get; init; }
    public bool CacheHit { get; init; }
    public bool BaseCacheHit { get; init; }
    public bool EmitReused { get; init; }
    public CompilerDiagnostic[] Diagnostics { get; init; } = [];
    public string? ErrorCode { get; init; }
    public string? Error { get; init; }
}

public static class WireJson
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        MaxDepth = 32,
    };
}
