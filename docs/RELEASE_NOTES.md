# UnityBridge v0.2.3-rc.1

This prerelease from `codex/heartbeat-state-updates` improves how quickly saved
Heartbeat state reflects changes in the Unity Editor. CLI and Unity Connector
versions are both `0.2.3-rc.1`. The latest stable release remains v0.2.2.

## Changes

- Publish server startup and pause/resume events immediately. Changes in state,
  compile errors, or port detected on an Editor update bypass the periodic interval.
- Keep regular Heartbeat publication at 0.5 seconds, about two writes per second
  while state is unchanged. Event writes reset the periodic clock to avoid a
  redundant scheduled write immediately afterward.
- Preserve refresh/compile/play readiness guards and atomic file replacement.
  Failed writes record their attempt time so unchanged state does not trigger
  filesystem retries every Editor update.
- Add optional native Unity audits for publication cadence, write cost, and
  pause/resume state visibility.

The improvement is fresher state at transitions. An unchanged Editor retains
the usual `Heartbeat age` range. Event writes and per-update state checks have a
cost; these changes do not establish lower whole-command latency or better game
frame performance. Busy or throttled Editors can still delay publication.

## Upgrade both components

From a v0.2.2 standalone CLI or a v0.2.2 release candidate:

```text
unity-bridge update --ref v0.2.3-rc.1
```

Also set the Unity Package Manager Git URL to:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.2.3-rc.1
```

After Unity finishes importing and compiling, `unity-bridge status` should show
`Connector: 0.2.3-rc.1`. The CLI updater does not update the Unity project's package
automatically. Verify the CLI with `unity-bridge update --check --ref v0.2.3-rc.1`.

For a fresh installation or an upgrade from v0.2.1 or earlier, rerun the new
installer. Older updaters expect the previous single-file release format.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.3-rc.1/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.2.3-rc.1
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.3-rc.1/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.2.3-rc.1
```

The installed executable needs its adjacent `_unity_bridge_runtime_<build-id>`
folder. Keep them together. Default installation and updates select the latest
stable release; select the tag explicitly to try this prerelease.

## Validation

- 94 Python regression tests cover CLI requests, discovery, adapters, updates,
  and offline installer fixtures.
- Native Unity 2021.3.19f1 and 6000.3.13f1 validation checks JSON `status`, live
  readiness, and the human-readable Connector version before and after a real
  compilation/domain reload, plus tool discovery, C# execution, and pause/resume
  Heartbeat publication. These are empty-project batch-mode checks.
- Release CI builds and exercises the archived executables on Windows x64,
  Linux x64/ARM64, and macOS Intel/Apple Silicon. Publication waits for all five.

## 한국어 안내

- v0.2.3-rc.1은 Heartbeat 상태 반영 개선을 담은 프리릴리스입니다.
  서버 시작과 일시정지·재개 이벤트를 바로 기록하고, 감지한 상태 변화도 정기 갱신을
  기다리지 않습니다. 평상시 기록은 기존 0.5초 간격을 유지합니다.
- CLI와 Unity Connector를 모두 `0.2.3-rc.1`로 맞추세요. Unity 컴파일 완료 후
  `unity-bridge status`에서 `Connector: 0.2.3-rc.1`을 확인할 수 있습니다.
- v0.2.2 또는 해당 버전의 RC CLI는 `unity-bridge update --ref v0.2.3-rc.1`로
  업데이트합니다. v0.2.1 이하에서는 위의 새 설치기를 다시 실행하세요.
- 기본 설치와 버전 지정 없는 업데이트는 정식 v0.2.2를 선택합니다.
  이 검증 결과로 전체 명령 응답 시간이나 FPS가 개선됐다고 판단하지 않습니다.
