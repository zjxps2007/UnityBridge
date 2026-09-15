# UnityBridge v0.2.2-rc.1

This is an opt-in prerelease from `codex/faster-startup` for testing startup improvements and the CLI refactor before merging into `main`.

## Changes

- Standalone releases now contain the executable and its runtime in a ZIP or tar.gz bundle. Installation extracts the runtime once; each command no longer unpacks a single-file executable. Keep the runtime folder beside the executable.
- Installers validate staged downloads before replacing the command, preserve custom installation paths, and give each build a separate runtime directory. Older single-file releases remain installable.
- Unity tool discovery uses TypeCache with a reflection fallback for runtime-loaded assemblies. Parameter schemas are generated on the first tool-list request, then cached. Dynamic tools, duplicate-handler selection, and domain reload remain supported.
- Split CLI argument parsing, dispatch, output, updates, installer commands, and version parsing into focused internal modules while preserving public commands and request contracts.
- Correct prerelease version comparisons: Python's `0.2.2rc1` and Unity's `0.2.2-rc.1` are equivalent, and final `0.2.2` sorts after its RCs. Explicit prerelease self-updates use the installer from the requested tag.
- The release workflow marks prerelease tags appropriately, preserves the latest stable release, and publishes only after all five platform bundles pass validation.

## Install both components

Use the installer **from this tag**, including when upgrading from v0.2.1. The v0.2.1 updater downloads the older installer from `main`, which does not support these bundles.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install-rc.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.2-rc.1/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.2.2-rc.1
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.2-rc.1/install.sh -o /tmp/unity-bridge-install-rc.sh
sh /tmp/unity-bridge-install-rc.sh --version v0.2.2-rc.1
```

Unity Package Manager Git URL:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.2.2-rc.1
```

Confirm the CLI with `unity-bridge update --check --ref v0.2.2-rc.1`. Default installation and plain `unity-bridge update` select the stable release, so the latter can replace this RC with v0.2.1. To return both components to v0.2.1, run `unity-bridge update --ref v0.2.1` and change the Connector URL to `#v0.2.1`.

## Validation and scope

- 94 Python tests passed locally, including installer migration, rejected-download recovery, command contracts, and prerelease ordering.
- The startup implementation and CLI refactor were validated in native Unity 2021.3.19f1 and 6000.3.13f1, including dynamic tool discovery, duplicate handlers, compilation, and domain reload.
- Release CI builds and runs the archived executable on Windows x64, Linux x64/ARM64, and macOS Intel/Apple Silicon. Publication waits for all five builds.
- Earlier Windows measurements using the same local Python/PyInstaller toolchain showed substantially lower process-start cost than v0.2.0/v0.2.1. Those measurements are not an A/B benchmark of these official release binaries or the full Codex response. Unity workload, Editor throttling, and machine state still affect response time.
- The live readiness behavior from v0.2.1 remains: no fixed 0.5-second settling delay. After editing scripts, use `refresh --compile request --wait` to request compilation and wait for it.

## 한국어 안내

- `codex/faster-startup`의 시작 속도 개선과 CLI 리팩토링을 시험하는 프리릴리스입니다.
- **위의 태그 전용 설치 명령을 사용하고 CLI와 Unity Connector를 모두 `0.2.2-rc.1`로 맞추세요.** v0.2.1의 기존 업데이터로는 새 압축 번들을 직접 설치할 수 없습니다.
- 실행 파일과 런타임은 설치할 때 한 번 압축을 풀며, 이후 명령을 실행할 때 다시 풀지 않습니다. 실행 파일 옆의 런타임 폴더를 유지하세요.
- 기본 설치는 정식 릴리스를 선택합니다. 이번 배포는 `main` 병합을 포함하지 않습니다.
- 설치와 정식 버전 복귀 방법은 [한국어 설치 안내](https://github.com/zjxps2007/UnityBridge/blob/v0.2.2-rc.1/docs/INSTALL.ko.md#프리릴리스)를 참고하세요.
