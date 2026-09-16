# External host validation — 2026-09-17

Candidate: `048bf8e` on `codex/external-host-compiler`, version `0.3.0-alpha.1` (unreleased).
Baseline: stable `v0.2.3`, commit `7524c07`. The feature branch has not been merged into main.

## Functional and distribution checks

- Local Python suite: 155 tests, 154 passed and one Windows directory-symlink privilege skip.
- Real Roslyn compiler suite: 11 cases passed, including diagnostics, MVID invalidation, fresh identities and cache behavior.
- Unity 2021.3.19f1 and 6000.3.13f1: 12 native checks each passed. Covered authentication, external compilation, repeated static-state isolation, deadlines after the execution lock, live controls, reference changes, real domain reload and play/pause state.
- Packaged Windows CLI in a path containing spaces: 12 Unity 6 checks passed, including automatic standalone host launch despite a stale registry PID.
- Two real Unity versions shared one host. Per-project execution/control checks passed; terminating its compiler child recovered on the next request without restarting Unity or the host. After both Editors closed, the host exited after 29.84 seconds.
- Real Windows bundle: fresh installation and upgrade from v0.2.3 passed in isolated custom paths. Previous runtime contents and user PATH were preserved. Installer fixtures cover rollback and failed worker checks on Windows and POSIX.
- [All five artifact-only CI jobs passed](https://github.com/zjxps2007/UnityBridge/actions/runs/35120162054): Windows x64, Linux x64/ARM64 and macOS Intel/Apple Silicon. Release publication was skipped.
- Unity 2020.3: official API/source compatibility audit and C# 8 syntax checks only; no actual 2020.3 Editor was available. See [compatibility evidence](UNITY2020_COMPATIBILITY.md).

## Matched response-time results

Windows 11, Python 3.14.4 and PyInstaller 6.22.3 for both local standalone builds; .NET SDK 10.0.401/Roslyn 5.0.0 for the candidate worker. Each Unity version used fresh disposable projects in baseline/candidate/candidate/baseline order. Candidate commands explicitly selected the host route. The shared desktop was not isolated with CPU affinity or a dedicated benchmark environment.

Latency runs from CLI subprocess launch to completed JSON response. Ordinary commands have 80 samples per variant/version; unique and repeated snippets have 40 each. Values below are milliseconds, using nearest-rank percentiles. These are empty-project batch-mode results, not GUI background behavior, game frame rates or prompt-to-answer latency.

| Unity | Command | v0.2.3 p50 / p95 | Host p50 / p95 |
|---|---|---:|---:|
| 6000.3.13f1 | `status` | 82.3 / 89.8 | 83.1 / 86.9 |
| 6000.3.13f1 | `console` | 217.9 / 267.6 | 217.1 / 266.3 |
| 6000.3.13f1 | `tools` | 250.3 / 251.4 | 250.1 / 251.3 |
| 6000.3.13f1 | `unique_exec` | 838.3 / 860.3 | 250.1 / 251.2 |
| 6000.3.13f1 | `repeat_exec` | 838.6 / 849.9 | 249.9 / 251.6 |
| 2021.3.19f1 | `status` | 82.8 / 87.9 | 83.3 / 85.8 |
| 2021.3.19f1 | `console` | 217.9 / 268.0 | 216.9 / 265.9 |
| 2021.3.19f1 | `tools` | 250.3 / 251.3 | 250.2 / 251.0 |
| 2021.3.19f1 | `unique_exec` | 713.1 / 733.4 | 250.0 / 251.1 |
| 2021.3.19f1 | `repeat_exec` | 713.2 / 724.9 | 249.9 / 251.1 |

All six ordinary-command p95 gates passed: candidate may exceed baseline by no more than `max(5% of baseline, 10 ms)`. The automatic host route is retained for compatible, registered installations; unregistered and older installations keep the direct route.

## Cold service and automatic prewarm

Each entry below is the range of only two runs, not a reliable startup percentile. The cold measurement starts with Unity ready and includes host process launch, context negotiation and the first result. It excludes installation/registration, Unity startup and OS disk-cache flushing. For prewarm-only measurements the host/worker is restarted, completes its harmless automatic `return null;` preparation, and then receives its first user snippet. The baseline comparison runs a new snippet with the legacy per-call compiler process.

| Unity | Cold v0.2.3 | Cold host | After prewarm: v0.2.3 / host |
|---|---:|---:|---:|
| 6000.3.13f1 | 935–941 ms | 1068–1114 ms | 840–843 ms / 219–267 ms |
| 2021.3.19f1 | 746–754 ms | 1012–1026 ms | 708–720 ms / 231–249 ms |

## Editor responsiveness and resource costs

The audit recorded every Editor update interval above 1 ms across the full exec run. Maximum gaps show main-thread stalls in this fixture; the distribution is conditioned on gaps above 1 ms and is not a GUI frame-time distribution.

| Unity | Maximum Editor gap: v0.2.3 / host | Editor RSS: v0.2.3 / host | Host RSS | Compiler RSS |
|---|---:|---:|---:|---:|
| 6000.3.13f1 | 744.6 / 12.6 ms | 435.3 / 432.0 MiB | 33.3 MiB | 220.2 MiB |
| 2021.3.19f1 | 598.1 / 21.5 ms | 290.3 / 294.8 MiB | 32.7 MiB | 208.0 MiB |

Windows uncompressed local installation: **20.4 → 113.2 MiB**. Worker and host working sets are resident snapshots after the workload, not peaks or private memory; shared pages make their sum an approximation. More projects/references can increase memory. Loaded snippet assemblies remain until Unity domain unload, as with legacy execution.

Compressed Windows local ZIP: 9.4 → 50.1 MiB. Public CI artifacts use Python 3.12 and can differ in size; the timing comparison deliberately used the same Python 3.14 build environment on both sides.

## Limitations and reproducibility

- Ordinary-command gates cover these two Windows batch-mode environments. Native Unity execution on Linux/macOS and Unity 2020.3 remains unmeasured; platform CI checks the package, worker and regression suites.
- Keep a short Windows installation path. Deep validation directories hit native executable/DLL path-length limits; successful custom-path checks retained spaces while shortening the parent path.
- Project source edits still need Unity compilation/domain reload. Already executing arbitrary Unity C# cannot be force-cancelled.
- Earlier runs found unnecessary per-request HTTPS context construction and failed the tools p95 gate. The final loopback transport uses fixed HTTPConnection endpoints, and the results above supersede those earlier runs. CI also exposed temporary-directory aliases; canonical path comparison fixed them.
- Reproduce with `scripts/benchmark-host.py` and `scripts/verify-host.py`; commands and scope are in [the native test guide](../tests/unity/README.md). [Machine-readable summary](HOST_BENCHMARK.json) preserves sample counts and gate thresholds. Detailed local logs remain under `.codex-deps/external-host-compiler/`.
