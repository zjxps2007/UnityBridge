# UnityBridge v0.3.0-rc.1 — prerelease

This release candidate is published from `codex/external-host-compiler` without
merging it into `main`. The latest stable release remains
[v0.2.3](https://github.com/zjxps2007/UnityBridge/releases/tag/v0.2.3).
CLI, Python source and Unity Connector versions are `0.3.0-rc.1`; Python package
metadata may display the equivalent normalized version `0.3.0rc1`.

## Changes

- Add a persistent Python host and a bundled .NET 10/Roslyn compiler. Unity starts
  the registered host asynchronously, which prepares compiler references and exits
  after 30 seconds without live Editors or pending work. Users of standalone
  bundles do not need to install Python or the .NET SDK.
- Compile snippets outside Unity, then invoke them on Unity's main thread. Reuse
  compilation preparation, validate actual reference MVIDs, and emit a unique
  assembly identity for each execution. Results and static state are not cached.
- Keep HTTP I/O off the Editor update loop while preserving main-thread tool
  invocation and result serialization. Prepare reference identities once per
  negotiated context and avoid duplicate DLL image reads/copies.
- Preserve per-project mutation order, validate deadlines after the execution
  lock, cancel queued work from a stopped listener, and never replay a command
  after an ambiguous lost response. Live readiness remains distinct from host health.
- Keep the legacy route and explicit `--csc`/`--dotnet` overrides. Select
  `--backend auto|host|legacy` or `UNITY_BRIDGE_BACKEND`. Both transports stay on
  loopback without environment proxies or redirects.
- Include compiler timeout/recovery, stale host PID recovery, installer rollback,
  authenticated host communication and fixes for worker timeout races.

## Install or upgrade to this RC

Use the installer **from this RC tag**, including for the first upgrade from
v0.2.3. A stable installer may install the new bundle without its host setup.
For a custom existing installation, add `-InstallDir PATH` or `--install-dir PATH`.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install-rc.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.0-rc.1/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.3.0-rc.1
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.0-rc.1/install.sh -o /tmp/unity-bridge-install-rc.sh
sh /tmp/unity-bridge-install-rc.sh --version v0.3.0-rc.1
```

Also update the Unity Package Manager Git URL:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.3.0-rc.1
```

After Unity finishes importing/compiling, verify `Connector: 0.3.0-rc.1` in
`unity-bridge status` and check the CLI:

```text
unity-bridge update --check --ref v0.3.0-rc.1
```

The CLI updater does not update the Unity package. Once running this RC, use
`unity-bridge update --ref v0.3.0-rc.1` to retain the RC channel. An unqualified
standalone `update` installs the latest stable release, even when an RC is installed.
Keep the executable beside its `_unity_bridge_runtime_<build-id>` directory.

Python-only installation is also available, but does not bundle/register the
compiler host automatically:

```sh
python -m pip install --upgrade "git+https://github.com/zjxps2007/UnityBridge.git@v0.3.0-rc.1"
```

## Validation and limits

Local RC preparation ran 167 Python checks (166 passed and one Windows symlink
privilege skip) and passed 14 native checks each in Unity 2021.3.19f1 and
6000.3.13f1. The compiler has 13 real Roslyn regression cases. Tagged release CI reruns client/installer/compiler
checks, then verifies all five platform archives before publication:
Windows x64, Linux x64/ARM64, macOS Intel/Apple Silicon.

Matched Windows batch-mode measurements against the earlier development build
reduced prepared `exec` median latency from about 250 ms to 122–124 ms, and
`tools` from about 250 ms to 109 ms. All ordinary-command p95 gates passed.
These measurements predate the RC version bump; they are not a GUI FPS or
prompt-to-answer guarantee. See the
[detailed report](https://github.com/zjxps2007/UnityBridge/blob/v0.3.0-rc.1/docs/HOST_OPTIMIZATION.md)
for sample counts, first-start timing, memory and installation costs.

Project source changes still require Unity compilation/domain reload. Already
running arbitrary C# cannot be forcibly cancelled. The bundled compiler needs a
.NET 10 supported OS and adds installation size/resident memory. Unity 2020.3
has source/API compatibility evidence only; no native 2020.3 run was available.

## 한국어 안내

- 현재 개발 브랜치를 배포하는 **v0.3.0-rc.1 프리릴리즈**입니다. main은 병합하지
  않았으며 최신 정식 버전은 v0.2.3으로 유지됩니다.
- 독립 Python 호스트·Roslyn 워커를 추가하고, 네트워크 대기와 중복 참조 처리를
  줄였습니다. Unity API 호출과 결과 직렬화는 메인 스레드에서 수행합니다.
- 기존 v0.2.3에서 처음 올릴 때는 위의 **RC 태그 설치기**를 사용하세요. 사용자
  지정 설치 위치가 있다면 같은 경로를 명시하세요. Unity 패키지 URL도 별도로
  `#v0.3.0-rc.1`로 바꿔야 합니다.
- 이후 RC를 지정해 업데이트하려면 `--ref v0.3.0-rc.1`을 사용합니다. 버전 없는
  일반 업데이트는 RC에서도 최신 정식 버전으로 돌아갈 수 있습니다.
- Python 메타데이터의 `0.3.0rc1`은 `0.3.0-rc.1`과 같은 버전입니다. Python만
  설치하면 독립 컴파일러가 자동으로 포함·등록되지는 않습니다.
- [한글 측정·검증 보고서](https://github.com/zjxps2007/UnityBridge/blob/v0.3.0-rc.1/docs/HOST_OPTIMIZATION.ko.md)에
  실제 응답 시간, 첫 시작 비용, 메모리와 검증 범위를 정리했습니다.
