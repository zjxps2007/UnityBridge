# CLI 유지보수

한국어 | [English](DEVELOPMENT.md)

공개 함수 `unity_bridge.cli:main`은 호환성을 유지합니다. 설치된 명령,
`python -m unity_bridge`, standalone 실행 파일은 `_bootstrap:main`에서 경량 exec
경로나 기존 CLI를 선택합니다. 두 경로 모두 Python이며 C# 컴파일은 기존 Roslyn
워커가 담당합니다.

| 파일 | 역할 |
|---|---|
| `_bootstrap.py`, `_fast_exec.py` | 경량 진입점, exec 적용 조건, 호출자 입력과 인증한 호스트 연결을 처리합니다. |
| `_wire.py` | 내부 CLI 통신의 메시지 크기와 남은 제한 시간을 확인합니다. |
| `cli.py` | 기본 명령과 직접 도구 호출을 구분하고, 클라이언트 생성·결과 출력·종료 코드를 처리합니다. |
| `_cli/arguments.py` | 기본 명령의 옵션·도움말과 직접 호출의 플래그·반복 값·위치 인자·JSON 매개변수를 해석합니다. |
| `_cli/commands.py` | 해석한 옵션을 `UnityClient`와 `UnityBridgeAdapter` 호출로 연결하고 C# 코드 입력을 읽습니다. |
| `_cli/output.py` | 일반 텍스트·JSON·오류·Connector 버전 경고·업데이트 결과를 출력합니다. |
| `_cli/updates.py` | Python 패키지 업데이트, standalone 업데이트 예약, 원격 버전 조회, 일일 알림 캐시를 처리합니다. |
| `_cli/standalone.py` | 플랫폼·아키텍처를 선택하고 운영체제별 설치기 실행 명령을 만듭니다. |
| `_cli/versions.py` | 공통 버전 해석과 비교를 담당합니다. |
| `_cli/session.py` | JSONL 순차 요청, 입력 크기 제한, 요청별 CLI 출력을 처리합니다. |
| `host/` | 선택적 로컬 서비스, 인증 통신, 프로젝트별 대기열, 런타임 등록과 컴파일러 프로세스를 관리합니다. |
| `host/context.py` | 협상한 Unity 참조 정보마다 참조 식별값과 프로젝트 정보를 한 번 준비합니다. |
| `host/cli_server.py`, `host/cli_request.py` | 경량 CLI 요청을 인증하고 호스트 안에서 기존 parser·탐색·adapter·대기열·출력을 사용합니다. |
| 저장소 루트의 `compiler-worker/` | 독립 Roslyn 컴파일러, 내부 JSONL 프로토콜과 컴파일러 회귀 검증을 포함합니다. |

`_cli`는 내부 구현입니다. Python 프로그램에서 연동할 때는 `unity_bridge`가
공개하는 client·adapter API를 사용합니다. 기존 `cli.build_parser`와
`cli.add_common_options` 함수도 계속 사용할 수 있습니다.

## 독립 호스트와 컴파일러

RC2는 공개 export와 선택 기능 모듈을 필요할 때 로드하고 선택한
명령의 parser만 캐시합니다. 기존 전체 parser API도 유지합니다. 세션은 프로세스·모듈·parser
초기화를 재사용하며 Unity 탐색 결과나 변경 명령 응답을 재사용하지 않습니다.
자동 업데이트 정책은 그대로입니다.

호환 호스트가 실행 중이면 `_fast_exec.py`가 호출자의 입력을 읽고 호스트 레지스트리의
`cliPort`로 요청 하나를 보냅니다. 짧게 실행되는 프로세스는 전체 CLI·client·adapter를
로드하지 않습니다. 서비스는 요청별 출력을 갖는 기존 parser를 사용하고 상대 경로는
호출자 작업 폴더 기준으로 해석하며 기존 프로젝트별 FIFO 대기열에 넣습니다.
여러 요청을 처리하는 호스트에서 전역 작업 폴더·환경 변수·출력 스트림을 바꾸지 않습니다.

