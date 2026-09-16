# CLI 유지보수

한국어 | [English](DEVELOPMENT.md)

공개 진입점은 기존과 같은 `unity_bridge.cli:main`입니다. 설치된 명령,
`python -m unity_bridge`, standalone 실행 파일이 모두 이 함수를 사용합니다.
내부 구현은 `src/unity_bridge/_cli/`에 있습니다.

| 파일 | 역할 |
|---|---|
| `cli.py` | 기본 명령과 직접 도구 호출을 구분하고, 클라이언트 생성·결과 출력·종료 코드를 처리합니다. |
| `_cli/arguments.py` | 기본 명령의 옵션·도움말과 직접 호출의 플래그·반복 값·위치 인자·JSON 매개변수를 해석합니다. |
| `_cli/commands.py` | 해석한 옵션을 `UnityClient`와 `UnityBridgeAdapter` 호출로 연결하고 C# 코드 입력을 읽습니다. |
| `_cli/output.py` | 일반 텍스트·JSON·오류·Connector 버전 경고·업데이트 결과를 출력합니다. |
| `_cli/updates.py` | Python 패키지 업데이트, standalone 업데이트 예약, 원격 버전 조회, 일일 알림 캐시를 처리합니다. |
| `_cli/standalone.py` | 플랫폼·아키텍처를 선택하고 운영체제별 설치기 실행 명령을 만듭니다. |
| `_cli/versions.py` | 공통 버전 해석과 비교를 담당합니다. |

`_cli`는 내부 구현입니다. Python 프로그램에서 연동할 때는 `unity_bridge`가
공개하는 client·adapter API를 사용합니다. 기존 `cli.build_parser`와
`cli.add_common_options` 함수도 계속 사용할 수 있습니다.

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
