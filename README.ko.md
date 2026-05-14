# UnityBridge

한국어 | [English](README.md)

UnityBridge는 로컬 HTTP connector를 통해 Unity Editor를 제어하는
Python-native 클라이언트와 Unity 패키지입니다.

Python 클라이언트는 별도의 CLI 바이너리를 호출하지 않습니다. 대신 Unity Editor 안에서 실행되는
connector와 직접 통신합니다.

1. `~/.unity-bridge/instances/*.json` heartbeat 파일을 읽습니다.
2. 포트, 정확한 프로젝트 경로, 경로 suffix, 현재 작업 경로, 최신 heartbeat를 기준으로 실행 중인 Unity Editor를 선택합니다.
3. `http://127.0.0.1:{port}/command`로 JSON 요청을 보냅니다.

## 빠른 시작

### 1. Unity 패키지 설치

Unity Editor에서 `Window > Package Manager > + > Add package from git URL...`을 열고
아래 URL을 붙여넣습니다.

```text
https://github.com/zjxps2007/UnityBridge.git?path=unity-bridge-connector
```

Connector는 Unity Editor가 열릴 때 자동으로 시작됩니다. 실행 중에는
`~/.unity-bridge/instances/` 아래에 heartbeat 파일을 기록합니다. Python 클라이언트는 이 파일을
읽어 Unity Editor를 발견하고 `http://127.0.0.1:{port}/command`로 명령을 보냅니다.
Heartbeat 파일은 임시 파일에 먼저 쓴 뒤 원자적으로 교체하므로, 클라이언트가 발견 과정에서
반쯤 쓰인 JSON을 읽을 가능성을 줄입니다.

### 권장 Editor 설정

기본적으로 Unity는 창이 포커스를 잃으면 Editor 업데이트를 쓰로틀링할 수 있습니다. UnityBridge는
Unity API 작업을 Editor 메인 스레드에서 디스패치하므로, Editor가 백그라운드에 있으면 CLI 명령
처리가 지연될 수 있습니다.

백그라운드 응답성을 가장 안정적으로 유지하려면 다음처럼 설정하세요.

```text
Edit > Preferences > General > Interaction Mode > No Throttling
```

커넥터도 CLI 요청이 들어올 때마다 PlayerLoop 업데이트를 요청합니다. 그래도 가장 안정적인 응답
시간을 위해 `No Throttling` 설정을 권장합니다.

### 2. Python 클라이언트 설치

```powershell
python -m pip install --upgrade "git+https://github.com/zjxps2007/UnityBridge.git"
```

설치 후에는 Python CLI를 기본 브랜치 기준으로 업데이트할 수 있습니다.

```powershell
unity-bridge update
```

PowerShell 설치 스크립트를 바로 실행할 수도 있습니다.

```powershell
irm https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1 | iex
```

```powershell
git clone https://github.com/zjxps2007/UnityBridge.git
cd UnityBridge
.\install.cmd
```

PowerShell 스크립트를 직접 실행하고 싶다면 현재 실행에만 Execution Policy를 우회할 수 있습니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

### 3. 연결 확인

Unity 프로젝트를 열어둔 상태에서 실행합니다.

```powershell
unity-bridge status
unity-bridge instances
unity-bridge tools
```

## 버전 고정

tag를 배포한 뒤에는 Unity 패키지 URL 뒤에 tag를 붙여 고정할 수 있습니다.

```text
https://github.com/zjxps2007/UnityBridge.git?path=unity-bridge-connector#v0.1.1
```

## CLI 사용법

설치 후 명령어:

```powershell
unity-bridge status
unity-bridge instances
unity-bridge tools
```

같은 CLI를 `unity_bridge` 명령어로도 사용할 수 있습니다.

다른 프로그램이나 에이전트가 결과를 파싱해야 할 때만 `--json` 옵션을 붙입니다.

```powershell
unity-bridge --json instances
unity-bridge --json console --count 20
```

설치하지 않고 모듈 경로로 실행:

```powershell
$env:PYTHONPATH='D:\Code\Codex\CP\UnityBridge\src'
python -m unity_bridge status
python -m unity_bridge instances
python -m unity_bridge tools
```

## 명령어 레퍼런스

전체 CLI 명령어, 공통 옵션, custom tool 직접 호출 방식은 [COMMANDS.ko.md](COMMANDS.ko.md)에
분리해서 정리했습니다.

## Python 사용 예시

```python
from unity_bridge import UnityBridgeAdapter

bridge = UnityBridgeAdapter(project=r"D:\UnityProjects\MyGame")

bridge.refresh_assets()
bridge.refresh_assets(paths=[r"D:\UnityProjects\MyGame\Assets\Scripts\Player.cs"], wait=True)
logs = bridge.read_console(count=50, types=["error", "warning", "log"])
tests = bridge.run_tests(mode="EditMode")
play = bridge.editor_play(wait=True)
```

`refresh_assets()`에 경로를 넘기지 않으면 Unity 전체 에셋 새로고침을 실행합니다.
`paths`를 넘기면 해당 asset path만 import하며, Unity 프로젝트 내부의 절대 경로는 connector가
Unity asset path로 정규화합니다. Agent 워크플로에서 refresh/import 이후 안정적인 Unity `ready`
heartbeat를 기다려야 한다면 `wait=True`를 사용하세요. 대기형 adapter 작업은 프로젝트 경로
기준으로 Unity를 다시 찾기 때문에, 도메인 리로드로 connector 포트가 바뀌어도 따라갈 수 있습니다.

adapter는 의도적으로 얇은 계층입니다. 쓰기 쉬운 Python 메서드를 connector command로 매핑하지만,
allowlist나 denylist 같은 정책 계층은 추가하지 않습니다. connector params를 정확히 지정해야 하면
`UnityClient`로 raw 호출을 사용할 수 있습니다.

```python
from unity_bridge import UnityClient

client = UnityClient(project=r"D:\UnityProjects\MyGame")
status = client.status()
print(status.state, status.port)

result = client.call("console", {"count": 20, "type": "error,warning"})
print(result.success, result.message, result.data)
```

## 테스트 실행

```powershell
git clone https://github.com/zjxps2007/UnityBridge.git
cd UnityBridge
python -m pip install -e .
python -m unittest discover -s tests
```

## 라이선스

UnityBridge는 MIT License로 배포됩니다.

제3자 라이선스 고지는 `NOTICE.md`를 확인하세요.