내부 통신은 고정 IPv4 루프백, CLI 프로토콜 1, 4바이트 big-endian 길이 접두부,
메시지당 32 MiB 제한과 기존 사용자 전용 인증 토큰을 사용합니다. 원래 명령의 절대
제한 시간을 전달합니다. 지원하지 않는 구문·구버전 호스트·컴파일러 직접 지정·연결 실패는
전송 전에 기존 CLI로 돌아가며 이미 읽은 stdin도 복구합니다. 프레임 전송을 시도한 뒤
응답이 유실되거나 잘못되면 `unknown`으로 표시하고 다시 실행하지 않습니다.
호스트 연결 상태를 Unity 준비 완료로 간주하지 않으며 Unity Heartbeat PID·포트의
의미도 유지합니다. 자동 업데이트 확인 시기가 되면 기존 CLI에서 그대로 확인합니다.
진단 시 `UNITY_BRIDGE_DISABLE_FAST_EXEC=1`로 경량 경로를 끌 수 있습니다.
Python API와 JSONL 세션은 기존 경로를 유지합니다. Standalone의 표준 입출력은
Windows 파이프를 포함해 UTF-8을 사용합니다.

Connector는 Heartbeat 변경 시 백그라운드에서 인증한 `/changed` 알림을 합쳐 보냅니다.
호스트는 탐색을 즉시 깨우되 실제 정보는 Heartbeat 파일에서 읽고 주기 탐색도 유지합니다.
전달 직전 대상 포트가 바뀌면 이전 listener가 살아 있어도 파일을 다시 확인합니다.
`EditorOperations.cs`는 제한된 수의 작업 기록을 `SessionState`에 저장해 리로드를
넘겨 유지합니다. 완료는 해당 import·컴파일·리로드 또는 재생 상태 이벤트로 확인합니다.
코드 import 완료가 불명확하면 기존 대기로 돌아가거나 작업 기록 유실을 보고합니다.

컴파일러는 기본적으로 ReadyToRun으로 배포 빌드합니다. 같은 코드의 JIT 비교 빌드는
`build-compiler.py --no-ready-to-run`을 사용하세요. .NET 런타임과 Roslyn은 여전히
동봉하며 사용자 C# 코드를 미리 컴파일하는 기능은 아닙니다. 시작 속도와 용량은
[검증 보고서](SPEED_FOLLOWUP.ko.md)에 기록합니다. 컴파일 캐시는 여러 항목이 공유하는
참조 이미지를 한 번만 계산하고 코드별 추정 비용을 더합니다. 256 MiB 계산 한도는
실제 프로세스 메모리 상한이 아닙니다.

