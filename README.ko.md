# UnityBridge

한국어 | [English](README.md)

UnityBridge는 로컬 HTTP connector를 통해 Unity Editor를 제어하는 standalone CLI,
Python-native 클라이언트, Unity 패키지입니다.

CLI는 `~/.unity-bridge/instances/*.json` heartbeat 파일로 실행 중인 Unity Editor를
발견하고, 대상 Editor를 선택한 뒤 `http://127.0.0.1:{port}/command`로 JSON 명령을
보냅니다.

새 standalone 빌드는 실행 파일과 런타임을 묶은 압축 파일로 배포하며, 설치할 때 한 번
압축을 풉니다. 실행 파일 옆의 런타임 폴더를 함께 유지하세요. 설치기는 v0.2.1 이하의
단일 실행 파일도 지원합니다. 자세한 내용은 [설치와 업데이트](docs/INSTALL.ko.md#standalone-cli)를 참고하세요.

`main` 병합 전에 시작 속도 개선을 시험하려면 [v0.2.2-rc.2 프리릴리스](docs/INSTALL.ko.md#프리릴리스)를
설치하세요. 아래 빠른 시작 명령은 정식 릴리스를 설치합니다.

## 빠른 시작

### 1. Unity 패키지 설치

Unity Editor에서 `Window > Package Manager > + > Add package from git URL...`을 열고
아래 URL을 붙여넣습니다.

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#main
```

Connector는 Unity 2020.3 LTS부터 Unity 6까지 지원합니다.

이 URL은 `main` 브랜치를 기준으로 설치합니다. 이후 새 버전이 `main`에 올라오면
Package Manager의 `Update` 버튼으로 갱신할 수 있습니다.

### 2. CLI 설치

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1 | iex
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh | sh
```

### 3. 연결 확인

Unity 프로젝트를 열어둔 상태에서 실행합니다.

```powershell
unity-bridge status
unity-bridge tools
```

### 권장 Editor 설정

백그라운드 응답성을 더 안정적으로 유지하려면 아래 설정을 권장합니다.

```text
Edit > Preferences > General > Interaction Mode > No Throttling
```

자세한 설명은 [docs/INSTALL.ko.md](docs/INSTALL.ko.md#권장-editor-설정)에 정리했습니다.

## 기본 명령어

```powershell
unity-bridge instances
unity-bridge status
unity-bridge wait-ready --timeout-sec 300
unity-bridge tools
```

`status`는 저장된 heartbeat를 읽고, `wait-ready`는 Editor에 현재 상태를 직접 확인해
고정 0.5초 안정화 대기 없이 `ready` 응답을 받으면 완료됩니다. 직접 상태 확인을 쓰려면
CLI와 Unity Connector를 함께 업데이트하세요. 브랜치 빌드는
[Python 패키지 모드](docs/PYTHON_PACKAGE.ko.md#브랜치에서-설치)의 안내에 따라
두 구성 요소를 같은 브랜치에서 설치합니다. 스크립트를 수정한 뒤에는 컴파일을 요청하고
완료를 기다리세요.

```powershell
unity-bridge console --count 50
unity-bridge refresh --path Assets/Scripts/Player.cs --compile request --wait
unity-bridge test --mode EditMode
```

단독 `wait-ready`는 컴파일을 요청하지 않으며, Editor 응답 이후 시작되는 별도 작업까지
기다리지 않습니다. 준비 확인과 새로고침 옵션은 [CLI 명령어](docs/COMMANDS.ko.md)를
확인하세요.

```powershell
unity-bridge editor play --wait
unity-bridge editor stop --wait
unity-bridge exec --file .\query.cs
```

다른 프로그램이 결과를 파싱해야 할 때는 `--json`을 붙입니다.

```powershell
unity-bridge --json status
unity-bridge --json console --count 20
```

Unity 쪽 custom tool은 이름으로 직접 호출할 수 있습니다.

```powershell
unity-bridge my_custom_tool --key value
unity-bridge call my_custom_tool --params '{"key":"value"}'
```

CLI 업데이트:

```powershell
unity-bridge update --check
unity-bridge update
```

## 문서

- [릴리스 노트](docs/RELEASE_NOTES.md): 현재 릴리스의 변경 사항, 업데이트 요구 사항, 검증 결과.
- [docs/INSTALL.ko.md](docs/INSTALL.ko.md): standalone 설치, 버전 고정, 업데이트, release asset.
- [docs/COMMANDS.ko.md](docs/COMMANDS.ko.md): CLI 명령어, 공통 옵션, custom tool 호출.
- [docs/PYTHON_PACKAGE.ko.md](docs/PYTHON_PACKAGE.ko.md): 개발 및 Python 직접 통합용 패키지 모드.
- [docs/DEVELOPMENT.ko.md](docs/DEVELOPMENT.ko.md): CLI 모듈별 역할, 명령 변경 방법, 회귀 검사.

## 라이선스

UnityBridge는 MIT License로 배포됩니다.

제3자 라이선스 고지는 [NOTICE.md](NOTICE.md)를 확인하세요.
