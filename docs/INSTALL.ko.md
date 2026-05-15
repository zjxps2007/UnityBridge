# UnityBridge 설치

한국어 | [English](INSTALL.md) | [README](../README.ko.md)

이 문서는 standalone CLI 설치, Unity 패키지 버전 고정, 업데이트, release asset을 다룹니다.
Python 패키지 모드는 [PYTHON_PACKAGE.ko.md](PYTHON_PACKAGE.ko.md)에 따로 정리했습니다.

## Unity 패키지

Unity Editor에서 `Window > Package Manager > + > Add package from git URL...`을 열고
아래 URL을 붙여넣습니다.

```text
https://github.com/zjxps2007/UnityBridge.git?path=unity-bridge-connector
```

Connector는 Unity Editor가 열릴 때 자동으로 시작됩니다. 실행 중에는
`~/.unity-bridge/instances/` 아래에 heartbeat 파일을 기록합니다. CLI는 이 파일을 읽어
Unity Editor를 발견하고 `http://127.0.0.1:{port}/command`로 명령을 보냅니다.
Heartbeat 파일은 임시 파일에 먼저 쓴 뒤 원자적으로 교체하므로, 클라이언트가 발견 과정에서
반쯤 쓰인 JSON을 읽을 가능성을 줄입니다.

## 권장 Editor 설정

기본적으로 Unity는 창이 포커스를 잃으면 Editor 업데이트를 쓰로틀링할 수 있습니다. UnityBridge는
Unity API 작업을 Editor 메인 스레드에서 디스패치하므로, Editor가 백그라운드에 있으면 CLI 명령
처리가 지연될 수 있습니다.

백그라운드 응답성을 가장 안정적으로 유지하려면 다음처럼 설정하세요.

```text
Edit > Preferences > General > Interaction Mode > No Throttling
```

커넥터도 CLI 요청이 들어올 때마다 PlayerLoop 업데이트를 요청합니다. 그래도 안정적인 응답 시간을
위해 `No Throttling` 설정을 권장합니다.

## Standalone CLI

권장 설치는 최신 GitHub Release의 standalone `unity-bridge` 실행 파일을 내려받습니다.
따라서 대상 PC에 Python이 없어도 됩니다.

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1 | iex
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh | sh
```

## 특정 릴리스 설치

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.1.5
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.1.5
```

## 업데이트

```powershell
unity-bridge update --check
unity-bridge update
```

standalone 빌드에서는 `update`가 현재 OS용 릴리스 설치 스크립트를 다시 실행해 맞는 release
실행 파일을 내려받습니다. Unity Connector용 Git 패키지 URL도 함께 출력하지만, Unity 프로젝트의
`Packages/manifest.json`은 자동으로 수정하지 않습니다.

일반 CLI 명령에서는 하루에 한 번만 CLI 업데이트를 확인하고, 새 버전이 있을 때만 짧은 알림을
출력합니다. `--json` 출력과 `update` 명령 자체에서는 이 알림을 건너뜁니다.
건너뛰려면 `UNITY_BRIDGE_SKIP_UPDATE_CHECK=1` 환경변수를 설정하거나 `--no-update-check`를
붙이세요.

## Release asset

Standalone 설치는 GitHub Release에 현재 플랫폼과 맞는 asset이 있어야 합니다.

```text
unity-bridge-windows-amd64.exe
unity-bridge-linux-amd64
unity-bridge-linux-arm64
unity-bridge-darwin-amd64
unity-bridge-darwin-arm64
```

Windows 설치 스크립트는 이전 릴리스를 위해 `unity-bridge-windows-x64.exe` asset도 fallback으로
지원합니다.

## 버전 고정

tag를 배포한 뒤에는 Unity 패키지 URL 뒤에 tag를 붙여 고정할 수 있습니다.

```text
https://github.com/zjxps2007/UnityBridge.git?path=unity-bridge-connector#v0.1.5
```

## 로컬 설치 스크립트

```powershell
git clone https://github.com/zjxps2007/UnityBridge.git
cd UnityBridge
.\install.cmd
```

PowerShell 스크립트를 직접 실행하고 싶다면 현재 실행에만 Execution Policy를 우회할 수 있습니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```
