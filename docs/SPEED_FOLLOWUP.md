# Speed follow-up after RC1

[한국어](SPEED_FOLLOWUP.ko.md) | English

These changes are included in **v0.3.0-rc.2**. Measurements were collected before
the RC2 version bump on `codex/external-host-compiler`, after `5945c3b`
(`v0.3.0-rc.1`); raw evidence retains those original versions and hashes.
Automatic update code, schedule, synchronous network behavior, and
installation/update destinations are unchanged.

## What changed

- CLI: lazy public exports and optional imports; build/cache the selected command parser.
- Host: authenticated, coalesced state-change hints wake discovery immediately, with periodic fallback and authoritative file validation before using a changed port.
- Completion: bounded operation receipts survive domain reload. Refresh, reserialize, play and stop confirm their own completion. Unknown/cancelled receipts never replay the action. Ambiguous code imports retain conservative waiting. Read-only probes have a one-second maximum, retry transient reload rejections, and rediscover the target within the original wait deadline.
- Worker: ReadyToRun publishing reduces initial compiler JIT work; `--no-ready-to-run` remains available for comparison.
- Repeated calls: optional JSONL `session` reuses one CLI process, while each request rediscovers Unity and executes separately.
- Cache: compilation entries count a shared metadata allocation once, with separate weights for per-source data. Reloaded images with the same path/MVID are counted separately if older compilations still retain earlier bytes. Every MVID is still validated, and each exec emits a fresh identity.

## Matched measurements

Windows, Python 3.14.4 / PyInstaller 6.20.0, .NET SDK 10.0.401 and Roslyn 5.0.0.
Both variants use the external host. Each Unity version ran fresh empty projects
in baseline/candidate/candidate/baseline order. Normal commands have 80 samples,
each exec category 40, and waited no-op refresh 16 per variant. Percentiles use
nearest rank. All values below are milliseconds; **lower is better**.

| Command | Unity 2021: RC1 → candidate (p50 / p95) | Unity 6: RC1 → candidate (p50 / p95) |
|---|---:|---:|
| status | 86.7 / 90.7 → 68.0 / 71.3 | 86.7 / 89.5 → 68.1 / 70.7 |
| console | 106.8 / 121.8 → 103.6 / 119.9 | 109.8 / 120.1 → 103.2 / 119.8 |
| tools | 109.2 / 124.9 → 109.2 / 112.9 | 109.9 / 125.0 → 108.9 / 123.2 |
| exec: unique | 124.2 / 143.2 → 110.7 / 139.9 | 125.5 / 142.9 → 116.7 / 142.0 |
| exec: repeated | 123.0 / 140.1 → 109.4 / 141.6 | 123.0 / 141.1 → 118.1 / 140.6 |
| refresh --wait: no changes | 1614.3 / 1628.1 → 155.9 / 529.8 | 1617.9 / 1627.7 → 143.4 / 181.8 |

The status/console/tools p95 gates all passed on both Editors: allowed degradation
is `max(5% of baseline p95, 10 ms)`. This does not mean every individual sample or
every exec percentile improved. No-op refresh measures completion overhead, not
the duration of a large asset import or script compilation.

## Persistent sessions and first execution

| Unity | New process console p50 / p95 | Session console p50 / p95 | First session command, two samples |
|---|---:|---:|---:|
| 2021.3.19f1 | 103.6 / 119.9 | 15.9 / 31.6 | 97.3–126.7 |
| 6000.3.13f1 | 103.2 / 119.8 | 16.8 / 31.9 | 99.7–113.6 |

Session timings exclude process initialization after the first command (40
samples per Editor). This benefit requires keeping `session` open; launching a
normal CLI command every time does not get it. The new command uses the existing
JSON-output update-notice exemption; automatic updates were not moved elsewhere.

| Unity | RC1 service start to first exec result | Candidate |
|---|---:|---:|
| 2021.3.19f1 | 776.3–782.9 | 497.5–501.9 |
| 6000.3.13f1 | 855.6–867.0 | 545.5–602.2 |

