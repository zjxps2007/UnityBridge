# UnityBridge Python 패키지 모드

한국어 | [English](PYTHON_PACKAGE.md) | [README](../README.ko.md)

Python 패키지 모드는 `unity_bridge`를 Python 코드에서 직접 import해야 하는 개발용/프로그램 통합용
설치 방식입니다. 일반 CLI 사용자는 대상 PC에 Python이 필요 없는 standalone 설치를 권장합니다.

## 언제 사용하나

Python 패키지 모드는 이런 경우에 사용합니다.

- Python 프로그램이 UnityBridge를 내부 API처럼 호출해야 할 때
- shell 문자열 파싱 없이 Unity 호출과 다른 Python 로직을 함께 조합해야 할 때
- UnityBridge 자체를 개발하거나 테스트할 때

standalone 모드는 이런 경우에 적합합니다.

- 사용자가 `unity-bridge` 명령어만 필요할 때
- 대상 PC에 Python을 설치하고 싶지 않을 때
- 다른 도구에서 CLI 명령으로 호출할 때

## Git에서 설치

```powershell
python -m pip install --upgrade "git+https://github.com/zjxps2007/UnityBridge.git"
```

특정 tag를 설치하려면:

```powershell
python -m pip install --upgrade "git+https://github.com/zjxps2007/UnityBridge.git@v0.2.0"
```

## 설치 스크립트로 Python 패키지 모드 설치

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -PythonMode
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh | sh -s -- --python-mode
```

## 클론한 repo에서 실행

```powershell
git clone https://github.com/zjxps2007/UnityBridge.git
cd UnityBridge
python -m pip install -e .
```

설치하지 않고 모듈 경로로 실행:

```powershell
$env:PYTHONPATH=(Resolve-Path .\src).Path
python -m unity_bridge status
python -m unity_bridge instances
python -m unity_bridge tools
```

## import 사용 예시

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
Unity asset path로 정규화합니다. refresh/import 이후 안정적인 Unity `ready` heartbeat를
기다려야 한다면 `wait=True`를 사용하세요. 대기형 adapter 작업은 프로젝트 경로
기준으로 Unity를 다시 찾기 때문에, 도메인 리로드로 connector 포트가 바뀌어도 따라갈 수 있습니다.

## Raw client 사용

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

`UnityClient.wait_for_ready()`는 낮은 수준의 상태 대기 API로, 기본값에서는 기존 `ready`
heartbeat를 읽고 즉시 반환할 수 있습니다. 새로운 heartbeat와 0.5초 동안의 준비 상태를
확인하려면 `UnityBridgeAdapter.wait_for_ready()`를 사용하세요. 스크립트를 변경한 뒤에는
`bridge.refresh_assets(compile="request", wait=True)`로 작업을 요청하고 준비 완료를
기다리세요. 직접 동기화 조건을 지정할 때는 낮은 수준의 `after_timestamp`, `stable_sec`
인자를 사용할 수 있습니다.

## 업데이트

Python 패키지 설치에서는 `unity-bridge update`가 pip로 패키지를 다시 설치합니다. Unity Connector용
Git 패키지 URL도 함께 출력하지만, Unity 프로젝트의 `Packages/manifest.json`은 자동으로 수정하지
않습니다.

```powershell
unity-bridge update --check
unity-bridge update
unity-bridge update --ref v0.2.0
```
