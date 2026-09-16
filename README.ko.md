# UnityBridge

한국어 | [English](README.md)

UnityBridge는 로컬 HTTP connector를 통해 Unity Editor를 제어하는 standalone CLI,
Python-native 클라이언트, Unity 패키지입니다.

CLI는 `~/.unity-bridge/instances/*.json` heartbeat 파일로 실행 중인 Unity Editor를
발견하고, 대상 Editor를 선택한 뒤 사용 가능한 로컬 호스트를 거치거나
`http://127.0.0.1:{port}/command`로 직접 JSON 명령을 보냅니다.

새 standalone 빌드는 실행 파일과 런타임을 묶은 압축 파일로 배포하며, 설치할 때 한 번
압축을 풉니다. 실행 파일 옆의 런타임 폴더를 함께 유지하세요. 설치기는 v0.2.1 이하의
단일 실행 파일도 지원합니다. 자세한 내용은 [설치와 업데이트](docs/INSTALL.ko.md#standalone-cli)를 참고하세요.

[v0.2.3 정식 릴리스](https://github.com/zjxps2007/UnityBridge/releases/tag/v0.2.3)는
평상시 0.5초 갱신 주기를 유지하면서 Heartbeat 상태 변화를 더 빠르게 반영합니다.
v0.2.2의 시작 속도 개선과 Connector 버전 표시 수정도 포함합니다.
[v0.2.3 업그레이드 안내](docs/INSTALL.ko.md#v023으로-업그레이드)에 따라
CLI와 Unity Connector를 함께 업데이트하세요. 기본 설치는 최신 정식 릴리스를 선택합니다.

## 미출시: 독립 호스트와 컴파일러

이 브랜치는 **0.3.0-alpha.1**을 개발하고 있으며, 현재 공개된 정식 버전은
**v0.2.3**입니다. 아래 설치 명령은 정식 버전을 설치하므로 미출시 기능을 포함하지
않습니다. 이 브랜치를 빌드하려면 [로컬 개발 안내](docs/DEVELOPMENT.ko.md#독립-호스트와-컴파일러)를 참고하세요.

새 호스트는 Unity 도메인 밖에서 실행되어 재컴파일 중에도 아직 전달하지 않은 요청을
보관합니다. 동봉된 Roslyn 워커가 C# 코드를 컴파일하고, Unity가 결과 DLL을 불러와
메인 스레드에서 Unity API를 실행합니다. 프로젝트 스크립트를 바꾸면 Unity 자체의
컴파일과 도메인 리로드는 여전히 필요합니다.

- Unity가 등록된 호스트를 비동기로 시작하고 프로젝트 참조로 컴파일러를 미리 준비합니다.
  실행 중인 Editor와 처리할 요청이 모두 없으면 30초 뒤 종료합니다.
- 반복 코드는 컴파일 준비 정보를 재사용하되 호출마다 새 assembly identity로 emit하고
  다시 실행합니다. 실행 결과나 정적 상태를 캐시하지 않습니다.
- Connector의 네트워크 입출력은 백그라운드에서 처리합니다. 도구 호출과 결과
  직렬화는 Unity 메인 스레드에서 수행합니다.
- `--backend auto|host|legacy`로 경로를 선택합니다. `auto`는 준비된 호환 호스트를
  사용하고, 없으면 기존 직접 연결을 사용합니다. `Host: running`은 Unity의 준비
  완료를 뜻하지 않으며, `wait-ready`는 계속 Unity의 실제 응답을 확인합니다.

호스트 포함 빌드는 .NET 런타임을 동봉하므로 사용자 PC에 SDK를 설치할 필요가 없습니다.
다만 [.NET 10 지원 운영체제](https://github.com/dotnet/core/blob/main/release-notes/10.0/supported-os.md)가
필요하며, 이는 Connector의 Unity 버전 호환성과 별개입니다.
[실행 경로](docs/COMMANDS.ko.md#실행-경로)와
[설치 조건](docs/INSTALL.ko.md#미출시-호스트-포함-빌드)을 확인하세요.
[최초 검증 보고서](docs/HOST_VALIDATION.ko.md)는 v0.2.3과 비교한 실측 응답 시간,
첫 시작 비용, 메모리 사용량과 검증 범위를 기록합니다. 이후 개발 브랜치의 변경은
[추가 최적화 보고서](docs/HOST_OPTIMIZATION.ko.md)를 참고하세요.

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

v0.2.3은 평상시 heartbeat 갱신 간격을 0.5초로 유지합니다.
서버 시작과 일시정지·재개 이벤트는 즉시 기록하고, 그 외 감지한 상태 변화는 다음
Editor 업데이트에 기록합니다. `Heartbeat age`는 저장된 상태의 경과 시간이며,
Editor가 바쁘거나 백그라운드에서 느리게 갱신되면 더 길어질 수 있습니다.

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