정식 **v0.3.0**은 독립 호스트와 컴파일러를 포함하며 `main`에 통합했습니다.
배포 묶음을 시험하려면 [해당 태그의 정식 설치기](INSTALL.ko.md#v030으로-업그레이드)를 사용하세요.
서비스는 Unity 밖에서 실행되며, Unity API 실행은 계속 Connector의 메인 스레드에서
처리합니다. 참조 정보에는 도메인·참조 세대, 실제 DLL 경로와 MVID, 명시적인 C# 언어
버전이 포함됩니다. Unity 참조를 워커의 .NET 10 라이브러리로 대신하지 않습니다.

Connector의 HTTP 읽기·쓰기는 백그라운드에서 처리합니다. 대기열의 도구 실행과
결과 직렬화는 Unity 메인 스레드에서 수행하며, Unity API를 사용하는 사용자 정의
결과 getter·converter도 여기에 포함합니다. Connector의 dispatch await는 Unity 동기화 컨텍스트를
유지합니다. 요청은 수신한 리스너에 속하며, 리스너 중지·교체 후 해당 대기 요청이
뒤늦게 실행되지 않도록 해야 합니다.

서비스는 컴파일러 프로세스를 미리 실행하고 새 프로젝트 참조 정보마다 백그라운드에서
`return null;`을 한 번 컴파일합니다. 이 준비용 DLL을 Unity에 로드하지 않습니다.
반복 코드는 파싱·바인딩 준비 정보를 재사용하지만 호출마다 새 assembly identity로
emit합니다. 호스트는 실행 결과·로드한 assembly·delegate를 캐시하지 않습니다.
워커 캐시를 비워도 Unity 도메인에 이미 로드된 DLL은 해제되지 않습니다.

`host/context.py`는 참조 정보를 협상한 뒤 프로젝트 경로 정규화와 참조 식별 해시를
한 번 계산합니다. 반복 요청은 이 스냅샷을 재사용하고, 도메인이나 참조 세대가
바뀌면 새로 협상합니다. 워커의 `MetadataReferenceCache`는 캐시하지 않은 DLL을
하나의 이미지로 읽어 MVID를 검증하고 같은 불변 이미지를 Roslyn에 전달합니다.
캐시가 있어도 파일의 현재 MVID를 다시 확인하므로 수정 시각이 같아도 참조 변경을
검사합니다. 캐시에 열린 DLL 파일 핸들을 남기지 않습니다.

Python 빌드 의존성과 .NET 10 SDK를 준비합니다. CI는 SDK **10.0.401**, 컴파일러
프로젝트는 Roslyn **5.0.0**을 고정합니다. 작업 폴더의 SDK는 `--dotnet PATH`로
지정할 수 있습니다. 완성된 배포 묶음을 쓰는 사용자에게는 SDK가 필요하지 않습니다.

```sh
python -m pip install -e ".[build]"
dotnet run --project compiler-worker/UnityBridge.Compiler.Tests --configuration Release
python scripts/build-compiler.py --runtime win-x64 --output build/compiler/win-x64
python scripts/build-standalone.py --output-name unity-bridge-windows-amd64.zip --compiler-dir build/compiler/win-x64
```

다른 플랫폼에서는 `linux-x64`, `linux-arm64`, `osx-x64`, `osx-arm64`와 해당 압축 파일
이름을 사용합니다. `--compiler-dir`을 생략하면 `build-standalone.py`가 현재 플랫폼의
컴파일러도 빌드합니다. `--without-compiler`는 Connector에 직접 연결하는 개발용 묶음을
만듭니다. 빌드 결과는 Git에서 제외한 `build/`와 `dist/`에 저장합니다.

수정 가능한 Python 설치와 Windows 워커를 등록하는 예시입니다.

```powershell
$python = (Get-Command python).Source
$worker = (Resolve-Path .\build\compiler\win-x64\UnityBridge.Compiler.exe).Path
python -m unity_bridge _host register --executable $python --python-module --worker $worker
python -m unity_bridge _host start
python -m unity_bridge --backend host exec --code "return 42;"
```

일치하는 로컬 Connector 패키지를 사용하고 Unity를 열어 두세요. macOS/Linux에서는
Python의 절대 경로와 `.exe`가 없는 워커 경로를 사용합니다. 수동으로 푼 standalone
묶음은 해당 실행 파일의 `_host register --executable <CLI-절대경로> --worker
<런타임/compiler/워커-절대경로>`를 실행하며 `--python-module`을 생략합니다.
패키지 설치기는 등록을 자동으로 수행합니다. `_host`는 설치기·개발자용 내부 명령이며
진단용 `_host status`, `_host stop`도 제공합니다. Unity가 열려 있으면 중지한 호스트가
다시 실행될 수 있습니다.

격리된 검증에는 Unity 시작 환경과 CLI 양쪽의 `UNITY_BRIDGE_HOST_HOME`을 같은 임시
폴더로 설정합니다. 테스트용 실행 경로를 등록할 때 `--instances-dir`도 지정할 수
있습니다. 검증 보고서에 등록 파일의 인증 토큰을 포함하지 마세요.

내부 프로토콜과 캐시 한도는 [compiler-worker/README.md](../compiler-worker/README.md)에
정리했습니다. 다음 조건을 유지합니다.

- 호스트 요청의 원래 제한 시간을 유지하고, Unity는 실행 잠금 획득 후와 DLL 로드
  직전에 다시 확인합니다.
- 실행 전에 참조가 바뀌면 갱신할 수 있습니다. 전달 이후 실행 여부가 불확실하면
  재실행하지 않고 `unknown`을 반환합니다. 실행 전 거부임이 확인된 `not_started`만
  준비 과정을 다시 시도할 수 있습니다.
- 실시간 상태 조회는 변경 명령 대기열에 막히지 않습니다. 호스트 상태로 Unity
  heartbeat나 준비 완료를 대신하지 않습니다. 기존 PID·포트는 Unity를 뜻하며
  호스트 등록은 별도 파일에 기록합니다.
- 호스트 경로와 기존 Connector 직접 연결 모두 로컬 HTTP를 사용하고 환경 변수의
  프록시나 리다이렉트를 따르지 않습니다. 직접 연결은 HTTP 연결 하나를 열어 범용
  HTTPS·인증서 초기화를 생략합니다. 두 경로 모두 응답 유실 후 명령을 재실행하지
  않습니다. 새 런타임 등록 후 이전 서비스는 진행 중인 요청을 마치고 종료합니다.

## 명령 변경 방법

1. `arguments.py`에 옵션을 정의하고 `KNOWN_COMMANDS`에 명령 이름을 추가합니다.
2. `commands.execute_command`에서 옵션을 실제 호출에 연결합니다. client·adapter의
   결과를 반환하면 진입점이 출력과 성공·실패 종료 코드를 공통으로 처리합니다.
3. `tests/test_cli.py`에서 요청 단위로 검증합니다. 명령 구문, JSON 형식,
   stdout·stderr 구분, 종료 코드는 기존 사용자와의 호환성을 유지해야 하는 항목입니다.

등록되지 않은 명령은 직접 도구 호출 파서로 처리합니다. 반복 플래그, `--params`,
`--` 처리를 기본 명령의 argparse 옵션과 구분해 유지합니다. 직접 호출은 이미 발견한
인스턴스를 요청에 재사용합니다. JSON 출력은 응답 데이터를 얕게 감싸고, 중첩된
전체 데이터를 복사하지 않습니다.

도움말이 빠르게 끝나도록 업데이트 모듈을 불러오기 전에 인자 해석을 수행합니다.
설치된 패키지 메타데이터는 업데이트·버전 확인에 필요할 때 불러옵니다. 자동 알림의
일일 캐시, 건너뛰기 옵션, 타임아웃 동작은 유지합니다.

원격 버전 조회는 `UNITY_BRIDGE_GITHUB_TOKEN`을 명시적으로 설정한 경우 인증을 사용합니다.
배포 CI는 압축된 실행 파일을 검증하는 단계에만 저장소 읽기 권한의 토큰을 전달합니다.
인증 헤더는 최초 GitHub API 요청에만 붙이고 리다이렉트에는 전달하지 않습니다.
`tests/test_update_auth.py`에서 같은 호스트와 다른 호스트로의 리다이렉트를
네트워크 연결 없이 검증합니다.

## 검증

저장소 루트에서 실행합니다.

```sh
python -m unittest discover -s tests
python -m compileall -q src tests
git diff --check
```

CLI 변경만 확인하려면 다음 명령을 사용합니다.

```sh
python -m unittest discover -s tests -p test_cli.py
```

`tests/test_client.py`는 인스턴스 탐색·HTTP·adapter를 검증합니다. 임시 heartbeat와
HTTP 서버 등 공통 도구는 `tests/helpers.py`에 있습니다.
`tests/fixtures/cli_requests.json`은 모듈 분리 전의 요청 형식 21개를 기록합니다.
명령의 외부 동작을 의도적으로 바꾸고 문서도 갱신하는 경우에만 해당 기대값을 바꿉니다.
`tests/test_installers.py`는 가짜 다운로드와 임시 설치 폴더를 사용하며, 필요한
운영체제나 셸이 없으면 해당 플랫폼 검사를 건너뜁니다.

Standalone을 수정했다면 `scripts/build-standalone.py`로 압축 파일을 빌드하고,
압축을 푼 실행 파일을 직접 확인합니다. 시작 시간은 동일한 Python·PyInstaller 버전과
배포 방식으로 비교합니다. 소스 import 시간만으로 배포 실행 파일의 성능을 판단하지
않습니다. 실제 Unity 검증은 [tests/unity/README.md](../tests/unity/README.md)를 참고하세요.

호스트 브랜치에서는 `tests/test_host_service.py`, `tests/test_host_context.py`, `tests/test_host_compiler.py`,
`tests/test_host_registry.py`와 위의 C# 회귀 검증을 포함합니다. 요청 ID 중복,
대기 전후 제한 시간, 컴파일러 실패와 재시작, 준비 중 리로드, 전달 이후 응답 유실,
토큰 격리와 다중 프로젝트를 확인합니다. 실제 실행은 Unity 2021과 Unity 6에서
검증하고, 최소 지원 버전의 API 호환성은 별도로 확인합니다.

배포 workflow는 Windows x64, Linux x64·ARM64, macOS Intel·Apple Silicon 묶음과
컴파일러 워커를 빌드·확인하도록 구성합니다. workflow를 수정한 것만으로 모든 플랫폼의
실행 결과가 검증되는 것은 아닙니다. 새 기본 경로를 활성화하기 전 v0.2.3과 같은
프로젝트·빌드 의존성으로 첫 실행과 사전 준비된 실행, 전체 응답 시간 p50·p95,
Editor 정지, 상주 메모리와 설치 용량을 비교합니다. 일반 명령 p95가 5% 또는 10ms 중
큰 값 이상 느려지면 원인을 확인합니다. 컴파일러만 측정한 결과로 전체 명령이
빨라졌다고 판단하지 않습니다.

[최초 v0.2.3 비교 보고서](HOST_VALIDATION.ko.md)는 당시 검증 기록으로 유지합니다.
이후 브랜치 변경과 검증은 [추가 최적화 보고서](HOST_OPTIMIZATION.ko.md)에 기록합니다.
두 보고서는 RC 이전 alpha 커밋을 측정한 결과이므로 기록된 버전·표본을 변경하지 않습니다.

## Heartbeat 갱신

v0.2.3은 평상시 기록 간격을 v0.2.2와 같은 0.5초로 유지합니다.
매 업데이트마다 상태·컴파일 오류·포트를 확인하고, 변화가 있으면 주기를 기다리지
않습니다. 서버 시작과 일시정지 이벤트도 바로 기록합니다. Unity API 조회와 기록은
메인 스레드에서 수행합니다. 백그라운드 타이머 때문에 응답하지 않는 Editor가
준비된 것처럼 보이면 안 됩니다. 새로고침·컴파일·Play Mode의 준비 확인 유예 시간은
유지해야 합니다.

모든 기록은 원자적 파일 교체를 사용하며, 실패해도 시도 시각을 남겨 매 프레임 파일
오류를 재시도하지 않습니다. 이벤트 기록도 주기 기준 시각을 갱신해 직후의 중복 기록을
줄입니다. 상태가 일정할 때 쓰기 횟수는 초당 약 2회를 유지하고,
상태 이벤트가 발생하면 추가 기록이 생길 수 있습니다. 네이티브 검증기의
`--heartbeat-audit`로 실제 간격·쓰기 비용·일시정지와 재개 상태를 비교합니다.
이 측정값으로 전체 명령이나 에이전트 응답 시간이 빨라졌다고 판단하면 안 됩니다.

앞서 시험한 0.1초 방식은 정기 쓰기 횟수를 5배로 늘렸습니다. v0.2.3은
0.5초 주기를 유지하면서 상태가 바뀔 때 빠르게 반영하는 데 집중합니다.
따라서 상태가 그대로인 동안 `Heartbeat age` 범위는 종전과 같고, 개선 대상은
상태 전환 시의 최신성입니다. 이벤트 기록과 매 업데이트의 상태 확인에도 비용은
있으므로 부하가 전혀 없다고 설명하면 안 됩니다.

## Connector 버전 표시

`unity-bridge status`는 실행 중인 Unity Connector가 기록한 버전을 표시합니다.
CLI 버전은 별개입니다. `Heartbeat`는 Unity 패키지 정보에서 버전을 읽고,
패키지 등록 변경이나 도메인 리로드까지 캐시합니다. C# 코드에 별도의 릴리스 버전
상수를 추가하지 마세요. UPM 패키지 밖에 소스만 복사한 경우에는 `unknown`을 표시합니다.

릴리스 전에는 Unity 2021과 Unity 6에서 실제 검증을 실행합니다. heartbeat,
실시간 준비 상태 응답, `Connector:` 표시가 설치된 `package.json` 버전과 일치해야 합니다.
`update --check`는 원격 manifest를 읽으므로 이 검증을 대신하지 못합니다.
v0.2.2-rc.1은 CLI와 manifest 버전이 일치해도 실행 중인 Connector의 상수가
구버전으로 남아 있었습니다. v0.2.2-rc.2에서 버전 출처를 패키지 정보로 변경했습니다.

## RC2 이후 Python 시작 시간 개선

[Python 시작 시간 보고서](PYTHON_STARTUP.ko.md)에 공개 RC2 기준, 기본값 선택,
채택하지 않은 실험, 원자료와 검증 한계를 기록합니다. 서비스 첫 시작,
Unity 시작, 준비된 CLI 프로세스, 연속 세션을 구분합니다.
`scripts/benchmark-host.py`는 `--cold-samples`, `--session-samples`,
`--candidate-env`, `--gui foreground|background`를 지원하며 요청별 실제 전경
여부를 기록합니다. Unity 시작 반복은 `--startup-host --startup-only
--reuse-projects`와 반복된 variant 목록으로 측정합니다. 최초 import와 기존
Library를 사용하는 재시작은 별도로 집계합니다.
`--large-samples 100`으로 1.5MiB 한글·이모지 결과의 CLI와 세션 지연도
각각 100회 비교할 수 있습니다.

`scripts/benchmark-preparation.py`는 저장한 `compiler-context.json`으로 컴파일러
준비를, `scripts/benchmark-output.py`는 세션 JSON 직렬화를 따로 측정합니다.
두 스크립트의 결과만으로 Unity 전체 응답 속도를 주장하지 않습니다.
`scripts/verify-windows-bundle.py`는 별도 폴더에서 로컬 압축 파일로 실제 설치기를
실행하며, Nuitka 실험 폴더의 설치 거부도 확인할 수 있습니다.

호스트·프레임·컴파일러 내부 제한 시간에는 `time.perf_counter()`를 사용합니다.
탐색·큐 대기 전에 만료 시점을 고정하고, 대기 후 원래 시간을 다시 부여하지
않습니다. Unix 시각의 만료 값도 Connector까지 전달하며 실행 잠금 직후 다시
검사합니다. 전송 결과가 불확실한 명령은 재실행하지 않습니다.

빌드 변형은 `scripts/build-standalone.py --output-dir ... --work-dir ...`로
분리합니다. `scripts/build-nuitka-experiment.py`의 결과는 릴리즈 파일이 아닌
실험 폴더입니다. 성능·설치·5개 플랫폼 기준을 통과하기 전까지 기본 배포 형식을
유지합니다. `release_tag`가 빈 workflow dispatch는 릴리즈를 게시하지 않고
검증용 artifact만 만듭니다.
플랫폼별 `build-info-*` artifact에는 Python·패키징 버전과 실행 파일 압축본,
컴파일러, Python 소스의 해시를 남깁니다. 릴리즈에 게시하는 설치 파일과는
별도로 보존합니다.
`--large-samples 100`으로 약 1.5MiB 한글·이모지 결과를 CLI와 세션에서 각각
100회 비교합니다. 현재 측정기는 일반 명령뿐 아니라 exec와 세션의 p95도
판정합니다. `--snippet-offset`은 실행 간 캐시를 조사할 때 생성하는 식을 바꿉니다.
느린 유효 표본도 재측정 결과와 함께 보존합니다. 과거 `passed` 필드는 확대된
판정 기준을 포함하지 않을 수 있습니다.
