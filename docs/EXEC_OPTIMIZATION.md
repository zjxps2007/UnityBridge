# Single-exec optimization while keeping Python

[한국어](EXEC_OPTIMIZATION.ko.md) | English

These changes are included in **v0.3.0-rc.2** on `codex/external-host-compiler`.
The CLI and host remain Python, and the existing Roslyn compiler remains C#.
Measurements below predate the RC2 version bump; raw evidence preserves the
original `0.3.0-rc.1` development versions and hashes.

## Change and baseline

When a compatible host is already running, the short-lived caller forwards exec
without loading the full parser, client and adapter. The resident Python host
uses the existing parser, output, discovery and per-project FIFO execution queue.
The connection to numeric loopback also avoids unnecessary hostname processing.
Command syntax, Python APIs, compilation and actual Unity execution are retained.
Standalone standard streams use UTF-8, including Windows pipes carrying Korean
text and emoji.

The baseline is the **working-branch bundle immediately before this change**,
not the published RC1. It already includes the [previous improvements](SPEED_FOLLOWUP.md):
lazy loading, ReadyToRun, shared-reference cache accounting and JSONL sessions.
All 220 compiler files have identical SHA-256 hashes in the two bundles, and both
use identical current Connector sources. Previous compiler improvements are not
counted again as gains from this Python route.

## Prepared-call measurements

Measured on 2026-09-18, Windows 11, Python 3.14.4 / PyInstaller 6.20.0. Each Unity
version ran fresh empty projects in baseline/candidate/candidate/baseline order.
Every command and each exec category has 80 samples per variant. Timing starts
before launching a separate CLI process and ends when its response is received,
after host/compiler preparation. Values are milliseconds; percentiles use
nearest-rank selection.

| Unity | Exec category | Before p50 / p95 | After p50 / p95 | p50 reduction |
|---|---|---:|---:|---:|
| 2021.3.19f1 | Distinct source | 109.9 / 140.4 | 91.4 / 110.5 | 16.8% |
| 2021.3.19f1 | Repeated source | 109.0 / 141.7 | 78.6 / 109.9 | 27.9% |
| 6000.3.13f1 | Distinct source | 122.4 / 141.0 | 93.1 / 110.5 | 24.0% |
| 6000.3.13f1 | Repeated source | 111.8 / 141.7 | 93.0 / 111.1 | 16.8% |

Exec p95 fell about 30–32 ms, or 21–23%. This does not imply proportional gains
for complex C# compilation or Unity work. Every call still emits a fresh assembly
identity and executes again; neither results nor static state are reused.

| Ordinary command | Unity 2021 p95: before → after | Unity 6 p95: before → after |
|---|---:|---:|
| status | 70.6 → 73.2 | 71.7 → 72.1 |
| console | 124.4 → 118.9 | 120.2 → 119.1 |
| tools | 125.1 → 125.3 | 119.5 → 125.2 |

Both versions pass the allowed p95 increase of `max(5% of baseline, 10 ms)`.
This is not a claim that every command improved. An initial ten-sample pilot
exceeded the tools limit; that evidence is retained. The table uses the larger,
counterbalanced run of the final executable.

## First use and costs

| Unity | Service start to first result: before → after | First exec after prewarm only: before → after |
|---|---:|---:|
| 2021.3.19f1 | 500.2–504.2 → 506.0–509.8 | 115.6–116.1 → 88.9–102.5 |
| 6000.3.13f1 | 557.5–559.0 → 578.2–581.2 | 110.3–111.2 → 91.7–113.7 |

These first-use cases have only two samples each, so ranges replace percentile
claims. **No improvement was established when the service also needs to start.**
Processes were fresh, but OS file caches were not purged; these are not
post-installation or post-reboot measurements.

Installed size increased from 129.24 to 129.26 MiB, approximately 22 KiB.
Host working set changed from 33.92 to 34.05–34.57 MiB on Unity 2021, and from
33.54–34.18 to 34.39–34.50 MiB on Unity 6. These are two observations per variant,
not peak-memory measurements. No new language runtime or compiler files are added.

During exec, p95 of Editor update intervals exceeding 1 ms changed from 5.68 to
6.24 ms on Unity 2021 and from 5.34 to 5.18 ms on Unity 6. Maxima increased from
6.46 to 12.75 ms and from 6.64 to 12.88 ms, respectively. These batchmode/nographics
observations do not establish smoother GUI frames or reduced stalls.

## Correctness and validation

- Authentication, ordering, the original deadline, and Unity's expiry check after
  acquiring its execution lock are retained.
- Ineligible fast calls fall back before sending. After a frame-write attempt,
  a missing response is `unknown`; the command is never replayed on another route.
- Automatic-update code, timing and network behavior are preserved. Ordinary
  text calls with a due check run through the normal CLI. Both benchmark variants
  suppress update checks equally.
- Python: 195 passed out of 196, with one Windows symlink-permission skip. POSIX
  installer tests passed with an accessible workspace temporary directory.
- All 14 fast-route tests pass in source, packaged Windows, and newly extracted
  ZIP modes, covering
  file/stdin/Unicode, authentication, expiry, lost responses, concurrent output,
  older hosts and update scheduling.
- Native Unity 2021 and Unity 6: 18/18 each, including fresh static state, compiler
  error recovery, reference changes, reloads and no late side effects after expiry.
- The five-platform CI now tests the fast route in each extracted executable.
  Linux/macOS CI and a release were not run as part of this work.

Large projects, foreground/background GUI behavior, post-reboot startup,
long-running assembly accumulation, agent-prompt-to-screen latency and token use
are outside this measurement scope.

[Raw measurements, gates, source and executable hashes](EXEC_OPTIMIZATION_BENCHMARK.json)
are retained. Reproduce with both saved bundles and `scripts/benchmark-host.py
--baseline-host --baseline-working-tree-connector --baseline-ref 5945c3b
--samples 40 --exec-samples 40`. `UNITY_BRIDGE_DISABLE_FAST_EXEC=1` disables the
fast route in the current executable for diagnosis. See the [development guide](DEVELOPMENT.md)
for builds and functional verification.
