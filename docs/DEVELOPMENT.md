# CLI maintenance

[한국어](DEVELOPMENT.ko.md) | English

The public entry point remains `unity_bridge.cli:main`. Installed commands,
`python -m unity_bridge`, and the standalone build all use this function.
Implementation modules live in `src/unity_bridge/_cli/`.

| File | Responsibility |
|---|---|
| `cli.py` | Select the built-in or direct-tool route, create the client, print the result, and choose the exit code. |
| `_cli/arguments.py` | Built-in options and help; direct-tool flags, repeated values, positionals, and JSON parameters. |
| `_cli/commands.py` | Map parsed built-in options to `UnityClient` and `UnityBridgeAdapter` calls; read C# code input. |
| `_cli/output.py` | Text and JSON rendering, errors, Connector version warnings, and update output. |
| `_cli/updates.py` | Python package updates, scheduling standalone updates, remote versions, and daily notice caching. |
| `_cli/standalone.py` | Platform/architecture selection and platform-specific installer command construction. |
| `_cli/versions.py` | Shared version parsing and comparison. |
| `host/` | Optional local service, authenticated transport, project queues, runtime registration, and compiler process supervision. |
| `compiler-worker/` (repository root) | Independent Roslyn compiler, its private JSONL protocol, and compiler regression scenarios. |

The `_cli` package is internal. Python integrations should use the client and
adapter APIs exported by `unity_bridge`. The existing `cli.build_parser` and
`cli.add_common_options` functions remain available.

## Independent Host And Compiler

The current branch is unreleased **0.3.0-alpha.1**; public **v0.2.3** remains the
stable baseline. The service runs outside Unity, while the Connector still owns
Unity API execution on the main thread. A reference context includes the domain
and reference generation, actual DLL paths/MVIDs, and explicit C# language version.
No .NET 10 framework references are substituted for Unity's references.

The service starts the compiler process early and schedules one background
`return null;` compilation per new project context. That warmup DLL is never
loaded into Unity. Repeated user source reuses parsed/bound compiler preparation
but emits a unique assembly identity on every invocation. Runtime return values,
loaded assemblies, and delegates are not cached by the host. Worker cache eviction
does not unload assemblies already loaded in the Unity domain.

Install Python build dependencies and a .NET 10 SDK. CI pins SDK **10.0.401**;
Roslyn **5.0.0** is pinned in the compiler project. A workspace SDK can be selected
with `--dotnet PATH`; users of the built bundle do not install an SDK.

```sh
python -m pip install -e ".[build]"
dotnet run --project compiler-worker/UnityBridge.Compiler.Tests --configuration Release
python scripts/build-compiler.py --runtime win-x64 --output build/compiler/win-x64
python scripts/build-standalone.py --output-name unity-bridge-windows-amd64.zip --compiler-dir build/compiler/win-x64
```

For other platforms, use `linux-x64`, `linux-arm64`, `osx-x64`, or `osx-arm64`
and the matching archive name. `build-standalone.py` builds the native compiler
automatically when `--compiler-dir` is omitted. `--without-compiler` deliberately
creates a development bundle that uses direct Connector execution. Build output
lives under ignored `build/` and `dist/` directories.

To register an editable Python checkout with a built Windows worker:

```powershell
$python = (Get-Command python).Source
$worker = (Resolve-Path .\build\compiler\win-x64\UnityBridge.Compiler.exe).Path
python -m unity_bridge _host register --executable $python --python-module --worker $worker
python -m unity_bridge _host start
python -m unity_bridge --backend host exec --code "return 42;"
```

