# Python startup and command performance

[한국어](PYTHON_STARTUP.ko.md) | [README](../README.md)

This work follows the public **v0.3.0-rc.2** release. It does not change the
published RC2 assets or stable v0.2.3. Python remains the CLI and host language;
Roslyn remains a separate process. Python package support still starts at 3.10.

## Implementation

- The Connector schedules filesystem checks and external host startup from its
  initialization callback. Import workers are excluded. Only external process
  preparation starts early; Unity reference collection and command execution
  still require the live ready/context checks. Host liveness never means Unity
  is ready. [Unity initialization rules](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/InitializeOnLoadAttribute.html).
- `_host` has a separate entry point. The compiler process starts while the host
  imports its server modules. When no ready project is available, the compiler
  can parse and emit a small framework-only assembly, which is discarded and
  never executed. Real requests take priority over preparation that has not
  started; an already running compilation is not interrupted.
- A first request waits for initial reference negotiation under its original
  deadline. Live state queries do not need that context. Requests that expire
  while waiting cannot execute after preparation finishes. The actual Editor
  startup checks exposed and fixed this initial-negotiation race.
- `console`, `tools`, and `wait-ready` join the lightweight `exec` path. An
  advertised capability list prevents submission of unsupported commands to
  older hosts. Unsupported syntax and compiler overrides use the original path
  before dispatch. The existing daily update checks are unchanged.
- The fast path also implements `instances` and `status`, but forwarding these
  snapshots exceeded the first Windows p95 gate. They retain local processing
  by default. `UNITY_BRIDGE_FAST_SNAPSHOTS=1` enables the experiment explicitly.
- Session handlers return result objects directly, followed by one JSONL
  serialization. They no longer redirect process-global output or decode the
  CLI's rendered JSON. The request/response schema and per-request discovery are
  unchanged.
