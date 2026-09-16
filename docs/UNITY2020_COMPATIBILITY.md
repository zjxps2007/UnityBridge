# Unity 2020.3 compatibility evidence

Reviewed for `0.3.0-alpha.1` on 2026-09-17. The Connector still declares Unity
2020.3 as its minimum version. **This is an API/source compatibility audit, not a
successful Unity 2020.3 compilation or native runtime test.** No 2020.3 Editor or
matching reference binaries were available in the checked local installations and
caches. No Editor was installed for this audit.

## Unity API surface

| Connector use | Evidence in the 2020.3 API or Unity's reference source |
|---|---|
| Enumerate Editor assemblies | [`CompilationPipeline.GetAssemblies(AssembliesType)`](https://docs.unity3d.com/2020.3/Documentation/ScriptReference/Compilation.CompilationPipeline.GetAssemblies.html) is documented in 2020.3. |
| Read compiler options | [`Assembly.compilerOptions`](https://docs.unity3d.com/2020.3/Documentation/ScriptReference/Compilation.Assembly-compilerOptions.html) and [`ScriptCompilerOptions`](https://docs.unity3d.com/2020.3/Documentation/ScriptReference/Compilation.ScriptCompilerOptions.html) are documented. The [2020.3 reference source](https://github.com/Unity-Technologies/UnityCsReference/blob/2020.3/Editor/Mono/Scripting/ScriptCompilation/CompilationPipeline.cs) exposes `LanguageVersion` with a public getter and initializes it to `8.0`. |
| Initialize and schedule host discovery | [`InitializeOnLoadAttribute`](https://docs.unity3d.com/2020.3/Documentation/ScriptReference/InitializeOnLoadAttribute.html), [`EditorApplication.delayCall`](https://docs.unity3d.com/2020.3/Documentation/ScriptReference/EditorApplication-delayCall.html), and [`EditorApplication.update`](https://docs.unity3d.com/2020.3/Documentation/ScriptReference/EditorApplication-update.html) are documented in 2020.3. |
| Exclude import worker processes | `AssetDatabase.IsAssetImportWorkerProcess()` is present in Unity's [2020.3 AssetDatabase binding source](https://github.com/Unity-Technologies/UnityCsReference/blob/2020.3/Modules/AssetDatabase/Editor/ScriptBindings/AssetDatabase.bindings.cs). Its individual archived API page was unavailable; source availability is the evidence. The existing Connector already used this API. |

The language option is queried reflectively. If it cannot be obtained, versions
before Unity 2021.2 select C# 8.0. The introduced Connector code does not require
records, nullable-reference annotations, collection expressions, or other recent
C# syntax. Unity documents C# 8.0 for 2020.3, with runtime restrictions including
default interface methods, ranges, async streams, and async disposal.
[Unity C# compiler manual](https://docs.unity3d.com/2020.3/Documentation/Manual/CSharpCompiler.html)

## Framework and external compiler boundary

The new scheduling and deadline code uses established Framework APIs:
[`Task.Run`](https://learn.microsoft.com/en-us/dotnet/api/system.threading.tasks.task.run?view=netframework-4.6.2),
[`SemaphoreSlim.WaitAsync(Int32)`](https://learn.microsoft.com/en-us/dotnet/api/system.threading.semaphoreslim.waitasync?view=netframework-4.6.2),
[`Interlocked.Read`](https://learn.microsoft.com/en-us/dotnet/api/system.threading.interlocked.read?view=netframework-4.6.2),
and [`ProcessStartInfo.Arguments`](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.processstartinfo.arguments?view=netframework-4.6.2).
Reflection, process launching, and assembly loading were already used by the
Connector. Editor code remains in its Editor-only assembly definition.

The .NET 10 compiler executable runs outside Unity. Its framework DLLs are not
added to the Unity package or used as snippet references. Roslyn receives the
running Editor's explicit language version and loaded-reference paths/MVIDs;
emitted snippets therefore target those references. This separation matters:
Unity 2020.3 documents .NET Standard 2.0/.NET 4.x profiles and does not support
loading .NET Core plugins.
[Unity framework profile support](https://docs.unity3d.com/2020.3/Documentation/Manual/dotnetProfileSupport.html)

## Verified checks and remaining gate

- Connector compilation with `-langversion:8.0` succeeded using **Unity 2021.3
  reference assemblies**, with 2021-or-newer symbols removed. This checks C# 8
  syntax and fallback compilation; it does not verify 2020.3 binary API coverage.
- Native functional suites passed on Unity 2021.3.19f1 and 6000.3.13f1, covering
  authentication, compilation, repeated execution/static isolation, reference
  invalidation, deadline rejection, live controls, domain reload, and play/pause
  readiness. These are separate evidence for those Editor versions.
- Before claiming native 2020.3 verification, run `scripts/verify-host.py` with an
  actual 2020.3 Editor and the published worker in a new disposable output
  directory. Exercise both supported API compatibility profiles and confirm the
  context reports C# 8.0 and the expected framework references.

The audit found no introduced Unity API that requires a newer minimum version.
Actual 2020.3 import, emitted-assembly execution, operating-system process launch,
and reload behavior remain unverified.
