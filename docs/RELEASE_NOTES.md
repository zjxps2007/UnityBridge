# Unreleased

- Build standalone CLI archives using PyInstaller one-folder mode. Install the runtime once, retaining the existing command path and support for older single-file release assets.
- Validate staged downloads before replacing the installed command. Give each build a separate runtime directory so updates do not overlay libraries used by an older process. Preserve custom installation paths during self-update.
- Use Unity TypeCache for initial tool discovery, with reflection fallback for runtime-loaded assemblies. Generate parameter schemas only on a tool-list request and retain handler/schema caches for subsequent requests.
- Keep dynamic tool discovery, duplicate-handler selection, domain-reload invalidation, and live readiness checks. No fixed readiness delay is added or removed by this change.

# UnityBridge v0.2.1

## Changes

- `wait-ready` now asks the Unity Editor for its current state on the main thread. A ready response completes immediately without a fixed 0.5-second settling delay. Saved heartbeat files are used for discovery, not as proof of readiness.
- Preserve pending refresh, compilation, and Play Mode transitions. Readiness checks recover from interrupted connections and port changes within the overall timeout, and reject mismatched or unconfirmed responses.
- Cache Unity tool discovery and reuse reflected handlers instead of scanning assemblies for every command. Coalesce main-thread wake-ups and avoid redundant CLI JSON conversions and discovery work.
- Prevent asset import workers from publishing bridge instances. Retry transient heartbeat file access failures during discovery.
- Update English and Korean READMEs, command references, and installation guides.

## Upgrade both components

Update the CLI and Unity Connector together to **0.2.1**. An older Connector does not support live readiness checks and returns an update error. The CLI updater does not change the Unity project's package automatically.

For an existing standalone CLI installation:

```text
unity-bridge update --ref v0.2.1
```

In Unity Package Manager, use:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.2.1
```

After changing scripts, request the work explicitly:

```text
unity-bridge refresh --compile request --wait
```

Standalone `wait-ready` does not request compilation or predict unrelated work that starts after the Editor responds.

## Validation

- 73 Python tests passed.
- Core changes were validated in native Unity 2021.3.19f1 and 6000.3.13f1: actual compilation and domain reload, stale heartbeat rejection, and compatibility errors for an older Connector.
- The release workflow builds and runs each executable on its matching platform, verifies its reported CLI and Connector versions, and publishes only after all five assets are ready: Windows x64, Linux x64/ARM64, and macOS Intel/Apple Silicon.

## 한국어 요약

- 고정 0.5초 대기 없이 Unity Editor의 실제 응답으로 준비 완료를 확인합니다. 컴파일·리로드 중에는 계속 기다리며, 오래된 상태 파일만으로 성공하지 않습니다.
- 도구 탐색 캐시, 요청 처리, CLI JSON 출력을 개선하고 import worker의 잘못된 인스턴스 등록을 방지했습니다.
- **CLI와 Unity Connector를 모두 0.2.1로 업데이트해야 합니다.** 위의 CLI 업데이트 명령과 Unity Package Manager URL을 함께 사용하세요.
- 스크립트 수정 후에는 `refresh --compile request --wait`로 컴파일 요청과 완료 대기를 연결하세요.
