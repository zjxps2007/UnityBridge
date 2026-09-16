# Independent C# compiler worker

This self-contained .NET 10 process uses pinned Roslyn 5.0.0. It parses and emits
assemblies in memory and **never loads or executes user code**. Unity provides
the reference DLL paths, their MVIDs, and its supported C# language version. The
worker does not supply references from its own .NET runtime.

Build and test with a .NET 10 SDK:

```sh
dotnet run --project compiler-worker/UnityBridge.Compiler.Tests --configuration Release
python scripts/build-compiler.py --runtime win-x64 --output build/compiler-publish
```

`--dotnet` selects an explicit SDK executable. Supported publish targets are
`win-x64`, `linux-x64`, `linux-arm64`, `osx-x64`, and `osx-arm64`. Deploy the whole
output directory, including its runtime and Roslyn libraries.

## Private protocol, version 1

Input and output are UTF-8 JSON Lines. There is exactly one response per input
line. Stdout contains protocol messages only. The parent serializes requests and
kills/restarts this process if compilation exceeds the smaller of 30 seconds
and the original command's remaining deadline.

Readiness probe:

```json
{"protocol":1,"operation":"ping","request_id":"probe"}
```

Compilation request:

```json
{
  "protocol": 1,
  "operation": "compile",
  "request_id": "unique-request-id",
  "project_id": "absolute Unity project path",
  "reference_generation": "parent-computed manifest fingerprint",
  "code": "return 42;",
  "usings": [],
  "language_version": "9.0",
  "references": [{"path": "absolute/reference.dll", "mvid": "00000000-0000-0000-0000-000000000000"}],
  "fresh_identity": true
}
```

The example is expanded for readability; transmit each request on one line.
`references` must contain the complete, actual Unity reference set. Numeric
language versions are required; `latest`, `preview`, and an implicit default are
rejected. Code is wrapped in `__CliDynamic.Execute()` with the existing CLI
default using directives and warning suppression.

Successful responses contain `success`, `request_id`, `compiler_version`,
`reference_generation`, `assembly_base64`, `assembly_name`, `diagnostics`,
`cache_hit`, and `emit_reused`. Diagnostics include ID, severity, message, and
optional one-based line/column in the wrapped source. Failures contain
`error_code` and `error`; `stale_reference` means the parent must refresh the
Unity manifest before attempting compilation again. There is no execution or
replay decision inside this process.

## Cache and isolation

Every request verifies reference MVIDs on disk, including compilation cache
hits. References are read into memory, so retained metadata does not lock Unity
DLLs during rebuilds. Missing, changed, or unreadable references fail before
emission. Compilation keys include source, language/options, compiler and
wrapper version, project ID, and ordered absolute reference paths/MVIDs.

`MetadataReferenceCache` owns reference loading and identity checks. A cold load
reads one image and shares its immutable bytes between MVID validation and Roslyn;
a cache hit still reads the file's actual MVID. `BoundedCache` handles retention
separately from compilation, so changing eviction policy does not change identity
validation or emitted assembly isolation.

`fresh_identity` defaults to `true`: cached parsing/binding is reused, but each
call emits a unique assembly name to preserve per-call type and static-state
isolation. Only explicit `false` permits byte-identical DLL reuse. `cache_hit`
therefore does not imply emission was skipped; `emit_reused` reports that fact.
The Connector, not this process, is responsible for validating domain generation
again before loading bytes and executing on Unity's main thread.

Metadata and compilation caches each have a 256 MiB estimated-retention budget,
with 512 reference entries and 64 compilation entries respectively. Compilation
weights conservatively include referenced images even when shared. Entries too
large for a budget are processed without caching. These limits are not a hard
process-memory cap: runtime, JIT, current compilation, and transient allocations
are additional. Evicting worker cache entries does not unload DLLs already loaded
inside Unity.
