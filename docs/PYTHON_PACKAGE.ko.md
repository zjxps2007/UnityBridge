# UnityBridge Python 패키지 모드

한국어 | [English](PYTHON_PACKAGE.md) | [README](../README.ko.md)

Python 패키지 모드는 `unity_bridge`를 Python 코드에서 직접 import해야 하는 개발용/프로그램 통합용
설치 방식입니다. 일반 CLI 사용자는 대상 PC에 Python이 필요 없는 standalone 설치를 권장합니다.

정식 버전은 **v0.3.0**이며 독립 호스트 옵션을 포함합니다.
Python 패키지만 설치하면 .NET이나 Roslyn 워커를 다운로드하지 않습니다.

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
python -m pip install --upgrade "git+https://github.com/zjxps2007/UnityBridge.git@v0.3.0"
```

Unity Package Manager에도 같은 태그의 URL을 사용합니다.

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.3.0
```

이 명령은 컴파일러 런타임을 설치하지 않습니다. 일치하는 호스트가 등록되지 않으면
`auto`는 직접 연결을 유지합니다. 독립 컴파일러를 쓰려면
[정식 standalone 묶음](INSTALL.ko.md#v030으로-업그레이드)도 설치하거나
[개발 안내](DEVELOPMENT.ko.md#독립-호스트와-컴파일러)에 따라 빌드·등록하세요.

## 브랜치에서 설치

릴리스 전 변경을 시험하려면 Python CLI와 Unity Connector를 같은 Git 브랜치에서
설치하세요. 아래 예시는 통합된 `main`을 사용합니다. 다른 개발 브랜치를
시험하려면 두 URL의 브랜치를 함께 바꾸세요. 미푸시 변경은 로컬 체크아웃에서 설치합니다.

Windows PowerShell:

```powershell
python -m pip install --upgrade --force-reinstall "git+https://github.com/zjxps2007/UnityBridge.git@main"
```

macOS/Linux에서는 UnityBridge용 Python 환경에서 실행합니다.

```sh
python3 -m pip install --upgrade --force-reinstall "git+https://github.com/zjxps2007/UnityBridge.git@main"
```

Unity Package Manager에는 같은 브랜치의 Git URL을 사용합니다.

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#main
```

브랜치가 갱신되면 CLI 설치 명령을 다시 실행하고 Unity 패키지도 업데이트하세요. 브랜치의
여러 커밋이 같은 패키지 버전을 사용할 수 있으므로 버전 번호만으로는 설치된 커밋을
구분할 수 없습니다. `python -m pip freeze`(macOS/Linux에서는 `python3`)와 Unity 프로젝트의
`Packages/packages-lock.json`에서 Git 참조와 리비전을 확인하세요. standalone 설치기는
이 브랜치를 선택하는 대신 릴리스 파일을 내려받습니다.

이 과정은 Python 클라이언트와 Connector를 갱신하며 외부 컴파일러 런타임은 설치하지
않습니다. 등록된 호환 호스트가 없으면 `auto`는 기존 직접 연결을 사용합니다. 독립
컴파일러를 시험하려면 [개발 안내](DEVELOPMENT.ko.md#독립-호스트와-컴파일러)에 따라
빌드·등록하거나, 같은 소스에서 만든 로컬 standalone 설치의 등록된 호스트를 사용하세요.

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

위 명령은 기본 Python Git 소스를 설치합니다. Python 모드의 `-Version`·`--version`은
패키지 버전을 고정하지 않습니다. 위의 정확한 pip 태그를 사용하거나
`-PackageSpec`·`--package-spec`에 해당 Git 패키지 URL 전체를 지정하세요.

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

실행 경로는 `UnityClient`에서 지정합니다. 명시한 값이 `UNITY_BRIDGE_BACKEND`보다
우선하며, 둘 다 없으면 `auto`입니다. 같은 경로를 adapter에서도 사용하려면 해당
클라이언트를 전달합니다.

```python
from unity_bridge import UnityBridgeAdapter, UnityClient

client = UnityClient(project=r"D:\UnityProjects\MyGame", backend="host")
bridge = UnityBridgeAdapter(client=client)
result = client.call("exec", {"code": "return 42;"})
if result.completion_unknown:
    print("실행 완료를 확인할 수 없습니다. 재시도 전 Unity 상태를 확인하세요.")
```

`host`는 등록되어 실행 중인 호환 서비스를 요구하고, `legacy`는 Connector에 직접
연결합니다. `auto`는 사용 가능한 호스트를 선택하며, 요청 전달 전일 때만 직접 연결로
전환할 수 있습니다. `exec`에 `csc`나 `dotnet`을 명시하면 기존 컴파일러 경로를 사용합니다.
전달 이후 호스트 응답이 유실되면 완료 여부가 불명확한 결과를 반환하며 직접 경로로
자동 재실행하지 않습니다. `status()`는 계속 저장된 Unity 상태를 읽고 호스트 정보를
별도로 제공합니다. 서비스가 실행 중인 것만으로 Unity의 준비 완료를 판단하지 않습니다.

`UnityClient.wait_for_ready()`는 낮은 수준의 상태 대기 API로, 기본값에서는 기존 `ready`
heartbeat를 읽고 즉시 반환할 수 있습니다. 고정 안정화 대기 없이 에디터의 현재 상태를
직접 확인하려면 `UnityBridgeAdapter.wait_for_ready()`를 사용하세요. 별도의 안정화 시간이
필요한 작업에서만 선택 인자 `stable_sec`를 지정하세요. 직접 확인 기능을 쓰려면 Python CLI와
Unity Connector를 함께 업데이트해야 합니다. 스크립트를 변경한 뒤에는
`bridge.refresh_assets(compile="request", wait=True)`로 작업을 요청하고 준비 완료를
기다리세요. 직접 동기화 조건을 지정할 때는 낮은 수준의 `after_timestamp`, `stable_sec`
인자를 사용할 수 있습니다.

## 업데이트

### RC2 대기 개선

RC2의 `refresh_assets`, `reserialize_assets`, `editor_play`,
`editor_stop`은 `stable_sec=None` / `poll_interval_sec=None`을 자동 기본값으로
사용합니다. 작업 ID가 있으면 해당 작업의 완료를 50ms마다 직접 확인하고 추가
안정화 시간을 두지 않습니다. 작업 ID가 없으면 기존 0.5초 조회·안정화 기본값을
사용합니다. 재생 상태에는 ready 안정화 시간을 적용하지 않습니다. 명시한 숫자 인자는
기본값보다 우선합니다. 작업 기록 유실·프로세스 교체·취소 시 변경 명령을 재실행하지
않고 오류로 보고합니다. 빠른 완료 확인에는 같은 브랜치의 Connector가 필요합니다.

반복 호출에서는 한 Python 프로세스에서 `UnityClient` 또는 `UnityBridgeAdapter`를
재사용하세요. 다른 언어에서는 [JSONL CLI 세션](COMMANDS.ko.md#rc2-연속-명령과-작업-완료-확인)을
사용하면 명령마다 CLI를 시작하는 비용을 줄일 수 있습니다. 공개 패키지 import는
기존과 호환됩니다.

### 패키지 업데이트

Python 패키지 설치에서는 `unity-bridge update`가 pip로 패키지를 다시 설치합니다. Unity Connector용
Git 패키지 URL도 함께 출력하지만, Unity 프로젝트의 `Packages/manifest.json`은 자동으로 수정하지
않습니다.

```powershell
unity-bridge update --check
unity-bridge update
unity-bridge update --ref v0.3.0
```
