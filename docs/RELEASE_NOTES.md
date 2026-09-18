# UnityBridge v0.3.0-rc.2 — prerelease

RC2 reduces CLI startup and repeated-command overhead while keeping the CLI and
resident host in Python. It also improves operation completion checks and compiler
startup. This release comes from `codex/external-host-compiler`; the latest stable
release remains [v0.2.3](https://github.com/zjxps2007/UnityBridge/releases/tag/v0.2.3).

CLI, Python source and Unity Connector versions are **0.3.0-rc.2**. Python package
metadata may display the equivalent normalized version `0.3.0rc2`.

## Changes since RC1

- Forward eligible single `exec` calls to the running host without loading the
  full CLI in each caller. Reuse the existing parser, output, discovery and
  per-project execution queue in the host. Preserve authentication, original
  deadlines, compiler overrides, older-host fallback and no replay after an
  ambiguous response. Standalone streams use UTF-8, including Windows pipes.
- Load optional CLI modules and only the requested command parser on demand.
  Add a sequential JSONL `session` command for integrations that keep one CLI
  process open across requests.
- Wake host discovery on authenticated Connector state-change notifications,
  retaining periodic discovery and checking changed ports before dispatch.
- Confirm `refresh --wait`, `reserialize --wait` and `editor play|stop --wait`
  using operation IDs and live Unity events, including across domain reloads.
  Confirmed operations need no fixed settling delay. Older Connectors retain
  conservative waits; lost or cancelled operations are not replayed.
- Publish the compiler with ReadyToRun and account for shared reference images
  once in the compilation cache. Repeated snippets still emit unique assemblies
  and execute again; return values and snippet static state are not reused.
- Keep automatic-update checks and stable/prerelease selection unchanged.

The external host and bundled .NET 10/Roslyn compiler introduced in RC1 remain.
Unity API work still executes on the Unity main thread. Standalone users do not
need to install Python or a .NET SDK separately.

## Install or upgrade

Use the installer and Connector from the **RC2 tag**. For a custom installation,
append `-InstallDir PATH` on Windows or `--install-dir PATH` on macOS/Linux.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install-rc.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.0-rc.2/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.3.0-rc.2
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.0-rc.2/install.sh -o /tmp/unity-bridge-install-rc.sh
sh /tmp/unity-bridge-install-rc.sh --version v0.3.0-rc.2
```

From an existing RC installation, the CLI can also update with:

```text
unity-bridge update --ref v0.3.0-rc.2
```

Update the Unity Package Manager Git URL separately:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.3.0-rc.2
```

After Unity finishes importing, verify `Connector: 0.3.0-rc.2` in
`unity-bridge status`, and run `unity-bridge update --check --ref v0.3.0-rc.2`
to check the CLI. The updater does not modify the Unity package. An unqualified
standalone `update` selects the latest stable release, including when an RC is
installed. Keep the executable beside its `_unity_bridge_runtime_<build-id>` folder.

Python package installation is available but does not automatically bundle or
register the compiler host:

```sh
python -m pip install --upgrade "git+https://github.com/zjxps2007/UnityBridge.git@v0.3.0-rc.2"
```

## Validation and measured scope

Local validation passed 195 of 196 Python tests, with one Windows symlink
permission skip, and 15 compiler regression scenarios. Real Unity 2021.3.19f1
and 6000.3.13f1 each passed 18 checks, including static-state isolation, compiler
error recovery, reference changes, reloads and expiry without late side effects.
All 14 fast-route tests passed with source Python and the extracted Windows bundle.
Release CI reruns client/installer/compiler tests and verifies extracted bundles
for Windows x64, Linux x64/ARM64, and macOS Intel/Apple Silicon before publication.

Before the RC2 version bump, matched Windows batch-mode measurements found that
the Python fast route reduced prepared `exec` p50 by **17–28%** and p95 by
**21–23%** relative to the immediately preceding unreleased optimized build.
Ordinary-command p95 remained within the allowed increase of
`max(5% of baseline, 10 ms)`. Service startup itself did not improve in that
comparison. The broader RC1 comparison also covers compiler startup, operation
waits and persistent sessions. These are empty-project measurements, not a GUI
frame-rate or agent-prompt-to-answer guarantee:

- [RC1 follow-up measurements](https://github.com/zjxps2007/UnityBridge/blob/v0.3.0-rc.2/docs/SPEED_FOLLOWUP.md)
- [Python exec measurements](https://github.com/zjxps2007/UnityBridge/blob/v0.3.0-rc.2/docs/EXEC_OPTIMIZATION.md)

ReadyToRun increases bundle size. The bundled compiler needs a .NET 10 supported
OS. Project source changes still require Unity compilation/domain reload, and
arbitrary C# already executing in Unity cannot be forcibly cancelled. Unity
2020.3 has source/API compatibility evidence; no native 2020.3 run was available.

## 한국어 안내

- **v0.3.0-rc.2 프리릴리즈**입니다. 개발 브랜치에서 배포하며 정식 버전은 v0.2.3입니다.
- CLI와 호스트를 Python으로 유지해 단일 `exec`의 초기화 비용을 줄였습니다.
  JSONL 연속 명령, 실제 작업 완료 확인, 상태 변경 알림, ReadyToRun과 캐시 개선도 포함합니다.
- CLI와 Unity Connector를 모두 RC2로 갱신하세요. CLI 업데이트는
  `unity-bridge update --ref v0.3.0-rc.2`, Unity 패키지는 위 Git URL을 사용합니다.
- 자동 업데이트 동작은 그대로이며, 버전 없는 업데이트는 정식 버전을 선택합니다.
- 준비된 `exec`의 개선과 서비스 첫 시작은 구분해야 합니다. 실측 조건과 비용은
  [RC1 이후 검증](https://github.com/zjxps2007/UnityBridge/blob/v0.3.0-rc.2/docs/SPEED_FOLLOWUP.ko.md)과
  [Python exec 검증](https://github.com/zjxps2007/UnityBridge/blob/v0.3.0-rc.2/docs/EXEC_OPTIMIZATION.ko.md)에 기록했습니다.
