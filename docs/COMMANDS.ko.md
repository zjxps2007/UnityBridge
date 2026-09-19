# UnityBridge 명령어

한국어 | [English](COMMANDS.md) | [README](../README.ko.md)

이 문서는 `unity-bridge` CLI에서 지금 사용할 수 있는 명령어를 정리합니다.
실행 경로 옵션은 **v0.3.0-rc.2** 기능입니다. 정식 **v0.2.3**은 기존 Connector
직접 연결을 사용합니다. 같은 태그의 설치기와 Unity 패키지는
[RC 설치 안내](INSTALL.ko.md#프리릴리스)를 참고하세요.

## RC2: 연속 명령과 작업 완료 확인

다음 기능은 RC2에 포함합니다.
`unity-bridge --project <경로> --no-update-check session`을 시작하고 stdin을
열어 둔 상태에서 한 줄에 JSON 요청 하나씩 보냅니다.

```json
{"id":1,"args":["status"]}
{"id":2,"args":["exec","--code","return 42;"]}
```

명령은 순서대로 실행되며 각 응답은 완료 즉시 한 줄로 출력합니다.

```json
{"id":2,"exit_code":0,"result":{"success":true,"message":"...","data":42},"error":null}
```

`result`는 기존 명령의 JSON 출력이고 `error`는 stderr 또는 `null`입니다.
ID는 문자열·정수·null을 지원하고 EOF에서 종료합니다. 잘못된 요청은 해당 줄만
종료 코드 2로 응답하고 다음 요청을 계속 처리합니다. 입력 한 줄은 문자 수 기준
1 MiB로 제한합니다. 프로젝트·포트·실행 경로·시간 제한·instances 디렉터리는
세션 옵션을 상속하며 요청별로 덮어쓸 수 있습니다. Unity 정보는 요청마다 다시 찾습니다.
세션 안의 `session`, `update`, `_host`, `--stdin`은 거부합니다. C# 입력은
`exec --code` 또는 `--code-file`을 사용하세요. 요청은 항상 JSON 출력이므로
기존 JSON 명령의 업데이트 알림 생략 규칙을 따릅니다. 일반 CLI의 업데이트 동작은 같습니다.

같은 브랜치의 Connector에서는 `refresh --wait`, `reserialize --wait`,
`editor play|stop --wait`가 반환된 작업 ID의 완료를 Unity에 직접 확인합니다.
기본 조회 간격은 50ms이며 별도의 안정화 시간을 더하지 않습니다. 컴파일은 필요한
도메인 리로드까지, 재생·정지는 해당 상태 이벤트까지 기다립니다. 이전 `ready`
기록만으로 다른 작업의 완료를 판단하지 않습니다. 작업 기록 유실·취소는 오류로
보고하며 명령을 재실행하지 않습니다. 작업 ID가 없으면 기존 Heartbeat 대기와
ready 상태의 0.5초 안정화 방식을 유지합니다. 명시한 `--stable-sec`도 유지하며,
editor/reserialize에서는 `--poll-interval-sec`를 지정할 수 있습니다.
독립 `wait-ready`와 하위 Python API의 스냅샷 판정 의미는 바꾸지 않았습니다.
직접 확인 요청은 전체 대기 제한 안에서 한 번에 최대 1초만 기다립니다. 리로드 전
listener의 연결이 전체 시간을 소모하지 않도록 하며, 재시도하는 것은 상태 조회뿐입니다.

## RC2 이후 개발 변경

RC2 이후 개발 변경은 세션·호스트 HTTP 연결을 재사용하고 결과 객체를 한 번만
직렬화합니다. 일반 `console`, `tools`, `wait-ready`, `exec`도 상주 호스트의 경량
경로를 사용할 수 있습니다. 스냅샷 명령은 전달 경로의 지연 기준을 통과하지 못해
기본적으로 로컬 처리합니다. [측정 결과](PYTHON_STARTUP.ko.md)를 참고하세요.
연속 요청에서는 세션 하나를 유지하고 각 응답을 받은 뒤 다음 요청을 보냅니다.

```python
import json
import subprocess

with subprocess.Popen(
    ["unity-bridge", "--project", "D:/UnityProjects/MyGame", "--no-update-check", "session"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
) as session:
    for request in ({"id": 1, "args": ["console", "--count", "5"]},
                    {"id": 2, "args": ["exec", "--code", "return 42;"]}):
        session.stdin.write(json.dumps(request) + "\n")
        session.stdin.flush()
        response = json.loads(session.stdout.readline())
        assert response["id"] == request["id"]
        print(response)
    session.stdin.close()
```

장기 실행 Python 프로그램은 `with UnityClient(...) as client:` 또는
`client.close()`로 연결을 해제할 수 있습니다. Unity 탐색은 요청마다 수행합니다.

## 기본 형태

```powershell
unity-bridge <command> [options]
unity_bridge <command> [options]
```

`unity_bridge` 명령어는 `unity-bridge`와 같은 CLI입니다.

공통 옵션은 명령어 앞이나 뒤에 붙일 수 있습니다.

```powershell
unity-bridge --project D:\UnityProjects\MyGame status
unity-bridge status --project D:\UnityProjects\MyGame
unity-bridge --port 8090 console --count 20
unity-bridge --json console --count 20
```

## 공통 옵션

| 옵션 | 설명 |
|------|------|
| `--project PATH_OR_TEXT` | 정확한 프로젝트 경로, 경로 suffix, 또는 정확한 프로젝트 폴더 이름으로 Unity 인스턴스를 선택합니다. |
| `--port PORT` | 포트 번호로 Unity 인스턴스를 선택합니다. |
| `--backend auto\|host\|legacy` | 호스트 또는 Connector 직접 연결을 선택합니다. 기본값은 `UNITY_BRIDGE_BACKEND`, 미설정 시 `auto`입니다. |
| `--timeout-ms MS` | HTTP 요청 타임아웃입니다. 기본값은 `120000`입니다. |
| `--instances-dir PATH` | 기본 `~/.unity-bridge/instances` 대신 다른 heartbeat 폴더를 사용합니다. |
| `--json` | 결과를 JSON으로 출력합니다. 다른 프로그램이 파싱할 때 사용합니다. |
| `--no-update-check` | 이번 실행에서 자동 일일 업데이트 알림을 건너뜁니다. |

`--project`는 정확한 프로젝트 경로, 입력 경로가 프로젝트 내부인지 여부, `UnityProjects/MyGame`이나
`MyGame` 같은 경로 세그먼트 suffix를 확인합니다. `Game`이 `GamePrototype`에 매칭되는 식의 부분
문자열 자동 선택은 하지 않습니다. suffix가 여러 Unity 인스턴스에 동시에 매칭되면 임의 선택하지 않고
에러를 반환합니다. 자동화 연동에서는 전체 프로젝트 경로나 `--port` 사용을 권장합니다.

## 실행 경로

```powershell
unity-bridge --backend host exec --code "return 42;"
unity-bridge --backend legacy console --count 20
```

- `auto`: 선택한 Unity 프로젝트와 연결을 확인한 호환 호스트를 사용합니다. 없으면
  요청을 전달하기 전에 기존 직접 연결을 선택합니다.
- `host`: 호스트가 없으면 오류를 반환합니다. `status`처럼 파일 상태만 읽는 명령은
  계속 파일을 사용하며, 옵션 때문에 Unity에 새 요청을 보내지 않습니다.
- `legacy`: Connector에 직접 연결합니다. `exec --csc`나 `--dotnet`을 명시한 경우도
  `--backend host` 여부와 관계없이 이 경로를 사용합니다.

명시한 옵션은 `UNITY_BRIDGE_BACKEND`보다 우선합니다. `--port`는 계속 Unity의 포트를
선택합니다. 호스트 경로에는 등록된 컴파일러 묶음과 호환 Connector가 필요합니다.
Python만 설치한 경우에는 이미 등록된 호환 호스트가 없다면 직접 연결을 사용합니다.

호스트는 프로젝트별 명령 순서를 유지하고, 아직 Unity에 전달하지 않은 명령만 리로드
종료까지 기다립니다. 대기·컴파일·전달 과정에 원래 요청의 제한 시간을 적용합니다.
이미 전달한 명령의 응답이 유실되면 `data.completion`은 `unknown`이며 완료 여부를
확인할 수 없다는 뜻입니다. 변경 명령을 다시 실행하기 전 Editor 상태를 확인하세요.
클라이언트는 다른 경로로 자동 재실행하지 않습니다. `not_started`는 명령이 실행되기
전에 거부되었음을 뜻합니다.

## 명령어 목록

| 명령어 | 용도 |
|--------|------|
| `unity-bridge instances` | 발견된 Unity Editor 인스턴스 목록을 출력합니다. |
| `unity-bridge status` | 선택된 Unity Editor 인스턴스 상태를 출력합니다. |
| `unity-bridge tools` | Unity Connector가 제공하는 도구 목록과 파라미터 스키마를 출력합니다. |
| `unity-bridge refresh` | Unity 에셋을 새로고침합니다. |
| `unity-bridge console` | Unity Console 로그를 읽거나 지웁니다. |
| `unity-bridge test` | Unity EditMode/PlayMode 테스트를 실행합니다. |
| `unity-bridge editor` | Play Mode 진입, 종료, 일시정지를 제어합니다. |
| `unity-bridge menu` | Unity 메뉴 아이템을 경로로 실행합니다. |
| `unity-bridge reserialize` | Unity 에셋을 강제로 리시리얼라이즈합니다. |
| `unity-bridge profiler` | Unity Profiler 상태 확인, 활성화, 비활성화, 초기화, hierarchy 호출을 실행합니다. |
| `unity-bridge screenshot` | Scene/Game 뷰 스크린샷을 저장합니다. |
| `unity-bridge exec` | Unity Editor 안에서 임의 C# 코드를 실행합니다. |
| `unity-bridge call` | connector command 이름과 JSON params를 직접 보내는 raw 호출입니다. |
| `unity-bridge wait-ready` | Unity Editor에 직접 준비 상태를 확인합니다. |
| `unity-bridge update` | 설치된 UnityBridge CLI 패키지 또는 standalone 실행 파일을 업데이트합니다. |
| `unity-bridge <tool-name>` | 목록에 없는 명령어는 connector/custom tool 이름으로 보고 직접 호출합니다. |

## 사용 예시

### Unity 인스턴스

```powershell
unity-bridge instances
unity-bridge status
unity-bridge tools
unity-bridge wait-ready --timeout-sec 300
```

`wait-ready`는 heartbeat 파일로 Unity를 찾은 뒤 에디터 메인 스레드에서 현재 상태를
직접 확인합니다. Unity가 `ready`라고 응답하면 heartbeat 갱신이나 고정 0.5초 안정화 시간을
기다리지 않고 완료됩니다. 요청된 새로고침·컴파일·Play Mode 전환이 남아 있으면 계속
기다리며, 이전 `ready` 파일만으로는 완료되지 않습니다. 시작 대기·연결 복구·상태 확인은
하나의 `--timeout-sec` 안에서 처리하고, 포트가 바뀌어도 같은 프로젝트를 따라갑니다.
에디터에 요청하지 않고 heartbeat 파일의 상태만 조회하려면 `status`를 사용하세요.

Unity heartbeat는 평상시 갱신 간격을 0.5초, 즉 초당 약 2회로 유지합니다.
서버 시작과 일시정지·재개 이벤트는 즉시 기록하고, Editor 업데이트에서 감지한
상태 변화도 정기 갱신 시간을 기다리지 않습니다. `Heartbeat age`는 저장된 상태의
경과 시간이며 명령 응답 시간과는 다릅니다. `status`는 한 번 출력하므로 최신 상태는
다시 실행해서 확인합니다. Editor가 멈추거나 백그라운드 갱신이 느리면 0.5초를
넘길 수 있습니다. 새로고침·컴파일·Play Mode 준비 확인과 파일의 원자적 교체는
그대로 적용됩니다.

독립 호스트를 설치하면 `status`에 `Host: running` 또는 `Host: unavailable`도 표시합니다.
호스트가 실행 중이라고 Unity를 `ready`로 표시하거나 Unity heartbeat 시각을 갱신하지
않습니다. `--json status`에는 별도 호스트 PID·포트, 프로젝트 등록 여부, 컴파일러의
`prewarm_state`가 포함됩니다. 일반 PID와 포트는 계속 Unity를 가리킵니다.

직접 상태 확인을 사용하려면 Python CLI와 Unity Connector를 함께 업데이트하세요.
구형 Connector는 저장된 상태로 대신 성공하지 않고 업데이트 안내 오류를 반환합니다.

스크립트를 수정한 뒤에는 `unity-bridge refresh --compile request --wait`로 새로고침과
컴파일을 요청하고 준비 완료를 기다리세요. 단독 `wait-ready`는 컴파일을 요청하지 않으며,
별개의 작업이 나중에 시작되지 않는다는 보장도 하지 않습니다.

### 업데이트

```powershell
unity-bridge update
unity-bridge update --check
unity-bridge update --ref main
unity-bridge update --ref v0.2.3
unity-bridge update --dry-run
```

Python 패키지 설치에서는 `update`가 pip로 CLI 패키지를 다시 설치합니다. standalone 빌드에서는
현재 OS용 릴리스 설치 스크립트를 다시 실행해 맞는 release 실행 파일을 내려받습니다. `--check`는
아무것도 설치하지 않고 설치된 CLI 버전과 선택한 Git ref의 버전을 비교합니다. Unity Connector용
Git 패키지 URL도 함께 출력하지만, Unity 프로젝트의 `Packages/manifest.json`은 자동으로 수정하지
않습니다.

일반 CLI 명령에서는 하루에 한 번만 CLI 업데이트를 확인하고, 새 버전이 있을 때만 짧은 알림을
출력합니다. `--json` 출력과 `update` 명령 자체에서는 이 알림을 건너뜁니다.
건너뛰려면 `UNITY_BRIDGE_SKIP_UPDATE_CHECK=1` 환경변수를 설정하거나 `--no-update-check`를
붙이세요.

### 에셋 새로고침

```powershell
unity-bridge refresh
unity-bridge refresh --path Assets/Scripts/Player.cs
unity-bridge refresh --path Assets/Scripts/Player.cs --path Assets/Prefabs/Enemy.prefab
unity-bridge refresh --path Assets/Scripts/Player.cs --wait
unity-bridge refresh --mode force
unity-bridge refresh --force
unity-bridge refresh --compile request
```

`--path`가 없으면 프로젝트 전체에 `AssetDatabase.Refresh()`를 실행합니다. 하나 이상의
`--path`를 넘기면 해당 경로들을 `AssetDatabase.ImportAsset()`으로 가져옵니다. 경로는
`Assets/...`, `Packages/...`, 또는 Unity 프로젝트 내부의 절대 경로를 사용할 수 있으며,
절대 경로는 import 전에 Unity asset path로 정규화됩니다.

refresh/import 이후에만 다음 작업을 이어가야 한다면 `--wait`를 사용하세요. 이 옵션은
Unity가 refresh/import를 관측한 뒤 안정적인 `ready` heartbeat로 돌아올 때까지 기다려서, 명령이
반환된 직후 시작되는 compile 또는 domain reload와의 race를 줄입니다.

### 콘솔 로그

```powershell
unity-bridge console
unity-bridge console --count 20
unity-bridge console --lines 20
unity-bridge console --type error --type warning
unity-bridge console --stacktrace none
unity-bridge console --stacktrace full
unity-bridge console --clear
```

### Editor 제어

```powershell
unity-bridge editor play
unity-bridge editor play --wait
unity-bridge editor play --wait --timeout-sec 300
unity-bridge editor stop
unity-bridge editor stop --wait
unity-bridge editor pause
```

`--wait`를 사용하면 `play`는 `playing` heartbeat를, `stop`은 안정적인 `ready`
heartbeat를 기다립니다. 도메인 리로드 중 connector가 다른 포트에서 다시 열려도 같은 Unity
프로젝트를 기준으로 다시 찾아서 대기합니다.

### 테스트 실행

```powershell
unity-bridge test
unity-bridge test --mode EditMode
unity-bridge test --mode PlayMode
unity-bridge test --filter MyTestClass
unity-bridge test --allow-dirty-scenes
unity-bridge test --auto-save-scenes
unity-bridge test --mode PlayMode --timeout-sec 600
unity-bridge test --mode PlayMode --no-wait
```

`PlayMode` 테스트는 기본적으로 Unity가 결과 파일을 쓸 때까지 기다린 뒤 최종 성공/실패를
반환합니다. 즉, 테스트 실패 시 CLI exit code도 실패로 처리됩니다. 즉시 반환이 필요하면
`--no-wait`를 사용하세요. 대기 중에는 처음 포트가 계속 유효하다고 가정하지 않고 프로젝트
경로 기준으로 Unity Editor를 다시 찾습니다.

`test` 명령은 Unity Test Framework(`com.unity.test-framework`)가 설치된 프로젝트에서만
사용할 수 있습니다. UnityBridge는 이 패키지를 자동 설치하지 않습니다. 설치되어 있지 않으면
`test` 명령은 Test Framework 설치 안내를 반환하고, 다른 UnityBridge 기능은 계속 사용할 수
있습니다.

### Unity 메뉴

```powershell
unity-bridge menu "File/Save Project"
unity-bridge menu "Assets/Refresh"
unity-bridge menu "Window/General/Console"
```

### 에셋 리시리얼라이즈

```powershell
unity-bridge reserialize
unity-bridge reserialize Assets/Prefabs/Player.prefab
unity-bridge reserialize Assets/Scenes/Main.unity Assets/Scenes/Lobby.unity
unity-bridge reserialize Assets/Prefabs/Player.prefab --wait
```

리시리얼라이즈가 긴 Editor 업데이트를 유발할 수 있고 다음 단계가 안정적인 Unity 상태를
필요로 한다면 `--wait`를 사용하세요.

### Profiler

```powershell
unity-bridge profiler status
unity-bridge profiler enable
unity-bridge profiler disable
unity-bridge profiler clear
unity-bridge profiler hierarchy
```

### 스크린샷

```powershell
unity-bridge screenshot
unity-bridge screenshot --view scene --output-path Screenshots/scene.png
unity-bridge screenshot --view game --width 1280 --height 720
```

### C# 코드 실행

```powershell
unity-bridge exec --code "return UnityEditor.EditorApplication.isPlaying;"
unity-bridge exec --code "return UnityEngine.Application.dataPath;"
unity-bridge exec --code-file .\query.cs
unity-bridge exec --file .\query.cs
Get-Content .\query.cs -Raw | unity-bridge exec --stdin
unity-bridge exec --code "return Unity.Entities.World.All.Count;" --using Unity.Entities
```

짧은 코드는 inline `--code`를 사용해도 됩니다. 여러 줄 C# 코드이거나 PowerShell이 해석하기 쉬운
문자(`;`, 따옴표, 줄바꿈 등)가 들어간 코드는 `--file`/`--code-file` 또는 `--stdin`을
권장합니다.

RC2는 호환 호스트가 실행 중인 일반 `exec`의 초기화 비용을 줄입니다.
명령 형식은 그대로이며 원래 제한 시간을 유지하고 응답 유실 후 재실행하지 않습니다.
구버전 호스트나 컴파일러 직접 지정은 기존 경로를 사용합니다. Standalone 파이프
입출력은 UTF-8입니다. [측정 범위](EXEC_OPTIMIZATION.ko.md)를 참고하세요.

호스트 경로에서는 별도 Roslyn 워커가 실제 Unity 참조 DLL과 지원 언어 버전을 기준으로
컴파일합니다. 결과 코드는 Unity 메인 스레드에서 실행합니다. 반복 코드는 컴파일 준비
정보를 재사용하지만 매번 새로운 assembly identity로 emit하여 호출별 정적 상태를
유지합니다. 반환값과 실행 자체를 캐시하지 않습니다. 참조 DLL의 식별자가 바뀌면
기존 컴파일 캐시는 사용할 수 없습니다. 컴파일 제한 시간은 최대 30초이며 원래 명령의
남은 시간도 적용됩니다. 이미 Unity 안에서 실행 중인 임의 C# 코드를 강제로 중단하는
제한 시간은 아닙니다.

프로젝트의 C# 파일을 수정하면 계속 `refresh --compile request --wait` 등으로 Unity
컴파일을 수행해야 합니다. 독립 컴파일러는 `exec`의 임시 코드를 처리합니다.

### Raw connector command

```powershell
unity-bridge list
unity-bridge call list
unity-bridge call console --params '{"count":20,"type":"error,warning"}'
unity-bridge call manage_editor --params '{"action":"play","wait_for_completion":true}'
unity-bridge call my_custom_tool --params '{"key":"value"}'
```

### Custom tool 직접 호출

```powershell
unity-bridge spawn --x 1 --y 0 --z 5 --prefab Enemy
unity-bridge spawn --params '{"x":1,"y":0,"z":5,"prefab":"Enemy"}'
unity-bridge my_custom_tool --key value --enabled
unity-bridge my_custom_tool --no-enabled
unity-bridge my_custom_tool first second
```

목록에 없는 명령어는 모두 connector command로 직접 전송됩니다. `--x 1` 같은 플래그는
`{"x": 1}` 형태의 params로 변환되고, `--my-value`는 `my_value`로 변환됩니다. 값이 없는
플래그는 `true`, `--no-name`은 `false`로 전달됩니다. 일반 위치 인자는 `args` 배열로
전달됩니다.

Unity 쪽 custom tool은 connector namespace와 attribute를 사용하면 됩니다.

```csharp
using Newtonsoft.Json.Linq;
using UnityBridgeConnector;

[UnityBridgeTool(Name = "my_custom_tool")]
public static class MyCustomTool
{
    public static object HandleCommand(JObject parameters)
    {
        return new SuccessResponse("ok");
    }
}
```

단, `profiler`, `console`, `test`처럼 이미 UnityBridge 전용 명령어로 예약된 이름은 전용 CLI가
먼저 처리합니다. 이런 built-in command에 아직 짧은 옵션으로 열려 있지 않은 세부 파라미터를
보내려면 `unity-bridge call <command> --params '{...}'` 형식을 사용하세요.
