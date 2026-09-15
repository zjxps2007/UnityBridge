# UnityBridge 설치

한국어 | [English](INSTALL.md) | [README](../README.ko.md)

이 문서는 standalone CLI 설치, Unity 패키지 버전 고정, 업데이트, release asset을 다룹니다.
Python 패키지 모드는 [PYTHON_PACKAGE.ko.md](PYTHON_PACKAGE.ko.md)에 따로 정리했습니다.

## Unity 패키지

Unity Editor에서 `Window > Package Manager > + > Add package from git URL...`을 열고
아래 URL을 붙여넣습니다.

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#main
```

Connector는 Unity 2020.3 LTS부터 Unity 6까지 지원합니다.

이 URL은 `main` 브랜치를 기준으로 설치합니다. 이후 새 버전이 `main`에 올라오면
Package Manager의 `Update` 버튼으로 최신 커밋을 받을 수 있습니다. 특정 버전에 고정하고
싶다면 아래의 [버전 고정](#버전-고정) 방식을 사용하세요.

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

커넥터는 CLI 요청이 들어오면 Editor 메인 스레드에 큐 처리를 요청하고, 겹치는 깨우기 요청을
하나로 모읍니다. 정기적인 Editor 업데이트 루프도 큐를 처리합니다. 안정적인 응답 시간을 위해
`No Throttling` 설정을 권장합니다.

## Standalone CLI

권장 설치는 최신 GitHub Release의 standalone `unity-bridge` 묶음을 내려받습니다.
대상 PC에 Python을 따로 설치할 필요는 없습니다.
새 빌드는 PyInstaller의 폴더 배포 방식을 사용해 설치할 때 한 번 압축을 풉니다.
매 명령 실행마다 런타임을 다시 풀지 않습니다. v0.2.1 이하의 단일 실행 파일도
설치기의 이전 형식 지원 경로로 설치할 수 있습니다.

명령의 설치 경로는 유지됩니다. 실행 파일 옆의 `_unity_bridge_runtime_<build-id>`
폴더도 필요하므로 실행 파일만 따로 옮기지 마세요. 업데이트는 내려받은 묶음을 검증한 뒤
실행 파일을 교체합니다. 실행 중인 이전 명령을 위해 이전 런타임 폴더는 보관합니다.
UnityBridge CLI 프로세스를 모두 종료한 뒤 사용하지 않는 런타임 폴더를 정리할 수 있지만,
현재 설치된 빌드의 폴더는 유지해야 합니다. `update`는 사용자가 지정한 설치 경로도 유지합니다.

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
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.2.1
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.2.1
```

## 프리릴리스

`v0.2.2-rc.2`에는 `codex/faster-startup`의 시작 속도 개선과 CLI 리팩토링이 포함됩니다.
프리릴리스는 버전을 직접 지정해야 설치되며, 기본 설치 명령은 최신 정식 릴리스를 선택합니다.
CLI와 Connector를 같은 태그로 설치하세요.

RC2는 RC1 패키지를 설치해도 `Connector: 0.2.1`로 표시되던 문제를 수정합니다.
CLI가 이미 RC1이면 `unity-bridge update --ref v0.2.2-rc.2`를 실행하고,
Unity Package Manager URL도 아래의 RC2 태그로 변경하세요. Unity 컴파일이 끝나면
`unity-bridge status`에 `Connector: 0.2.2-rc.2`가 표시되어야 합니다.

**프리릴리스 태그의 설치 스크립트**를 사용하세요. v0.2.1의 설치기와 업데이터는
기존 단일 실행 파일 형식을 사용하므로 이번 압축 번들을 직접 설치할 수 없습니다.

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

Unity Package Manager Git URL:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.2.2-rc.2
```

`unity-bridge update --check --ref v0.2.2-rc.2`로 설치 버전을 확인할 수 있습니다.
Python 패키지 정보에 표시되는 `0.2.2rc2`와 `0.2.2-rc.2`는 같은 버전입니다.
v0.2.2-rc.1부터는 `update --ref`로 프리릴리스를 지정하면 해당 태그의 설치기를 사용합니다.
버전 지정 없는 `unity-bridge update`는 정식 릴리스를 선택하므로 더 오래된 정식 버전으로
바뀔 수 있습니다. 두 구성 요소를 v0.2.1로 되돌리려면 `unity-bridge update --ref v0.2.1`을
실행하고 Connector URL도 `#v0.2.1`로 변경하세요.

## 업데이트

```powershell
unity-bridge update --check
unity-bridge update
```

standalone 빌드에서는 `update`가 현재 OS용 릴리스 설치 스크립트를 다시 실행해 맞는 release
실행 파일을 내려받습니다. Unity Connector용 Git 패키지 URL도 함께 출력하지만, Unity 프로젝트의
`Packages/manifest.json`은 자동으로 수정하지 않습니다.

실시간 `wait-ready` 확인을 사용하려면 CLI와 Unity Connector를 함께 업데이트하세요.
구형 Connector는 저장된 `ready` heartbeat로 대신 성공하지 않고 업데이트 안내 오류를
반환합니다. 미출시 브랜치를 시험하려면 [브랜치에서 설치](PYTHON_PACKAGE.ko.md#브랜치에서-설치)를
따라 두 구성 요소를 같은 Git 브랜치에서 설치하세요. standalone 설치기는 릴리스 파일을
내려받습니다.

일반 CLI 명령에서는 하루에 한 번만 CLI 업데이트를 확인하고, 새 버전이 있을 때만 짧은 알림을
출력합니다. `--json` 출력과 `update` 명령 자체에서는 이 알림을 건너뜁니다.
건너뛰려면 `UNITY_BRIDGE_SKIP_UPDATE_CHECK=1` 환경변수를 설정하거나 `--no-update-check`를
붙이세요.

## Release asset

Standalone 설치는 GitHub Release에 현재 플랫폼과 맞는 asset이 있어야 합니다.

```text
unity-bridge-windows-amd64.zip
unity-bridge-linux-amd64.tar.gz
unity-bridge-linux-arm64.tar.gz
unity-bridge-darwin-amd64.tar.gz
unity-bridge-darwin-arm64.tar.gz
```

압축 파일에는 `unity-bridge/` 폴더가 들어 있습니다. 수동 설치 시 폴더 전체를 풀고 그 안의
실행 파일을 사용하세요. 설치기는 압축 묶음을 우선 선택하고 이전 릴리스의 단일 실행 파일
(Windows는 `.exe`, macOS/Linux는 확장자 없음)도 지원합니다. Windows의 이전
`unity-bridge-windows-x64.exe` 이름도 지원합니다.

## 버전 고정

tag를 배포한 뒤에는 Unity 패키지 URL 뒤에 tag를 붙여 고정할 수 있습니다.

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.2.1
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
