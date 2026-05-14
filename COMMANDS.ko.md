# UnityBridge 명령어

한국어 | [English](COMMANDS.md)

이 문서는 `unity-bridge` CLI에서 지금 사용할 수 있는 명령어를 정리합니다.

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
| `--timeout-ms MS` | HTTP 요청 타임아웃입니다. 기본값은 `120000`입니다. |
| `--instances-dir PATH` | 기본 `~/.unity-bridge/instances` 대신 다른 heartbeat 폴더를 사용합니다. |
| `--json` | 결과를 JSON으로 출력합니다. 에이전트가 파싱할 때 사용합니다. |

`--project`는 정확한 프로젝트 경로, 입력 경로가 프로젝트 내부인지 여부, `UnityProjects/MyGame`이나
`MyGame` 같은 경로 세그먼트 suffix를 확인합니다. `Game`이 `GamePrototype`에 매칭되는 식의 부분
문자열 자동 선택은 하지 않습니다. suffix가 여러 Unity 인스턴스에 동시에 매칭되면 임의 선택하지 않고
에러를 반환합니다. Agent 통합에서는 전체 프로젝트 경로나 `--port` 사용을 권장합니다.

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
| `unity-bridge wait-ready` | Unity가 ready 상태가 될 때까지 대기합니다. |
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

### 업데이트

```powershell
unity-bridge update
unity-bridge update --check
unity-bridge update --ref main
unity-bridge update --ref v0.1.3
unity-bridge update --dry-run
```

Python 패키지 설치에서는 `update`가 pip로 CLI 패키지를 다시 설치합니다. Windows standalone 빌드에서는
릴리스 설치 스크립트를 다시 실행해 release 실행 파일을 내려받습니다. `--check`는 아무것도 설치하지 않고
설치된 CLI 버전과 선택한 Git ref의 버전을 비교합니다. Unity Connector용 Git 패키지 URL도 함께 출력하지만,
Unity 프로젝트의 `Packages/manifest.json`은 자동으로 수정하지 않습니다.

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

Agent가 refresh/import 이후에만 다음 작업을 이어가야 한다면 `--wait`를 사용하세요. 이 옵션은
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

리시리얼라이즈가 긴 Editor 업데이트를 유발할 수 있고 다음 Agent 단계가 안정적인 Unity 상태를
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
