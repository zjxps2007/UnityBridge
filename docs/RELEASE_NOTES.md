# UnityBridge v0.2.2

This stable release includes the startup improvements, CLI refactoring, and
Connector version fix validated in v0.2.2-rc.2. CLI and Unity Connector versions
are both `0.2.2`.

## Changes

- Standalone runtimes are unpacked once during installation, avoiding repeated
  extraction each time a command starts. Installers, updates, and release CI
  support these bundles while retaining support for older single-file assets.
- Defer Unity tool parameter schemas until they are requested, cache discovery,
  and preserve dynamically loaded tools and the existing handler/schema contract.
- Split CLI argument parsing, command routing, output, and update/version handling
  into focused internal modules while preserving command syntax and JSON output.
- Read the running Connector version from Unity package metadata. This fixes RC1
  reporting `Connector: 0.2.1` despite its newer package manifest. Cache the version
  until package registration changes or a domain reload.
- Keep the existing 0.5-second periodic heartbeat interval. Heartbeat publication
  changes are being developed separately and are not part of this release.

## Upgrade both components

From an RC1/RC2 standalone CLI:

```text
unity-bridge update --ref v0.2.2
```

Also set the Unity Package Manager Git URL to:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.2.2
```

After Unity finishes importing and compiling, `unity-bridge status` should show
`Connector: 0.2.2`. The CLI updater does not update the Unity project's package
automatically. Verify the CLI with `unity-bridge update --check --ref v0.2.2`.

For a fresh installation or an upgrade from v0.2.1 or earlier, rerun the new
installer. Older updaters expect the previous single-file release format.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.2/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.2.2
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.2/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.2.2
```

The installed executable needs its adjacent `_unity_bridge_runtime_<build-id>`
folder. Keep them together. Default installation selects the latest stable release.

## Validation

- 94 Python regression tests cover CLI requests, discovery, adapters, updates,
  and offline installer fixtures.
- Native Unity 2021.3.19f1 and 6000.3.13f1 validation checks JSON `status`, live
  readiness, and the human-readable Connector version before and after a real
  compilation/domain reload, plus tool discovery and C# execution.
- Release CI builds and exercises the archived executables on Windows x64,
  Linux x64/ARM64, and macOS Intel/Apple Silicon. Publication waits for all five.

## 한국어 안내

- v0.2.2 정식 릴리스에는 설치 시 한 번만 런타임을 푸는 배포 방식, 도구 탐색 개선,
  CLI 리팩토링, Connector 버전 표시 수정이 포함됩니다.
- CLI와 Unity Connector를 모두 `0.2.2`로 업데이트하세요. Unity 컴파일 완료 후
  `unity-bridge status`에서 `Connector: 0.2.2`를 확인할 수 있습니다.
- RC1/RC2 CLI는 `unity-bridge update --ref v0.2.2`로 업데이트합니다.
  v0.2.1 이하에서는 위의 새 설치기를 다시 실행하세요.
- Heartbeat 정기 갱신은 기존 0.5초를 유지합니다. 상태 반영 개선은 별도 브랜치에서
  진행하며 이번 정식 릴리스에는 포함되지 않습니다.
