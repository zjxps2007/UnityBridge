# Native startup and discovery checks

`StartupDiscoveryAudit.cs` is copied into disposable projects by
`scripts/verify-startup.py`; it is not part of the shipped Unity package.
The runner also extracts the baseline discovery implementation as
`LegacyToolDiscovery` for handler and schema compatibility checks.

The Connector is installed as an embedded UPM package using the source
`package.json` name and version, rather than copying its scripts into `Assets`.
For offline validation, Newtonsoft is copied from the installed Editor and its
registry dependency is omitted from the fixture manifest. Existing user projects
and installations are not changed.

Build a baseline CLI from the chosen release in a separate checkout/snapshot and
the candidate bundle with the same Python/PyInstaller environment. Install or
extract the candidate archive, then run from the repository root:

```powershell
python scripts/verify-startup.py --unity-editor "C:/Program Files/Unity/Hub/Editor/6000.3.13f1/Editor/Unity.exe" --unity-version 6000.3.13f1 --baseline-bin "path/to/baseline/unity-bridge.exe" --candidate-bin "path/to/candidate/unity-bridge.exe" --output .codex-deps/startup-unity6
```

The output directory must be empty. Repeat with the installed Unity 2021 Editor
and a different output directory. Each run starts fresh Editor processes in
baseline/candidate/candidate/baseline order, observes a real matching heartbeat,
and measures the first console command without an RPC warm-up. It then checks
lazy schemas, repeated list isolation, dynamically loaded tools, duplicate names,
the baseline schema/handler contract, a real compilation/domain reload, and an
actual `exec` compilation/Assembly.Load followed by another tool-list request.
It also checks that JSON `status`, live `wait-ready`, and the human-readable
`Connector:` line match the package version, both before and after domain reload.
These checks catch a stale runtime version even when CLI and remote manifest
version checks pass.
Use `--variants candidate` for a candidate-only functional follow-up.

For heartbeat changes, pass `--heartbeat-audit` and use the same installed CLI for
both variants to isolate Connector behavior. For example, add
`--baseline-ref v0.2.2 --variants baseline candidate --heartbeat-audit`.
The runner copies `HeartbeatPublishingAudit.cs` into the disposable project,
samples the saved file for five seconds at roughly 10 ms intervals using the
CLI's bounded file-read retries, times 100 warm writes, and checks four real
pause/resume events and subsequent `status` calls. The candidate must publish
the new state by the pause event observer;
baseline differences are recorded without failing the comparison. Warm write
timing includes reflection and filesystem work, not whole-command latency.
The fixture requests pause/resume through a file observed on `Editor.update`,
because a paused Unity 2021 batch-mode Editor can suspend HTTP async continuations.
The `status` checks still use the supplied standalone executable. The optional
component profile separates snapshot/JSON creation, atomic writes, process lookup,
and directory creation so publication changes can be assessed with their cost.

These are empty-project batch-mode measurements, not GUI background latency or
the time from an agent prompt to its displayed answer. Previous runs are retained
and failing sessions are written before the runner exits.

## External host validation

`scripts/verify-host.py` creates a disposable embedded-package project and an
isolated host registry. It checks real external compilation, authentication,
static-state isolation, stale references/domains, deadlines inside the execution
lock, control requests during queued work, compiler errors, reload recovery, and
play/pause readiness. Asynchronous handlers and custom result getters must both
remain on the Unity main thread. It starts and closes only the processes it owns.

```powershell
python scripts/verify-host.py --unity-editor "C:/Program Files/Unity/Hub/Editor/6000.3.13f1/Editor/Unity.exe" --unity-version 6000.3.13f1 --worker "path/to/compiler/UnityBridge.Compiler.exe" --cli-exe "path/to/unity-bridge.exe" --stale-host-registry --output .codex-deps/host-native-unity6
```

Omit `--cli-exe` to exercise the source Python package. Packaged mode registers
the supplied executable so Unity's automatic launch is also tested. The stale
registry option verifies recovery when an old host PID belongs to another live
process. Repeat on Unity 2021 with a separate output directory.

`scripts/benchmark-host.py` measures standalone subprocess-to-response latency
against `v0.2.3` in baseline/candidate/candidate/baseline order. Use matching
Python/PyInstaller builds. It records cold service startup separately from
prepared execution, ordinary-command and exec p50/p95, installed size, Windows
working sets, and Editor update gaps above 1 ms across the entire measured run.
Those gaps are batch-mode observations, not GUI/game frame-time measurements.

```powershell
python scripts/benchmark-host.py --unity-editor "C:/Program Files/Unity/Hub/Editor/6000.3.13f1/Editor/Unity.exe" --unity-version 6000.3.13f1 --baseline-bin "path/to/v0.2.3/unity-bridge.exe" --candidate-bin "path/to/candidate/unity-bridge.exe" --output .codex-deps/host-benchmark-unity6
```

To compare two external-host builds, add `--baseline-host --baseline-ref <commit>`
and supply the matching baseline executable. Both variants then register/start
their own host and perform the same cold and prewarm-only sequences. Without
this flag the baseline retains the legacy path used for the v0.2.3 comparison.

The result file records the ordinary-command gate: candidate p95 may not exceed
baseline by more than `max(5% of baseline, 10 ms)`. A functional pass alone does
not imply that this performance gate passed. Minimum Unity 2020.3 API evidence
and the absence of a native 2020 run are documented in
[UNITY2020_COMPATIBILITY.md](../../docs/UNITY2020_COMPATIBILITY.md).
