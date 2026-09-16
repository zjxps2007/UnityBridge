# Follow-up host optimization — 2026-09-17

Baseline: `1749359`. Candidate: `5a49f00` on `codex/external-host-compiler`, both `0.3.0-alpha.1`, unreleased. This comparison measures the development branch before and after this change. The earlier stable v0.2.3 comparison remains in [its original report](HOST_VALIDATION.md). Main and release tags were not changed.

## Changes and preserved behavior

- HTTP acceptance, request reads and response writes no longer resume through Unity's update loop. Tool invocation and result serialization still run on the main thread, including user result getters. Connector dispatch awaits keep Unity's synchronization context.
- Requests retain their originating listener's cancellation token. Validation checks it before dispatch and again after the execution lock. Stopping/replacing the listener cannot authorize its waiting mutation later; already running user code is not interrupted.
- `PreparedContext` computes the normalized project path and reference digest once per negotiated context. Domain/reference changes replace it. Existing projects no longer allocate an unused queue/condition on every discovery scan.
- `MetadataReferenceCache` owns reference loading/MVID validation; `BoundedCache` owns retention. A cache miss reads one image for validation and Roslyn. Every hit still checks the actual DLL MVID, including replacements with unchanged timestamps. Execution results, static state and loaded assemblies are not cached.
- Worker timeout cleanup joins an already-started watchdog before releasing the worker lock. A deterministic regression test reproduced the old race.
- Legacy commands use one direct loopback HTTP connection, avoiding generic HTTPS/certificate setup. They preserve success/error/plain-text/empty-response behavior. Environment proxies and redirects are deliberately not followed; response loss never triggers replay.

## Verification

- Local Python: 166 passed, one existing Windows symlink-privilege skip (167 total). Real Roslyn: 13/13 passed.
- Packaged CLI with Unity 2021.3.19f1 and 6000.3.13f1: 14/14 native checks each. Includes async tool/result getter main-thread access, listener restart with a mutation waiting behind the execution lock, stale host PID recovery, reload, static isolation, reference invalidation, deadlines, live controls, compile error recovery and play/pause state.
- Actual Windows bundle fresh install and v0.2.3 upgrade passed in isolated custom paths; bundled worker launch, previous runtime retention and unchanged user PATH were verified.
- [Five platform CI builds and regression suites passed](https://github.com/zjxps2007/UnityBridge/actions/runs/35123845115) at `5a49f00`. Windows x64, Linux x64/ARM64, macOS Intel/Apple Silicon; release publication skipped.

## Matched process-to-response latency

Both builds used Python 3.14.4/PyInstaller 6.22.3 on Windows 11. Both used the host backend, fresh empty Unity projects, and baseline/candidate/candidate/baseline order. Ordinary commands: 80 samples per build/version; unique/repeated exec: 40 each. Milliseconds use nearest-rank p50/p95. Timing starts at CLI subprocess launch and ends at its completed JSON response. These are batch-mode measurements, not GUI frame rates or prompt-to-answer latency; the desktop was not dedicated or CPU-pinned.

| Unity | Command | Before p50 / p95 (ms) | After p50 / p95 (ms) |
|---|---|---:|---:|
| 6000.3.13f1 | `status` | 83.5 / 85.9 | 82.7 / 86.8 |
| 6000.3.13f1 | `console` | 217.0 / 266.6 | 104.7 / 121.4 |
| 6000.3.13f1 | `tools` | 250.0 / 250.9 | 109.1 / 125.4 |
| 6000.3.13f1 | `unique_exec` | 249.9 / 251.4 | 124.0 / 139.0 |
| 6000.3.13f1 | `repeat_exec` | 250.2 / 251.2 | 124.5 / 142.3 |
| 2021.3.19f1 | `status` | 84.0 / 90.7 | 83.4 / 91.0 |
| 2021.3.19f1 | `console` | 216.3 / 264.8 | 104.6 / 119.5 |
| 2021.3.19f1 | `tools` | 250.2 / 251.7 | 109.1 / 124.9 |
| 2021.3.19f1 | `unique_exec` | 249.9 / 250.9 | 121.8 / 143.0 |
| 2021.3.19f1 | `repeat_exec` | 250.0 / 251.3 | 110.2 / 125.9 |

All six ordinary-command p95 gates passed: an increase must stay within `max(5% of baseline, 10 ms)`. `status` remains predominantly local file/process startup work; this result does not claim a material status speedup.

## First result and resources

Only two runs per entry: the ranges below are not reliable startup percentiles. Cold service timing includes host launch, context negotiation and the first user result after Unity is ready. It excludes installation, Unity startup, reboot and disk-cache flushing. Prewarm-only uses a restarted worker after its harmless automatic reference preparation, before any user snippet.

| Unity | Cold before / after (ms) | Prewarm-only first exec before / after (ms) |
|---|---:|---:|
| 6000.3.13f1 | 1060–1651 / 827–847 | 239–276 / 136–142 |
| 2021.3.19f1 | 1021–1029 / 758–769 | 253–285 / 112–125 |

| Unity | Exec max Editor gap before / after (ms) | Host RSS before / after (MiB) | Worker RSS before / after (MiB) |
|---|---:|---:|---:|
| 6000.3.13f1 | 8.4 / 6.1 | 33.3–33.4 / 32.4–32.8 | 219.8–220.0 / 207.9–208.6 |
| 2021.3.19f1 | 6.5 / 6.9 | 32.9–33.0 / 32.1–32.5 | 207.7–207.9 / 179.0–179.3 |

Editor gaps record update intervals above 1 ms over the whole exec workload; they are not GUI frame times. RSS ranges are post-workload resident snapshots, not peaks/private memory. Reference count and project workloads affect them. Uncompressed local Windows bundle: 113.2 → 113.2 MiB; candidate ZIP: 50.1 MiB.

A separate reference-loader component check used 174 .NET reference DLLs (63.2 MiB), an empty metadata cache and warm OS file cache, 20 alternating samples per variant. Median loading time was 28.19 → 17.69 ms and per-thread allocated bytes 191.87 → 127.37 MiB. This excludes compilation and Unity; it is not an additional end-to-end speedup to add to the table.

## Scope and reproduction

Native checks cover these two Windows Editors. Linux/macOS are validated through CI, not native Unity execution. Unity 2020.3 remains source/API compatibility evidence only. No claim is made about every project, OS, GUI focus state or cold disk cache. Existing source edits still require Unity compilation/reload.

Use the [native test guide](../tests/unity/README.md), adding `--baseline-host --baseline-ref 1749359` to `scripts/benchmark-host.py` with the saved matching baseline executable. [Machine-readable evidence](HOST_OPTIMIZATION_BENCHMARK.json) contains every timing sample, gates, resources, native checks and bundle hash. Detailed local logs are under `.codex-deps/host-optimization/`.