Cold-service results have only **two observations per variant**. Ranges are shown
instead of treating them as reliable p95 estimates. They are fresh process starts
on a running OS, not first launch after installation or reboot. Compiler prewarming
is not awaited before issuing the first request in this measurement; prepared command
results and prewarm-only first calls are retained separately in the raw data.

## Compiler startup, cache and costs

An independent alternating comparison used the **same final compiler source**,
12 fresh JIT workers and 12 ReadyToRun workers, with a saved Unity 6 reference set.
Process start plus first compilation p50 was **586.9 → 314.2 ms**.
First compilation after ping was **516.0 → 245.8 ms**;
the next compilation was **12.4 → 12.5 ms**.
These are compiler-component timings, without Unity execution. The first JIT
sample was an outlier; raw observations are retained. ReadyToRun reduces JIT
startup work while increasing code size; it is not Native AOT and still needs the
bundled .NET runtime. See [Microsoft's ReadyToRun documentation](https://learn.microsoft.com/en-us/dotnet/core/deploying/ready-to-run).

With eight rotating snippets, second-pass cache hits were **0/16 → 16/16** on
each Editor. This demonstrates retained preparation rather than cached execution:
static counters still start at 1 on every call. Source/metadata estimates retain
the 64-compilation and 256 MiB accounting limits; those limits are not RSS caps.

Windows installed size: **113.2 → 129.2 MiB**;
ZIP size: **50.1 → 57.8 MiB**. Installation still
extracts the bundle once. Post-run working sets (two snapshots per variant):

| Unity | Process | RC1 MiB | Candidate MiB |
|---|---|---:|---:|
| 2021.3.19f1 | Unity | 296.6–297.6 | 297.4–303.0 |
| 2021.3.19f1 | Host | 33.9–33.9 | 34.0–34.0 |
| 2021.3.19f1 | Compiler | 194.8–196.7 | 199.0–199.4 |
| 6000.3.13f1 | Unity | 433.8–441.6 | 433.9–440.0 |
| 6000.3.13f1 | Host | 34.0–34.1 | 34.1–34.2 |
| 6000.3.13f1 | Compiler | 209.3–213.9 | 212.9–214.2 |

Editor update-gap p95 during exec: unity6: 5.36 → 5.32 ms; unity2021: 6.11 → 6.04 ms.
Only gaps above 1 ms are recorded. These observations do not measure GUI frame
time, peak memory, or long-lived assembly accumulation. Keeping more compiler
preparation and R2R code can increase worker memory. Worker eviction cannot unload
assemblies already loaded into Unity.

## Verification and scope

- Python: 182 tests, 181 passed and one Windows symlink-privilege skip.
- Compiler: 15 regression scenarios passed, including reference replacement,
  separate reloaded-image accounting, cache eviction and fresh assembly identities.
- Extracted Windows ZIP: bundled compiler ping and two sequential JSONL requests passed.
- Packaged native checks: 16/16 on Unity 2021.3.19f1 and 16/16 on 6000.3.13f1.
  They include no-change explicit compilation, operation receipts through a real
  reload, waited play/stop, session requests, authentication, listener replacement,
  deadline rejection, static isolation and compiler failure recovery.
- Validation exposed a read stuck on the old listener and a transient rejection
  during reload; bounded read retries fixed both. Mutations remain single-dispatch.
- The five-platform release matrix now smoke-tests JSONL sessions and builds R2R
  workers. Linux/macOS builds were not run locally or published in this task.
- Native Unity 2020.3, large projects, GUI/background-window behavior, first boot,
  and agent prompt-to-answer time remain unmeasured. Update checks were disabled
  equally for all timing runs; their network latency is outside these results.

[Raw samples, gates and source hashes](SPEED_FOLLOWUP_BENCHMARK.json) identify the
tested working tree. Reproduce with `scripts/benchmark-host.py --baseline-ref
5945c3b --baseline-host --extended` and matching baseline/candidate binaries, then
use `scripts/verify-host.py` for functional checks. `scripts/benchmark-worker.py`
accepts its saved `compiler-context.json`, `--jit`, `--r2r` and an unused output
file; its reference DLLs must still exist. See [native test instructions](../tests/unity/README.md).