- Long-lived clients and the host use bounded persistent HTTP connections, with
  separate execution, control and negotiation lanes. PID, port, domain,
  reference generation or host identity changes retire the affected connection.
  Responses are fully read. Idle closed sockets can be replaced before a new
  submission; a request with a lost response is never replayed.
  [HTTPConnection reuse](https://docs.python.org/3.14/library/http.client.html).
- Base compilations share the existing 64-entry, 256 MiB estimated retention
  budget with snippet compilations. Keys include project, compiler, references,
  language and options. Every request still checks reference MVIDs and emits a
  fresh assembly identity. Roslyn can carry observed metadata into derived
  compilations, but changing assembly identity requires symbol rebinding, so
  this does not eliminate all binding work. Results and loaded assemblies are
  never reused. The base cache is opt-in because the separate experiment did
  not show a benefit; the existing source-specific cache remains enabled.
  [Roslyn implementation](https://github.com/dotnet/roslyn/blob/main/src/Compilers/CSharp/Portable/Compilation/CSharpCompilation.cs).
- Internal host/compiler/frame deadlines use `perf_counter()`. The tested
  Windows Python 3.12 reported a 15.625 ms `GetTickCount64` monotonic clock,
  compared with a 0.0001 ms QPC performance counter. A monotonic deadline is
  anchored before discovery and lock waits, preventing those waits from
  extending the caller's budget. [Python clock semantics](https://docs.python.org/3.12/library/time.html#time.perf_counter).

## Reproduce and inspect

Use the actual public RC2 archive for the release baseline. A local 3.14 build
of the RC2 source is a different runtime experiment, not the public baseline.
Build comparison variants with the same compiler directory and packaging tools:

```powershell
python scripts/build-standalone.py --compiler-dir <published-worker-directory> --output-name unity-bridge-windows-amd64.zip --output-dir <variant-output> --work-dir <variant-build>
python scripts/benchmark-host.py --unity-editor <Unity.exe> --unity-version <version> --baseline-bin <public-RC2.exe> --candidate-bin <candidate.exe> --baseline-ref v0.3.0-rc.2 --baseline-host --variants baseline candidate --cold-samples 50 --samples 100 --exec-samples 100 --session-samples 100 --extended --output <empty-directory>
```

The driver creates disposable projects and owns their Unity processes. Manual
service-start measurements disable automatic launching identically in the two
fixture Connectors; they include the `_host start` subprocess, discovery, first
CLI process and first execution. Use `--startup-host --cold-samples 1` separately
to register before Unity starts and issue the first command after its ready
heartbeat. `--gui foreground|background` records whether Unity actually owns the
foreground window. Batch update gaps are not interactive frame stalls.

Diagnostic ablations use `--candidate-env NAME=1` with
`UNITY_BRIDGE_DISABLE_FAST_CLI`, `UNITY_BRIDGE_DISABLE_CONNECTION_REUSE`,
`UNITY_BRIDGE_DISABLE_BASE_COMPILATION`, `UNITY_BRIDGE_DISABLE_EARLY_HOST`, or
`UNITY_BRIDGE_DISABLE_COMPILER_WARMUP`. These are experiment controls, not
required user configuration. The normal performance runs leave timing output
disabled and do not clear the OS file cache or claim reboot-cold results.

`UNITY_BRIDGE_ENABLE_BASE_COMPILATION=1` enables the optional base Compilation
experiment. Its separate measurement did not improve new-code latency, so it
is disabled by default; the existing source-specific cache remains enabled.
`UNITY_BRIDGE_DISABLE_COMPILER_WARMUP` disables only framework-only preparation,
not all project-reference preparation.

Set `UNITY_BRIDGE_TIMING_DIR` to an empty writable directory before launching
the CLI/host/Unity to collect per-process JSONL events. They separate entry/import,
compiler spawn/request, reference negotiation, host queue, Unity main-thread
queue, execution, serialization and transmission. No source code, parameters,
results or authentication tokens are written. Python events use nanoseconds;
Unity events include Stopwatch ticks/frequency. Compare durations within each
process; epoch timestamps are for approximate cross-process alignment. Timing
I/O changes the measured workload and is excluded from acceptance runs. On
Windows, the parent driver and child CLI share QPC for process-launch-to-entry
and result-to-exit intervals.

## Runtime and packaging experiment

The final RC2 comparison uses official CPython **3.12.10**, with a `python312.dll`
hash identical to the public RC2 bundle. The separate runtime experiment compares
standard CPython 3.12.13 and 3.14.5; the packaging experiment uses 3.12.13 for both
packagers. Those controlled experiments share source, PyInstaller 6.20.0 and the
same self-contained .NET 10/Roslyn worker; Nuitka is 4.2.1. Do not attribute a
change between different Python distributions entirely to application code.
No free-threaded build, JIT or extra resident worker is enabled.

```powershell
python scripts/build-nuitka-experiment.py --output <empty-experiment-directory> --compiler-dir <published-worker-directory> --c-compiler mingw64
```

The Nuitka script creates an experimental standalone directory, not a release
archive. Nuitka keeps native libraries beside its executable. The production
installer requires an immutable versioned runtime directory, allowing it to
stage dependencies before replacing the CLI. Runtime recognition and executable
path lookup handle Nuitka independently of `sys.frozen`, but this alone does not
make its flat bundle update-compatible. [Nuitka standalone](https://nuitka.net/user-documentation/user-manual.html),
[runtime identification](https://nuitka.net/user-documentation/tips.html#detecting-nuitka-compilation-at-runtime).

Adoption requires first-result p50 improvement of at least `max(10%, 10 ms)`,
compatible installation/update behavior and all five platform checks. Otherwise
PyInstaller remains the default. The general command gate allows at most
`max(5%, 10 ms)` p95 regression against public RC2. A 20% cold first-result
improvement is a target, not a claim. Memory and installed-size growth have a
10% default budget.

## Results

Warmed commands and repeated sessions improved. **The 20% p50 target for a newly started service against an already running Unity was not achieved.** Overlapping preparation with Editor startup is a separate scenario below. Python 3.12 and PyInstaller remain the default. These are Windows empty-project measurements, not large-project or agent/model latency claims.

[Raw samples, checksums and experiment cohorts](benchmarks/python-startup-2026-09-19/README.md)

**Final performance acceptance is on hold:** two valid foreground cohorts showed approximately 337 ms new-code execution. Subsequent runs of the identical binary did not reproduce it, but its cause is unresolved. The improvements below do not establish absence of regressions across all conditions. Five-platform CI is also pending resolution of signing.

### Public RC2 versus the current candidate in batchmode

All latency cells are **p50 / p95, ms**. Each variant has 50 fresh-service samples and 100 samples per warmed command/session. Service start includes `_host start`, discovery, the first CLI process and execution, with Unity already running. Timing instrumentation is off; OS caches are retained. These are not reboot-cold results. Percentiles use nearest rank.

#### Unity 6000.3.13f1

| Operation | RC2 | Candidate |
|---|---|---|
| Service start → first result | 520.25 / 543.80 | 504.48 / 526.30 |
| `instances` | 58.34 / 60.72 | 58.66 / 60.98 |
| `status` | 65.48 / 69.93 | 65.58 / 68.48 |
| `console` | 102.53 / 117.57 | 59.12 / 79.58 |
| `tools` | 105.31 / 112.00 | 58.90 / 75.63 |
| `wait-ready` | 97.71 / 120.53 | 59.12 / 79.22 |
| New-code `exec` | 91.38 / 107.46 | 73.20 / 94.10 |
| Repeated-code `exec` | 90.59 / 103.06 | 71.95 / 93.00 |
| Session `console`, after first request | 30.38 / 32.24 | 2.09 / 3.15 |

#### Unity 2021.3.19f1

| Operation | RC2 | Candidate |
|---|---|---|
| Service start → first result | 504.43 / 524.06 | 476.89 / 491.02 |
| `instances` | 58.96 / 63.59 | 57.80 / 60.62 |
| `status` | 66.01 / 71.62 | 64.60 / 68.28 |
| `console` | 102.56 / 117.58 | 58.16 / 76.33 |
| `tools` | 106.06 / 120.56 | 57.93 / 66.56 |
| `wait-ready` | 100.70 / 121.17 | 58.16 / 78.21 |
| New-code `exec` | 79.04 / 109.02 | 68.69 / 87.22 |
| Repeated-code `exec` | 75.84 / 102.17 | 67.31 / 88.07 |
| Session `console`, after first request | 28.50 / 31.66 | 2.30 / 3.24 |

Service-cold p50 improves by **3.0%** in Unity 6 and **5.5%** in Unity 2021. All five ordinary-command p95 gates pass in both Editors. `instances` and `status` retain local processing, so small differences should be treated as measurement variation. Session rows exclude process startup; they do not mean a new CLI starts in 2 ms.

### First command after Editor startup

Each variant imports its project once, then restarts it 50 times using the same Library. RC2 and candidate launches alternate. One `exec` is sent immediately after observing the ready heartbeat. The one initial import per variant is retained under `new_project` in the raw data, outside these percentiles.

| Unity | Interval | RC2 | Candidate |
|---|---|---|---|
| 6 | Editor launch → observed ready | 2959.40 / 3115.28 | 2939.82 / 3103.38 |
| 6 | Editor launch → first result | 3794.00 / 3959.99 | 3164.25 / 3351.26 |
| 6 | Observed ready → first result | 835.19 / 867.28 | 234.92 / 263.76 |
| 2021 | Editor launch → observed ready | 3439.05 / 4169.57 | 3452.15 / 3971.72 |
| 2021 | Editor launch → first result | 4102.71 / 4846.92 | 3629.63 / 4308.88 |
| 2021 | Observed ready → first result | 665.16 / 681.14 | 187.75 / 202.92 |

The Unity 6 startup ablations also have 50 restarts per variant. Disabling framework warmup still allows project-reference preparation.

| Variant | Editor launch → observed ready | Editor launch → first result | Observed ready → first result |
|---|---|---|---|
| Default | 2939.82 / 3103.38 | 3164.25 / 3351.26 | 234.92 / 263.76 |
| Early launch off | 2916.53 / 3040.18 | 3757.60 / 3892.70 | 832.66 / 890.23 |
| Framework warmup off | 2919.98 / 3020.53 | 3356.77 / 3472.78 | 436.34 / 458.30 |

Ready here is the time the driver observes the heartbeat file. Successful execution of the first command is verified separately; host liveness is not treated as Unity readiness. Preparation moves and overlaps work, rather than removing an equal amount of total computation.

### Real GUI foreground and background

| Unity | GUI | Operation | RC2 | Candidate |
|---|---|---|---|---|
| 6 | foreground | CLI console | 111.81 / 128.81 | 67.32 / 86.44 |
| 6 | foreground | New exec | 94.20 / 120.83 | 81.08 / 106.01 |
| 6 | foreground | Session console | 30.01 / 31.97 | 2.08 / 2.62 |
| 6 | background | CLI console | 126.98 / 224.11 | 126.66 / 129.51 |
| 6 | background | New exec | 107.85 / 200.26 | 99.71 / 112.26 |
| 6 | background | Session console | 106.50 / 110.55 | 107.11 / 110.16 |
| 2021 | foreground | CLI console | 110.42 / 130.08 | 67.13 / 88.60 |
| 2021 | foreground | New exec | 91.70 / 118.94 | 77.89 / 97.87 |
| 2021 | foreground | Session console | 29.85 / 33.47 | 2.09 / 3.55 |
| 2021 | background | CLI console | 110.84 / 127.43 | 67.71 / 92.19 |
| 2021 | background | New exec | 93.74 / 123.18 | 79.90 / 94.92 |
| 2021 | background | Session console | 28.49 / 32.19 | 2.11 / 3.31 |

Each operation/session has 100 samples. Actual foreground PID must match the requested state. Failed window transitions and mixed-focus attempts are retained but excluded here. Unity main-thread update cadence can dominate background latency; the batch-session 2 ms result does not transfer directly to a minimized Editor.

Editor update intervals during exec, **p95 / maximum, ms**, are below. Only intervals above 1 ms are retained; these are neither FPS nor isolated code execution time. Idle and batchmode intervals are also in the raw data.

| Unity | GUI | RC2 | Candidate |
|---|---|---|---|
| 6 | foreground | 5.79 / 21.45 | 5.77 / 7.93 |
| 6 | background | 113.39 / 116.21 | 105.79 / 112.28 |
| 2021 | foreground | 5.44 / 24.31 | 5.46 / 6.36 |
| 2021 | background | 5.60 / 22.66 | 5.55 / 7.25 |

#### Unresolved foreground latency

| Unity | Cohort | RC2 p50 / p95 | Candidate p50 / p95 |
|---|---|---|---|
| 6 | Earlier valid run | 93.89 / 121.25 | 337.13 / 419.52 |
| 6 | Uninstrumented rerun | 94.20 / 120.83 | 81.08 / 106.01 |
| 2021 | Earlier valid run | 92.77 / 110.44 | 336.73 / 395.14 |
| 2021 | Uninstrumented rerun | 91.70 / 118.94 | 77.89 / 97.87 |

Both sets contain 100 new-code samples per variant and 1,664/1,664 matching foreground observations. Slow runs are not discarded as focus errors or outliers. The later runs have no stage file instrumentation; they separately record process creation, whose p50 is about 4.9 ms in both variants. An isolated worker using the same Unity references takes about 9 ms for new code. Instrumented live GUI runs, including 20 previously unused expressions, also did not reproduce the 337 ms delay. These observations do not identify the OS, security software or a code change as the cause. Further reproduction and phase tracing remain necessary; new-code regression clearance is incomplete. Older ordinary-command gates omitted exec, so the harness now includes exec, sessions and large results in its overall gate. Historical JSON `passed: true` does not imply passing this expanded criterion.

### Large-result delivery

| Unity | Operation | RC2 p50 / p95 | Candidate p50 / p95 |
|---|---|---|---|
| 6 | large_exec | 106.15 / 123.39 | 91.81 / 120.46 |
| 6 | session_large_exec | 64.08 / 81.35 | 29.05 / 35.47 |
| 2021 | large_exec | 105.14 / 125.27 | 89.57 / 111.78 |
| 2021 | session_large_exec | 49.84 / 78.15 | 26.68 / 34.75 |

Each variant has 100 samples per operation in batchmode. Every result is compared in full: 524,288 Korean characters plus an emoji, approximately 1.5 MiB of UTF-8. This is a separate scenario, not pooled with small-result latencies. All large-result p95 checks stay within the threshold.

### Isolated effects and rejected defaults

The fast-path/connection ablations below toggle one feature in an earlier 3.12.10 candidate with base caching enabled. Each has 50 fresh-service and 100 warmed/session samples. They are not pooled with final acceptance. Values are p50 (ms).

| Variant | Cold | Console | New exec | Session |
|---|---|---|---|---|
| Earlier reference | 493.39 | 56.79 | 73.39 | 2.06 |
| Fast CLI off | 513.86 | 84.44 | 100.41 | 2.17 |
| Connection reuse off | 506.07 | 75.80 | 85.83 | 24.12 |

Forwarding snapshots raised `instances` p95 from RC2 61.38 to 80.84 ms, exceeding its 10 ms allowance. `status` tails also grew from 68.65 to 76.93 ms. Both retain local processing by default.

| Compiler only | Preparation | First compile | Total | Warmed new code |
|---|---|---|---|---|
| No base cache | 70.60 | 252.17 | 323.46 | 9.00 |
| Base cache | 70.89 | 255.17 | 326.86 | 9.36 |
| Framework warmup + base | 245.63 | 92.14 | 337.38 | 9.49 |

There are 50 first preparations and 100 new/repeated snippets; cells are p50 (ms). No generated code executes in Unity. Base caching did not improve new-code latency, so it remains opt-in. Framework preparation reduces the post-preparation request interval but not the preparation-plus-compile total. Total medians are computed from total samples, not sums of separate medians.

In the 100-sample output-conversion microbenchmark, small-result p50 changes from 0.0084 to 0.0019 ms, and a 1.5 MiB UTF-8 result from 2.6603 to 0.9740 ms. JSONL output bytes match. This isolates duplicate-conversion CPU cost, not Unity round-trip latency.

| Runtime/packager experiment | First result p50 / p95 (ms) |
|---|---|
| PyInstaller / CPython 3.12.13 | 498.56 / 517.51 |
| PyInstaller / CPython 3.14.5 | 507.19 / 544.36 |
| PyInstaller / 3.12.13 (packaging) | 496.95 / 517.74 |
| Nuitka / 3.12.13 | 452.86 / 466.57 |

These experiments use the same earlier source with snapshot forwarding/base caching enabled and the same Roslyn worker, separately from final 3.12.10 acceptance. Python 3.14 did not improve first startup here. Nuitka improved first-result p50 by 8.9%, below the 10% gate. Its warmed console changed from 57.50 to 38.60 ms and new exec from 70.52 to 53.24 ms, but the default packaging is unchanged. The real installer also safely rejects the flat experimental Nuitka layout.

### Resources and validation scope

| Unity | Working set (bytes) | RC2 | Candidate | Change |
|---|---|---|---|---|
| 6 | Host + worker | 260,292,608 | 263,520,256 | +1.24% |
| 6 | Unity | 470,945,792 | 464,658,432 | -1.34% |
| 2021 | Host + worker | 243,261,440 | 247,132,160 | +1.59% |
| 2021 | Unity | 321,134,592 | 320,512,000 | -0.19% |

| Large-result workload | RC2 host + worker bytes | Candidate host + worker bytes | Change |
|---|---|---|---|
| 6 | 698,908,672 | 711,376,896 | +1.78% |
| 2021 | 684,294,144 | 694,558,720 | +1.50% |

In the large-result scenario, both hosts retain completed request results and reach about 476–479 MB. This reflects the existing completed-job retention policy; these are not peak-memory measurements. Both normal and large-result scenarios remain within the relative +10% budget.

Installed size changes from **135,202,789 to 135,226,276 bytes (+0.017%)**. These working-set/size samples remain within the +10% budget. Memory is an end-of-workload snapshot, not peak use or a large-project upper bound. Exactly one compiler child was observed, with no additional workers. The final ZIP is 58,165,086 bytes; packaging with an already published worker took 10.99 seconds.

The first Nuitka build took 60.82 seconds including C compiler download; a cached rebuild took 16.68 seconds. The original public RC2 build duration is unknown. These are not equivalent clean-environment build-time comparisons.

Python tests: **212 passed, one privilege-dependent symlink test skipped**. Compiler tests: **18 passed**. The final executable passes **19 live checks each in Unity 2021 and 6**, covering large Unicode/emoji results, static isolation, reference changes, reloads, concurrent control, expiry and lost-response non-replay. The real Windows installer passes fresh install, reinstall, public-RC2 upgrade and registered-path host relaunch; only downloads are substituted with local files and user PATH is untouched.

**Five-platform CI is not complete.** The validation commit failed at GPG pinentry under the existing global `commit.gpgsign=true` setting. Signing was not bypassed; Linux/macOS execution or distribution validation of the new code is not claimed. After resolving signing, dispatch the workflow on this branch with an empty `release_tag` to validate all five artifacts without publishing a release.

The instrumented run is in `accepted-timing.json`, per-process JSONL and `timing-summary.json`. It separates CLI process startup, Python entry/import, host readiness, reference negotiation, compiler request, Unity queue/execution and serialization/delivery. These few diagnostic samples include file-I/O overhead and are excluded from adoption gates. Compiler intervals also include IPC/reference validation; overlapping phases must not be summed.

An additional 21 fast-call tests pass against the packaged Windows executable. This is separate packaging validation, not an increase in the source-test count.

### Additional primary references

- [Nuitka runtime detection](https://nuitka.net/user-documentation/tips.html#detecting-nuitka-compilation-at-runtime): runtime detection also checks the module-level `__compiled__` marker instead of relying only on `sys.frozen`.
- [PyInstaller operating modes](https://pyinstaller.org/en/stable/operating-mode.html): the existing onedir installation is retained; this is not a comparison against per-run onefile extraction.
- [Python 3.14 changes](https://docs.python.org/3.14/whatsnew/3.14.html): the experiment uses the standard GIL build, without adopting free-threading or experimental JIT. The measured version is fixed at 3.14.5.
