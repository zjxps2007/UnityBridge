# UnityBridge v0.3.1-rc.1 — prerelease

This release candidate adds parallel compiler reference validation and optional
session pipelining to v0.3.0. It is published from `codex/session-exec-throughput`.
The CLI, Python package and Unity Connector versions are all **0.3.1-rc.1**.

## Changes since v0.3.0

- Compiler reference validation can read independent DLL metadata in parallel.
  Every request still checks the actual reference MVIDs, including cache hits;
  matching file timestamps alone do not make a reference valid. The compiler
  avoids an extra copy of metadata bytes that it already owns.
- `session --pipeline 1|2|4` accepts a bounded number of outstanding requests.
  The default remains `1`. With a compatible host, inline `exec --code` requests
  can prepare the next compilation while Unity executes the previous request.
  Responses are flushed in input order without waiting for EOF or a full window.
- Unity API execution remains ordered. File input, ordinary commands, compiler
  overrides and target changes wait for earlier work. Prepared compilations are
  revalidated when their request reaches the front of the execution queue.
- Queued requests can be cancelled before dispatch. Their original deadlines
  include queue waiting. A lost response after dispatch is not automatically
  replayed; an uncertain completion stops the pipeline and cancels undispatched
  work. Already dispatched C# can still finish.
- Host enqueue, result and cancellation endpoints use the existing authenticated
  local transport. Result polling and cancellation use separate connections.
  Older hosts use the sequential route before submission.
- An experimental second compiler worker is available through
  `UNITY_BRIDGE_EXPERIMENTAL_COMPILER_WORKERS=2`. The default remains one worker;
  an idle secondary worker retires after 30 seconds. This option does not make
  Unity API calls execute in parallel.

Python 3.12 and PyInstaller onedir remain the release defaults. Archives contain
the Python runtime and the self-contained .NET 10/Roslyn compiler runtime.
Installers unpack the bundle once; no separate SDK installation is required.
Automatic update checks keep their existing behavior. Default installation and
unqualified updates continue to select stable **v0.3.0**.

For pipeline input, output and failure handling, see the
[command guide](https://github.com/zjxps2007/UnityBridge/blob/v0.3.1-rc.1/docs/COMMANDS.md#optional-session-pipeline-v031-rc1).

## Install or upgrade

Explicitly select this candidate:

```text
unity-bridge update --ref v0.3.1-rc.1
```

For a fresh install, use the tagged installer. Custom installations can append
`-InstallDir PATH` on Windows or `--install-dir PATH` on macOS/Linux.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.1-rc.1/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.3.1-rc.1
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.1-rc.1/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.3.1-rc.1
```

Update the Unity Package Manager Git URL separately:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.3.1-rc.1
```

After Unity imports the package, verify `Connector: 0.3.1-rc.1` with
`unity-bridge status`. Run `unity-bridge update --check --ref v0.3.1-rc.1`
to verify the CLI version. Updating the CLI does not edit the Unity package URL.
Keep the executable beside its `_unity_bridge_runtime_<build-id>` folder.

Python package mode remains available without automatically bundling or
registering the compiler host:

```sh
python -m pip install --upgrade "git+https://github.com/zjxps2007/UnityBridge.git@v0.3.1-rc.1"
```

## Validation scope

The release workflow runs Python client and installer tests, compiler scenarios,
and extracted-bundle checks on Windows x64, Linux x64/ARM64 and macOS Intel/Apple
Silicon. Publication requires every platform to pass.

Project source changes still require Unity compilation/domain reload. Arbitrary
C# already executing in Unity cannot be forcibly cancelled. The compiler requires
a .NET 10 supported OS. Session pipelining is opt-in and keeps Unity execution on
the main thread.

## 한국어 안내

- **v0.3.1-rc.1 프리릴리스**입니다. 현재 기능 브랜치에서 배포하며
  CLI·Python·Unity Connector 버전을 모두 0.3.1-rc.1로 맞췄습니다.
- 참조 DLL의 병렬 검증과 불필요한 메타데이터 복사 제거를 적용했습니다.
  캐시가 있어도 매 요청에서 실제 MVID를 확인합니다.
- `session --pipeline 1|2|4`로 다음 코드의 컴파일 준비를 앞선 Unity 실행과
  겹칠 수 있습니다. 기본값은 `1`이며 Unity API 실행과 응답 순서는 유지합니다.
- 컴파일러 워커는 기본 1개입니다. 실험적 2개 설정도 Unity API를 병렬로
  실행하지 않으며, 전달 이후 응답이 유실된 명령은 자동 재실행하지 않습니다.
- CLI는 `unity-bridge update --ref v0.3.1-rc.1`, Unity 패키지는 위
  `#v0.3.1-rc.1` Git URL로 각각 갱신하세요. 기본 설치·업데이트는 정식
  v0.3.0을 선택하며 자동 업데이트 확인 동작은 그대로입니다.
- [한국어 설치 안내](https://github.com/zjxps2007/UnityBridge/blob/v0.3.1-rc.1/docs/INSTALL.ko.md#프리릴리스)와
  [세션 사용법](https://github.com/zjxps2007/UnityBridge/blob/v0.3.1-rc.1/docs/COMMANDS.ko.md#선택적-세션-파이프라인-v031-rc1)을 참고하세요.
