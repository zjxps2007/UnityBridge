# Python performance evidence / Python 성능 원자료

[한국어 보고서](../../PYTHON_STARTUP.ko.md) · [English report](../../PYTHON_STARTUP.md)

`manifest.json` records the machine, public RC2 baseline, runtime/worker hashes,
file checksums, and CI status. Repository paths in JSON are replaced with
`<repo>`. Launcher/host registries, authentication tokens, Unity license logs,
and generated executable bundles are not published here.

`manifest.json`에 측정 장비, 공개 RC2 기준, 런타임·워커 해시, 각 파일의 체크섬과
CI 상태를 기록합니다. JSON의 저장소 경로는 `<repo>`로 바꿨습니다.
호스트 등록 파일·인증 토큰·Unity 라이선스 로그·생성한 실행 파일은 포함하지 않습니다.

| Files | Meaning / 의미 |
|---|---|
| `accepted6.json`, `accepted2021.json` | Final default vs public RC2; official CPython 3.12.10, base cache off, first-negotiation race fixed. 최종 기본값과 공개 RC2 비교 |
| `accepted-gui-*.json` | Current binary in a real GUI. The two `foreground-verified` files contain a valid new-code regression, not a full acceptance pass. 전경 새 코드 지연 결과를 포함 |
| `diagnostic-gui-*-uninstrumented.json` | Later 100-sample foreground reruns of the identical binary. All expanded gates pass; the earlier slow cohorts remain unresolved. 동일 바이너리 재측정이며 이전 느린 결과의 원인이 해결된 것은 아님 |
| `diagnostic-gui6.json`, `diagnostic-gui6-novel.json`, `diagnostic-gui-worker.json` | Short diagnostic runs, including unused expressions and isolated worker compilation. Not acceptance samples. 원인 탐색용으로 성능 승인 표본과 구분 |
| `accepted-large*.json` | 100 CLI and 100 session responses per variant, each about 1.5 MiB of Korean text plus emoji; contents checked in full |
| `accepted-startup*.json` | Unity started with the launcher registered; first import separated from 50 reused-project starts. `smoke` has only two starts per variant and is excluded from final percentiles. Unity 시작과 첫 명령을 별도 측정 |
| `accepted-native*.json` | Current Connector and packaged CLI functional checks; diagnostics enabled to coordinate real compiler overlap. 기능 검증이며 성능 판정에 사용하지 않음 |
| `accepted-install.json` | Real installer and binaries with offline downloads, isolated paths and no user PATH changes. 실제 신규·업그레이드 설치 검증 |
| `selected*.json` | Earlier base-cache-off candidate before the initial-negotiation fix. `selected-startup6` exposed a first-request rejection; superseded by `accepted*`. 초기 협상 경쟁 상태 수정 전 후보 |
| `final6.json`, `final2021.json` | Earlier candidate with base Compilation caching on; superseded for final acceptance. 캐시 채택 판정 이전 후보 |
| `ablation-*.json` | One feature toggled in that earlier 3.12.10 candidate. 같은 후보에서 기능별 효과를 분리 |
| `preparation.json` | Compiler-only base/no-base/framework-prewarm experiment; no generated code executed. 계산량과 사전 준비 이후 대기 시간을 구분 |
| `session-output.json` | Duplicate JSON conversion removed; small and 1.5 MiB UTF-8 outputs. CLI/Unity 왕복과 구분하는 구성 요소 실험 |
| `runtime.json` | Controlled 3.12.13 vs 3.14.5 PyInstaller builds. Earlier all-fast source with base caching on |
| `packaging.json` | Same 3.12.13/source/worker, PyInstaller vs Nuitka. Earlier all-fast source with base caching on |
| `build-*.json`, `controlled-source.*` | Build metadata and the source snapshot for runtime/packager experiments. 빌드·소스 근거 |
| `accepted-timing.json`, `timing-*.jsonl`, `timing-summary.json` | Instrumented diagnostic run, excluded from performance gates. 구간별 계측 전용 |
| `validation.json`, `attempts.json` | Validation inventory and incomplete/rejected attempts. 검증 범위와 실패·제외 사유 |
| `initial-*.json` | Initial 3.12.13 all-fast experiments, including rejected snapshot tails. `initial-bench6` candidate is incomplete after a harness cleanup failure |
| Other `gui-*`, `controlled-gui-*`, `final-native*`, `robust-native*`, `bundle-install*` | Retained earlier attempts. Some GUI runs mixed focus or stopped at focus setup; native timing assumed a 100 ms compile; installer check originally assumed synchronous host start. Inspect `passed`, errors and sample counts; do not treat these as final acceptance |

Every normal performance run leaves stage timing off, retains OS file caches and
uses owned disposable projects. It is not a reboot-cold benchmark. A process's
working set is a sample at the end of its workload, not peak memory.

`selected-source.patch` contains the accepted production changes relative to
the manifest's base commit. `controlled-source.patch` is the earlier source
used for the runtime/packager experiments. Evidence JSON, JSONL and patch files
have Git text conversion disabled so their checksums survive Windows checkouts.

일반 성능 측정에서는 계측을 끄고 OS 파일 캐시를 유지하며 별도 테스트 프로젝트를
사용했습니다. 재부팅 직후 결과가 아닙니다. Working set은 작업 후 한 시점의
메모리이며 최대 사용량이 아닙니다. 실패·불완전·전경 상태가 섞인 실행은 원인과
함께 보존하되 최종 채택 수치에 합산하지 않습니다.

The valid slow foreground cohorts are **not excluded as outliers**. Their older
`passed` field only applies the five ordinary-command gates; it does not check
exec. The current harness also gates exec, sessions and large results. Final
performance acceptance remains on hold despite passing reruns; read
`validation.json` and both language reports for the unresolved issue and CI status.

전경 새 코드가 느렸던 유효 표본은 이상치로 제외하지 않습니다. 당시 JSON의
`passed`는 일반 명령 다섯 개만 판정했습니다. 현재 측정기는 exec·세션·큰 결과도
판정하며, 후속 재측정 통과만으로 이전 지연을 해결했다고 처리하지 않습니다.

The tools are `scripts/benchmark-host.py`, `scripts/benchmark-preparation.py`,
`scripts/benchmark-output.py`, `scripts/verify-host.py` and
`scripts/verify-windows-bundle.py`. JSON benchmark configurations preserve their
arguments. Reconstruct `<repo>` with the checkout's absolute path and use a new
output directory. Compiler contexts additionally require their original Unity
reference DLLs and matching MVIDs; never replace identity verification with a
path-only cache to replay a benchmark.
