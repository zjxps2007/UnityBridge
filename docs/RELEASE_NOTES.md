# UnityBridge v0.3.0 — stable release

v0.3.0 brings the independent Python host, bundled Roslyn compiler and persistent
JSONL sessions to the stable channel. It integrates `codex/external-host-compiler`
into `main`, promoting the RC3 implementation without additional runtime changes.
CLI, Python package and Unity Connector versions are all **0.3.0**.

## Changes since v0.2.3

- A persistent Python service owns connections, per-project request order,
  readiness and reload waiting. It retains requests not yet dispatched to Unity;
  a request with a lost response after dispatch is never automatically replayed.
- A separate .NET 10/Roslyn worker compiles C# against each project's actual Unity
  references and language version. Unity loads the emitted DLL and executes API
  calls on its main thread. Compiler preparation is outside the execution lock.
- Compiler caches reuse preparation while checking reference MVIDs on every
  request and emitting a fresh assembly identity. Execution results, loaded
  assemblies and static state are not reused. A compiler timeout terminates only
  the worker, not the host or arbitrary C# already running in Unity.
- The Connector starts external preparation asynchronously during initialization.
  Asset import workers are excluded; Unity reference collection and execution
  still require live readiness. Preparation code is never executed in Unity.
- Lightweight forwarding reduces startup work for eligible `exec`, `console`,
  `tools` and `wait-ready` calls. Existing commands, Python APIs, project/port
  selection, compiler overrides, JSON output and exit codes remain available.
- Persistent `session` accepts JSONL requests, returns structured results with one
  serialization, and reuses HTTP connections. Separate execution and status lanes
  keep control requests independent of long execution requests.
- Operation-specific completion and early absolute deadlines improve waiting.
  Deadlines are checked again after acquiring the execution lock, preventing
  expired queued work from running later. Unstarted preparation yields to users.
- Installers register exact CLI/worker paths for Unity Hub, and the host shuts
  down after 30 seconds without Editors or work. The host uses authenticated
  loopback communication and a registry separate from Unity heartbeat files.

Python 3.12 and PyInstaller onedir remain the release defaults. Standalone archives
include Python and the self-contained .NET 10/Roslyn runtime, with no separate SDK
installation required. Ordinary ReadyToRun is enabled. `instances` and `status`
retain local processing; the base Compilation cache stays opt-in. Automatic
update checks keep their existing behavior. An unqualified install or update
selects the latest stable release, including when a release candidate is installed.

## Install or upgrade

From v0.2.3 or a v0.3.0 release candidate:

```text
unity-bridge update
```

To pin this release, use `unity-bridge update --ref v0.3.0`. For a fresh install or
v0.2.1 and earlier, run the tagged installer below. Custom installations can append
`-InstallDir PATH` on Windows or `--install-dir PATH` on macOS/Linux.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.0/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.3.0
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.0/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.3.0
```

Update the Unity Package Manager Git URL separately:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.3.0
```

After Unity finishes importing, verify `Connector: 0.3.0` in `unity-bridge status`
and CLI version `0.3.0` with `unity-bridge update --check`. The updater preserves
custom installation paths but does not change the Unity package. Keep the
executable beside its `_unity_bridge_runtime_<build-id>` folder.

Python package mode remains available, without automatically bundling or
registering the compiler host:

```sh
python -m pip install --upgrade "git+https://github.com/zjxps2007/UnityBridge.git@v0.3.0"
```

## Validation scope

Local v0.3.0 pre-publication verification passed 212 Python tests with one
environment skip, 18 compiler scenarios, 21 packaged-Windows fast-call tests and
19 live checks each in Unity 2021.3.19f1 and 6000.3.13f1. Live checks confirmed
Connector version 0.3.0, reload recovery, reference invalidation, static-state
isolation, expiration, concurrent status and lost-response non-replay.

Publication requires passing client/installer/compiler tests and extracted-bundle
checks on Windows x64, Linux x64/ARM64 and macOS Intel/Apple Silicon.
Historical benchmarks preserve their original versions, hashes and measurement
conditions. Final local release verification is recorded separately; functional
checks do not establish performance across every environment.

Project source changes still require Unity compilation/domain reload. Arbitrary
C# already executing in Unity cannot be forcibly cancelled. The compiler requires
a .NET 10 supported OS. Unity 2020.3 has source/API compatibility evidence;
no native 2020.3 run was available.

## 한국어 안내

- **v0.3.0 정식 릴리스**입니다. 독립 호스트·컴파일러 브랜치를 `main`에 통합하고,
  CLI·Python·Unity Connector 버전을 모두 0.3.0으로 맞췄습니다.
- Python 상주 호스트, 동봉 Roslyn 워커, 빠른 사전 준비, 경량 CLI 호출과 JSONL
  세션을 포함합니다. Unity API는 계속 메인 스레드에서 실행하며 원래 제한 시간,
  정적 상태 격리, 전달 이후 응답 유실 시 중복 실행 방지를 유지합니다.
- Python 3.12·PyInstaller를 유지하며 자동 업데이트 확인 동작은 그대로입니다.
- 정식 버전 로컬 검증에서 Python 212개 통과·1개 건너뜀, 컴파일러 18개,
  Windows 실행 파일 21개와 Unity 2021·6 각각 19개 검증을 통과했습니다.
- CLI는 `unity-bridge update`, Unity 패키지는 위 `#v0.3.0` Git URL로 각각
  갱신하세요. Unity import 후 `Connector: 0.3.0`을 확인합니다.
- [한국어 설치 안내](https://github.com/zjxps2007/UnityBridge/blob/v0.3.0/docs/INSTALL.ko.md)와
  [성능 비교 보고서](https://github.com/zjxps2007/UnityBridge/blob/v0.3.0/docs/PYTHON_STARTUP.ko.md)를 참고하세요.
