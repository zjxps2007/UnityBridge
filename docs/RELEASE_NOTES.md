# UnityBridge v0.2.2-rc.2

This prerelease fixes the Connector version reported by `unity-bridge status`. In RC1, the Unity package manifest said `0.2.2-rc.1`, but a separate runtime constant still reported `0.2.1`. RC2 reads the installed package metadata and reports `0.2.2-rc.2`.

## Changes

- Remove the duplicated C# version constant. Resolve the version from the installed Unity package and cache it until a package registration change or domain reload. Source copied outside a UPM package reports `unknown`.
- Extend native validation to install the Connector as an embedded UPM package and compare JSON `status`, live `wait-ready`, and the human-readable `Connector:` line with the package version, before and after domain reload.
- Clarify that release CI's remote version check validates the Connector manifest; actual runtime reporting is checked separately in Unity.
- Include the startup improvements and CLI refactoring from [RC1](https://github.com/zjxps2007/UnityBridge/releases/tag/v0.2.2-rc.1): install-once runtime bundles, cached tool discovery, lazy parameter schemas, and focused CLI modules. No fixed readiness delay is introduced.

## Upgrade both components

If the CLI is already on RC1:

```text
unity-bridge update --ref v0.2.2-rc.2
```

Also change the Unity Package Manager Git URL to:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.2.2-rc.2
```

After Unity finishes importing and compiling, run `unity-bridge status`. It should show `Connector: 0.2.2-rc.2`. The CLI updater does not update the Unity project's package automatically.

For a fresh installation or an upgrade from v0.2.1, use this tag's installer. The installer on `main` still uses the older single-file release format.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install-rc.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.2-rc.2/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.2.2-rc.2
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.2-rc.2/install.sh -o /tmp/unity-bridge-install-rc.sh
sh /tmp/unity-bridge-install-rc.sh --version v0.2.2-rc.2
```

Verify the CLI with `unity-bridge update --check --ref v0.2.2-rc.2`. Python metadata may display the equivalent version `0.2.2rc2`.

Default installation and plain `unity-bridge update` select the latest stable release. To return both components to v0.2.1, run `unity-bridge update --ref v0.2.1` and change the Connector URL to `#v0.2.1`.

## Validation

- 94 Python tests passed locally.
- Native Unity 2021.3.19f1 and 6000.3.13f1 checks verify the package version in `status` and live readiness responses, including after compilation/domain reload, plus tool discovery and execution regressions.
- The new native check was also run against the original RC1 package and correctly rejected its stale `0.2.1` runtime version.
- Release CI builds and runs the archived executable on Windows x64, Linux x64/ARM64, and macOS Intel/Apple Silicon. Publication waits for all five builds.

## 한국어 안내

- RC1을 설치해도 `Connector: 0.2.1`로 표시되던 버그를 수정했습니다. 이제 Unity에 설치된 패키지 정보에서 버전을 읽습니다.
- **CLI와 Unity Connector를 모두 `0.2.2-rc.2`로 업데이트하세요.** CLI 업데이트만으로 Unity 프로젝트의 Connector가 바뀌지는 않습니다.
- CLI가 RC1이면 `unity-bridge update --ref v0.2.2-rc.2`를 실행하고, 위의 Unity Package Manager URL도 RC2 태그로 변경하세요.
- Unity 컴파일 완료 후 `unity-bridge status`에서 `Connector: 0.2.2-rc.2`를 확인할 수 있습니다.
- 기본 설치는 정식 릴리스를 선택합니다. 이번 프리릴리스 배포에는 `main` 병합이 포함되지 않습니다.
- 자세한 설치·복귀 방법은 [한국어 설치 안내](https://github.com/zjxps2007/UnityBridge/blob/v0.2.2-rc.2/docs/INSTALL.ko.md#프리릴리스)를 참고하세요.