Use a matching local Connector package and keep Unity open. On macOS/Linux, use
the absolute Python path and worker executable without `.exe`. For a manually
unpacked standalone bundle, run its executable's `_host register --executable
<absolute-cli-path> --worker <absolute-runtime/compiler/UnityBridge.Compiler-path>`
without `--python-module`. Packaged installers perform this registration themselves.
`_host` is a private installer/developer interface; `_host status` and `_host stop`
are available for diagnosis. An open Unity Editor may restart a stopped host.

For isolated tests, set `UNITY_BRIDGE_HOST_HOME` to a temporary directory in both
Unity's launch environment and the CLI. `--instances-dir` can be supplied when
registering the test launcher. Never include registry tokens in test reports.

The private protocol and cache limits are documented in
[compiler-worker/README.md](../compiler-worker/README.md). Preserve these boundaries:

- Host requests retain their original deadline; Unity rechecks it after acquiring
  the execution lock and before loading an emitted assembly.
- A changed context can be refreshed before execution. Once dispatch is uncertain,
  return `unknown` rather than replaying the command. Only a proven `not_started`
  rejection permits a preparation retry.
- Live control queries bypass the mutation queue. Host health cannot advance the
  Unity heartbeat or satisfy live readiness. Existing heartbeat PID/port fields
  continue to identify Unity; host registration lives in separate files.
- Token-bearing requests stay on loopback, do not inherit proxies, and do not
  follow redirects. New runtime registration retires the previous service after
  its outstanding work drains.

## Changing a command

1. Define its options and add its name to `KNOWN_COMMANDS` in `arguments.py`.
2. Map those options in `commands.execute_command`. Return the client/adapter
   result; the entry point handles printing and success/failure exit codes.
3. Add request-level coverage in `tests/test_cli.py`. Command syntax, emitted
   JSON, stdout/stderr, and exit codes are compatibility contracts.

Unknown command names follow the direct-tool parser. Keep its repeated flags,
`--params`, and `--` handling independent of built-in argparse options. Direct
tools reuse the instance already discovered for the request. JSON output must
retain the shallow wrapper around response data rather than copy nested payloads.

Keep argument parsing ahead of update-module imports so help can finish early.
Installed-package metadata is loaded only when an update/version check needs it.
Automatic notices retain their existing daily cache, skip flags, and timeout.

Remote version checks can use `UNITY_BRIDGE_GITHUB_TOKEN` when explicitly set.
The release workflow supplies its read-only repository token only to the archived
executable verification step. Authorization is sent to the initial GitHub API
request and is omitted from redirects. `tests/test_update_auth.py` checks this
with an offline HTTP transport, including same-host and cross-host redirects.

## Validation

From the repository root:

```sh
python -m unittest discover -s tests
python -m compileall -q src tests
git diff --check
```

For CLI changes alone:

```sh
python -m unittest discover -s tests -p test_cli.py
```

`tests/test_client.py` covers discovery, HTTP, and adapters. Shared temporary
heartbeat and HTTP fixtures are in `tests/helpers.py`. `tests/fixtures/cli_requests.json`
records 21 request contracts captured before the CLI split; change these only
when an intentional command contract change also updates its documentation.
`tests/test_installers.py` uses offline fixture downloads and temporary install
directories; platform tests are skipped when the required platform or shell is absent.

For standalone changes, build an archive with `scripts/build-standalone.py`,
unpack it, and exercise the resulting executable. Compare startup with the same
Python/PyInstaller versions and build mode; source-import timing alone does not
verify the packaged command. Native Unity checks are described in
[tests/unity/README.md](../tests/unity/README.md).

For the host branch, include `tests/test_host_service.py`,
`tests/test_host_compiler.py`, `tests/test_host_registry.py`, and the C# regression
command above. Exercise duplicate IDs, deadlines before and after queueing,
compiler failure/restart, reload during preparation, lost responses after
dispatch, token isolation, and multiple projects. Native checks must cover both
Unity 2021 and Unity 6; minimum-version API compatibility is a separate check.

The release workflow is configured to build and verify Windows x64, Linux x64
and ARM64, and macOS Intel and Apple Silicon bundles, including the compiler
worker. Changing that workflow is not evidence that all platform jobs have run.
Before enabling a new default route, compare with v0.2.3 using identical projects
and build dependencies: cold and prewarmed requests, p50/p95 end-to-end latency,
Editor stalls, resident memory, and installed size. Investigate a normal-command
p95 regression exceeding the larger of 5% or 10 ms; compiler microbenchmarks
alone do not establish whole-command improvement.

## Heartbeat publication

v0.2.3 keeps periodic publication at 0.5 seconds, matching v0.2.2.
Each tick checks state, compile errors, and port before applying
the interval. Server startup and pause events publish explicitly. Keep Unity API
reads and publication on the main thread; a background timer must not make an
unresponsive Editor appear ready. Pending refresh, compile, and play-mode grace
periods must remain in force.

All writes go through the same atomic replacement and record their attempt time,
including failed writes, to avoid retrying filesystem errors on every Editor
frame. Event writes reset the periodic clock to avoid a redundant scheduled write
immediately afterward. Steady-state writes remain at about 2 per
second; state events can add writes. Use `--heartbeat-audit` in the native runner
to compare actual cadence, file-write costs, and pause/resume status publication.
These measurements do not establish whole-command or agent response speed.

An earlier 0.1-second experiment increased periodic writes fivefold. v0.2.3
keeps the 0.5-second cadence and prioritizes publication when state changes.
An unchanged Editor's `Heartbeat age` therefore keeps its usual range; the
improvement is fresher state at transitions. Event writes and per-update state
checks still have a cost, so do not describe the change as having zero overhead.

## Connector version reporting

`unity-bridge status` prints the version published by the running Unity Connector,
not the CLI version. `Heartbeat` resolves it from Unity's package metadata and
caches it until a package registration change or domain reload. Do not add a
separate C# release-version constant. Source copies outside a UPM package report
`unknown` instead of guessing a release version.

Before a release, run the native checks in Unity 2021 and Unity 6. The heartbeat,
live readiness response, and `Connector:` status line must match the installed
`package.json`. `update --check` reads the remote manifest and does not replace this
runtime check. v0.2.2-rc.1 shipped with a stale runtime constant despite matching
CLI and manifest versions; v0.2.2-rc.2 fixes the runtime version source.
