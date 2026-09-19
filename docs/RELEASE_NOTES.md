# UnityBridge v0.3.0-rc.3 — prerelease

RC3 starts the Python host and compiler preparation earlier, reduces ordinary
CLI startup work, and improves repeated session requests. It is published from
`codex/external-host-compiler`. The latest stable release remains
[v0.2.3](https://github.com/zjxps2007/UnityBridge/releases/tag/v0.2.3).

CLI, Python source and Unity Connector versions are **0.3.0-rc.3**. Python package
metadata may use the equivalent normalized version `0.3.0rc3`.

## Changes since RC2

- Start external host preparation asynchronously during Connector initialization.
  Skip asset import workers and keep Unity reference collection and execution
  behind live readiness checks. Overlap imports with compiler startup and framework
  preparation; preparation code is never executed in Unity.
- Extend the lightweight `exec` route to eligible `console`, `tools` and
  `wait-ready` calls, reusing the host's parser and handlers. Unsupported syntax
  and older hosts select the compatible path before dispatch. Preserve CLI output,
  exit codes, project/port selection, file/stdin input and compiler overrides.
- Pass structured results directly to JSONL sessions and serialize once. Reuse
  bounded HTTP connections with separate execution, control and negotiation lanes.
  Retire changed endpoints and never replay requests after an ambiguous response.
- Queue the first request during initial reference negotiation while keeping live
  status independent. Anchor deadlines before discovery and lock waits, use a
  precise elapsed-time clock, and prevent expired work from executing later.
  Waiting user requests take priority over unstarted preparation.
- Add opt-in phase timings, reproducible benchmarks, build provenance artifacts,
  and Python 3.12/3.14 and PyInstaller/Nuitka comparison tooling.

Python 3.12 and PyInstaller onedir remain the default release configuration.
`instances` and `status` retain local processing after forwarded snapshots failed
the latency gate. The base Compilation cache remains opt-in because its isolated
experiment showed no benefit. Existing code caches, per-request MVID validation
and fresh assembly identities remain; execution results and loaded Unity assemblies
are not reused. Automatic-update behavior is unchanged. Standalone bundles include
Python and the .NET 10/Roslyn runtime without a separate Python or SDK installation.

## Known performance limitation

**Foreground new-code latency is not fully cleared.** Two valid Windows GUI
cohorts measured approximately 337 ms p50 for new-code `exec`, versus 93–94 ms
in public RC2. Later uninstrumented runs of the identical binary measured
78–81 ms and passed the expanded gates, but the earlier delay's cause is unknown.
Those samples are retained, not discarded as outliers. This prerelease does not
claim zero regressions or approve promotion to stable.

Before the RC3 version bump, matched Windows empty-project measurements found:

| Scenario (p50) | Public RC2 | Candidate |
|---|---:|---:|
| Fresh service with Unity already running, Unity 6 | 520 ms | 504 ms |
| Fresh service with Unity already running, Unity 2021 | 504 ms | 477 ms |
| Ready heartbeat observed → first result, Unity 6 | 835 ms | 235 ms |
| Ready heartbeat observed → first result, Unity 2021 | 665 ms | 188 ms |
| Warm `console`, Unity 6 batchmode | 103 ms | 59 ms |
| Reused session `console`, Unity 6 batchmode | 30 ms | 2.1 ms |

Fresh-service and reused-project startup comparisons have 50 samples per variant;
warm commands and sessions have 100. The 20% fresh-service target was not met.
Earlier preparation overlaps work with Editor startup rather than removing all
of that computation. Session values exclude process startup. Background Unity 6
still showed about 107 ms session latency. OS caches were retained; these are not
reboot-cold or agent/model response times.

- [Detailed measurements, p95 and limitations](https://github.com/zjxps2007/UnityBridge/blob/v0.3.0-rc.3/docs/PYTHON_STARTUP.md)
- [Raw samples and checksums](https://github.com/zjxps2007/UnityBridge/tree/v0.3.0-rc.3/docs/benchmarks/python-startup-2026-09-19)

## Install or upgrade

Use the installer and Connector from the **RC3 tag**. For a custom installation,
append `-InstallDir PATH` on Windows or `--install-dir PATH` on macOS/Linux.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install-rc.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.0-rc.3/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.3.0-rc.3
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.0-rc.3/install.sh -o /tmp/unity-bridge-install-rc.sh
sh /tmp/unity-bridge-install-rc.sh --version v0.3.0-rc.3
```

From an existing RC installation, the CLI can also update with:

```text
unity-bridge update --ref v0.3.0-rc.3
```

Update the Unity Package Manager Git URL separately:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.3.0-rc.3
```

After Unity finishes importing, verify `Connector: 0.3.0-rc.3` in
`unity-bridge status`, and run `unity-bridge update --check --ref v0.3.0-rc.3`
to check the CLI. The updater does not modify the Unity package. An unqualified
standalone `update` selects the latest stable release, including when an RC is
installed. Keep the executable beside its `_unity_bridge_runtime_<build-id>` folder.

Python package installation is available but does not automatically bundle or
register the compiler host:

```sh
python -m pip install --upgrade "git+https://github.com/zjxps2007/UnityBridge.git@v0.3.0-rc.3"
```

## Validation scope

Local RC3 verification passed 212 Python tests with one Windows symlink
permission skip, 18 compiler scenarios, 21 extracted-Windows-bundle fast-call
tests, and 19 live checks each in Unity 2021.3.19f1 and 6000.3.13f1. Coverage includes
large Unicode/emoji results, static-state isolation, reference changes, reloads,
concurrent status, expiration and lost-response non-replay.

Publication requires release CI to pass client/installer/compiler tests and
extracted-bundle checks on Windows x64, Linux x64/ARM64 and macOS Intel/Apple
Silicon. Functional CI is separate from the unresolved Windows foreground
performance finding. Historical benchmark files preserve the versions, hashes
and CI status recorded when the measurements were made.

Project source changes still require Unity compilation/domain reload. Arbitrary
C# already executing in Unity cannot be forcibly cancelled. The compiler requires
a .NET 10 supported OS. Unity 2020.3 has source/API compatibility evidence;
no native 2020.3 run was available.

## 한국어 안내

- **v0.3.0-rc.3 프리릴리즈**입니다. CLI·Python·Unity Connector 버전을 함께
  갱신했으며 정식 버전은 v0.2.3으로 유지합니다.
- 호스트·컴파일러 준비를 앞당기고, `console`·`tools`·`wait-ready` 경량 호출,
  세션 JSON 중복 변환 제거와 연결 재사용을 적용했습니다. 초기 참조 협상 중 첫
  요청이 거절되던 문제도 수정했습니다. 원래 제한 시간과 중복 실행 방지는 유지합니다.
- Python 3.12·PyInstaller를 유지합니다. 기본 Compilation 캐시와 스냅샷 전달은
  기본값에서 제외했고 자동 업데이트 주기와 정식/프리릴리즈 선택은 바꾸지 않았습니다.
- **전경 새 코드 `exec` 지연의 원인은 아직 확인되지 않았습니다.** 두 측정에서
  p50 약 337ms가 나왔고 동일 바이너리 재측정은 78~81ms로 통과했습니다.
  느린 결과도 보존했으며 성능 무회귀나 정식 버전 채택을 보장하지 않습니다.
- CLI는 `unity-bridge update --ref v0.3.0-rc.3`, Unity 패키지는 위 RC3 Git URL로
  각각 갱신하세요. Unity import 후 `status`의 `Connector: 0.3.0-rc.3`을 확인합니다.
- [한국어 비교 보고서](https://github.com/zjxps2007/UnityBridge/blob/v0.3.0-rc.3/docs/PYTHON_STARTUP.ko.md)에
  조건별 수치와 아직 확인할 사항을 정리했습니다.
