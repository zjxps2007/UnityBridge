# UnityBridge Commands

[한국어](COMMANDS.ko.md) | English | [README](../README.md)

This document lists the commands currently available in the `unity-bridge` CLI.
The backend options are included in stable **v0.3.0**; earlier v0.2.3 uses
direct Connector communication. See [stable installation](INSTALL.md#upgrade-to-v030)
for the tagged installer and matching Unity package.

## Persistent Session And Operation Completion

The following features are included in v0.3.0. Start
`unity-bridge --project <path> --no-update-check session`, keep its
stdin open, and send one JSON object per line:

```json
{"id":1,"args":["status"]}
{"id":2,"args":["exec","--code","return 42;"]}
```

Each command finishes before the next starts. A response is flushed immediately:

```json
{"id":2,"exit_code":0,"result":{"success":true,"message":"...","data":42},"error":null}
```

`result` contains the usual JSON command output; `error` contains stderr, or
`null`. IDs may be strings, integers, or null. EOF ends the session. Invalid input
returns exit code 2 for that request and does not close the session. Input is
limited to 1 MiB of characters per line. Commands inherit the session's project,
port, backend, timeout and instances directory, with per-request overrides.
Discovery is refreshed for each request. `session`, `update`, `_host` and
`--stdin` are rejected inside a session; use `exec --code` or `--code-file`.
Requests always use JSON output, so the existing JSON update-notice exemption
applies. Normal CLI update behavior is unchanged.

With a matching Connector, `refresh --wait`, `reserialize --wait`, and
`editor play|stop --wait` confirm the returned operation ID through a live Unity
response. The default receipt polling interval is 50 ms with no added stability
window. Compile completion also waits for the required domain reload; play/stop
waits for its corresponding event. A stale `ready` snapshot cannot complete a
different operation. A lost or cancelled receipt is reported without replaying
the action. Commands without a receipt retain the existing heartbeat wait and
0.5-second stability window for ready states. Explicit `--stable-sec` values
remain supported; editor/reserialize also accept `--poll-interval-sec`.
Standalone `wait-ready` and low-level Python snapshot semantics are unchanged.
Live confirmation probes use at most one second per read, within the original
wait deadline, so a connection to a replaced listener cannot consume the whole
wait. Only state reads are retried.

## Development After RC2

Development after RC2 also reuses session/host HTTP connections and serializes
result objects once. Ordinary `console`, `tools`, `wait-ready` and `exec` calls
can use the resident parser. Snapshot commands stay local by default after
their forwarding path missed the latency gate. See [measurements](PYTHON_STARTUP.md).
Use one session across consecutive requests, reading each response before the next:

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

Long-lived Python callers can use `with UnityClient(...) as client:` or call
`client.close()` to release the connection pool. Discovery still runs per call.

## Basic Form

```powershell
unity-bridge <command> [options]
unity_bridge <command> [options]
```

The `unity_bridge` command runs the same CLI as `unity-bridge`.

Common options can be placed before or after the subcommand.

```powershell
unity-bridge --project D:\UnityProjects\MyGame status
unity-bridge status --project D:\UnityProjects\MyGame
unity-bridge --port 8090 console --count 20
unity-bridge --json console --count 20
```

## Common Options

| Option | Description |
|--------|-------------|
| `--project PATH_OR_TEXT` | Select a Unity instance by exact project path, path suffix, or exact project folder name. |
| `--port PORT` | Select a Unity instance by port. |
| `--backend auto\|host\|legacy` | Choose external-host or direct-Connector routing. Defaults to `UNITY_BRIDGE_BACKEND`, otherwise `auto`. |
| `--timeout-ms MS` | HTTP request timeout. Default: `120000`. |
| `--instances-dir PATH` | Use a heartbeat directory other than `~/.unity-bridge/instances`. |
| `--json` | Print JSON output for other programs. |
| `--no-update-check` | Skip the automatic daily update notice for this run. |

`--project` checks exact project paths, whether the supplied path is inside a
project, and path-segment suffixes such as `UnityProjects/MyGame` or `MyGame`.
It does not auto-select substring-only matches, so `Game` will not match
`GamePrototype`. If a suffix matches multiple Unity instances, UnityBridge
returns an error instead of choosing one arbitrarily. For automated integrations,
prefer a full project path or `--port`.

## Execution Backend

```powershell
unity-bridge --backend host exec --code "return 42;"
unity-bridge --backend legacy console --count 20
```

- `auto`: use a compatible registered host that has negotiated the selected Unity
  project; otherwise use the existing direct connection before submitting any work.
- `host`: require that host, returning an error when unavailable. Snapshot commands
  such as `status` still read files and do not force a Unity request.
- `legacy`: communicate directly with the Connector. Explicit `exec --csc` or
  `--dotnet` options also select this path, even with `--backend host`.

An explicit option overrides `UNITY_BRIDGE_BACKEND`. `--port` continues to select
the Unity port, not the host port. Host routing requires a registered compiler
bundle and a compatible Connector; a Python-only install keeps the direct path
unless a suitable host is already registered.

The host preserves per-project command order and waits through reloads only for
commands not yet sent to Unity. Queueing, compilation, and dispatch use the
original request deadline. If an already sent command loses its response,
`data.completion` is `unknown`; this means completion is uncertain. Inspect the
Editor before deciding whether to repeat a changing command. The client does not
automatically replay it through another route. `not_started` means execution was
rejected before the command ran.

## Command List

| Command | Purpose |
|---------|---------|
| `unity-bridge instances` | Print discovered Unity Editor instances. |
| `unity-bridge status` | Print the selected Unity Editor instance status. |
| `unity-bridge tools` | Print Unity Connector tools and parameter schemas. |
| `unity-bridge refresh` | Refresh Unity assets. |
| `unity-bridge console` | Read or clear Unity Console logs. |
| `unity-bridge test` | Run Unity EditMode or PlayMode tests. |
| `unity-bridge editor` | Enter, stop, or pause Play Mode. |
| `unity-bridge menu` | Execute a Unity menu item by path. |
| `unity-bridge reserialize` | Force reserialize Unity assets. |
| `unity-bridge profiler` | Run Unity Profiler status, enable, disable, clear, or hierarchy calls. |
| `unity-bridge screenshot` | Save a Scene/Game view screenshot. |
| `unity-bridge exec` | Execute arbitrary C# code inside the Unity Editor. |
| `unity-bridge call` | Send a raw connector command name and JSON params. |
| `unity-bridge wait-ready` | Confirm readiness directly with the Unity Editor. |
| `unity-bridge update` | Update the installed UnityBridge CLI package or standalone executable. |
| `unity-bridge <tool-name>` | Treat unknown command names as connector/custom tool names and call them directly. |

## Usage

### Unity Instances

```powershell
unity-bridge instances
unity-bridge status
unity-bridge tools
unity-bridge wait-ready --timeout-sec 300
```

`wait-ready` uses heartbeat files to locate Unity, then asks the selected editor
for its current state on the editor main thread. It returns as soon as Unity
confirms `ready`, without waiting for a heartbeat update or a fixed 0.5-second
settling period. Pending refresh, compilation, and play transitions remain busy.
An old `ready` file alone cannot complete the wait. Startup, connection recovery,
and state checks share `--timeout-sec`; port changes follow the same project.
Use `status` for a snapshot of the heartbeat file without contacting the editor.

Unity heartbeat publication keeps its regular 0.5-second interval, about two writes per
second while state is unchanged. Server start and pause/resume events publish
immediately; changes detected on an Editor update also bypass the periodic
interval. `Heartbeat age` measures
how old the saved snapshot is, not command response time. `status` prints once;
run it again to read a newer snapshot. Editor stalls or background throttling can
delay publication beyond 0.5 seconds. Refresh/compile/play readiness guards still
apply, and the file is replaced atomically.

With the independent host installed, `status` also prints `Host: running` or
`Host: unavailable`. The host process staying alive does not make Unity `ready`
or update Unity's heartbeat timestamp. `--json status` includes separate host PID,
port, project registration, and compiler `prewarm_state`; the ordinary PID and
port continue to identify Unity.

Update the Python CLI and Unity Connector together to use live readiness checks.
An older Connector reports an update error instead of accepting a cached state.

After editing scripts, use `unity-bridge refresh --compile request --wait` to
request refresh/compilation and wait for readiness. Standalone `wait-ready` does
not request compilation or guarantee that an unrelated task will not start later.

### Update

```powershell
unity-bridge update
unity-bridge update --check
unity-bridge update --ref main
unity-bridge update --ref v0.3.0
unity-bridge update --dry-run
```

For Python package installs, `update` reinstalls the CLI package with pip. For
standalone builds, `update` reruns the release installer for the current OS and
downloads the matching release executable. `--check` compares the installed CLI
version with the selected Git ref without installing anything. The command
prints the Unity Connector Git package URL too, but it does not edit a Unity
project's `Packages/manifest.json` automatically.

For normal CLI commands, UnityBridge checks for a CLI update at most once per
day and prints a short notice only when a newer version is available. The notice
is skipped for `--json` output and for the `update` command itself. Set
`UNITY_BRIDGE_SKIP_UPDATE_CHECK=1` or pass `--no-update-check` to skip it.

### Asset Refresh

```powershell
unity-bridge refresh
unity-bridge refresh --path Assets/Scripts/Player.cs
unity-bridge refresh --path Assets/Scripts/Player.cs --path Assets/Prefabs/Enemy.prefab
unity-bridge refresh --path Assets/Scripts/Player.cs --wait
unity-bridge refresh --mode force
unity-bridge refresh --force
unity-bridge refresh --compile request
```

Without `--path`, refresh runs `AssetDatabase.Refresh()` for the project. With
one or more `--path` values, UnityBridge sends those paths to
`AssetDatabase.ImportAsset()`. Paths can be `Assets/...`, `Packages/...`, or
absolute paths inside the Unity project; absolute project paths are normalized
to Unity asset paths before import.

Use `--wait` when the next step needs to continue only after Unity has observed the
refresh/import and returned to a stable `ready` heartbeat. This avoids racing a
compile or domain reload that starts just after the refresh command returns.

### Console Logs

```powershell
unity-bridge console
unity-bridge console --count 20
unity-bridge console --lines 20
unity-bridge console --type error --type warning
unity-bridge console --stacktrace none
unity-bridge console --stacktrace full
unity-bridge console --clear
```

### Editor Control

```powershell
unity-bridge editor play
unity-bridge editor play --wait
unity-bridge editor play --wait --timeout-sec 300
unity-bridge editor stop
unity-bridge editor stop --wait
unity-bridge editor pause
```

With `--wait`, `play` waits for a `playing` heartbeat and `stop` waits for a
stable `ready` heartbeat. The wait follows the same Unity project even if the
connector restarts on a different port during a domain reload.

### Tests

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

`PlayMode` tests wait for Unity's result file by default, then return the final
success or failure. Test failures therefore produce a failing CLI exit code.
Use `--no-wait` when you intentionally want to return immediately. While
waiting, UnityBridge resolves the editor again by project path instead of
assuming the original port is still valid.

The `test` command requires Unity Test Framework (`com.unity.test-framework`) in
the Unity project. UnityBridge does not install that package automatically. If it
is missing, the `test` command returns an installation hint and the rest of
UnityBridge remains usable.

### Unity Menu

```powershell
unity-bridge menu "File/Save Project"
unity-bridge menu "Assets/Refresh"
unity-bridge menu "Window/General/Console"
```

### Asset Reserialization

```powershell
unity-bridge reserialize
unity-bridge reserialize Assets/Prefabs/Player.prefab
unity-bridge reserialize Assets/Scenes/Main.unity Assets/Scenes/Lobby.unity
unity-bridge reserialize Assets/Prefabs/Player.prefab --wait
```

Use `--wait` when reserialization may trigger a long editor update and the next
step needs Unity to be stable before continuing.

### Profiler

```powershell
unity-bridge profiler status
unity-bridge profiler enable
unity-bridge profiler disable
unity-bridge profiler clear
unity-bridge profiler hierarchy
```

### Screenshots

```powershell
unity-bridge screenshot
unity-bridge screenshot --view scene --output-path Screenshots/scene.png
unity-bridge screenshot --view game --width 1280 --height 720
```

### C# Execution

```powershell
unity-bridge exec --code "return UnityEditor.EditorApplication.isPlaying;"
unity-bridge exec --code "return UnityEngine.Application.dataPath;"
unity-bridge exec --code-file .\query.cs
unity-bridge exec --file .\query.cs
Get-Content .\query.cs -Raw | unity-bridge exec --stdin
unity-bridge exec --code "return Unity.Entities.World.All.Count;" --using Unity.Entities
```

Use inline `--code` for short snippets. For multi-line C# or code containing
characters that shells often interpret, prefer `--file`/`--code-file` or
`--stdin`.

RC2 accelerates ordinary `exec` invocations when a
compatible host is already running; no command changes are needed. It retains
the original timeout and never re-executes a request after a lost response.
Older hosts and explicit compiler overrides use the existing route. Standalone
pipe input/output is UTF-8. See [measured scope](EXEC_OPTIMIZATION.md).

On the host backend, a separate Roslyn worker compiles against Unity's actual
reference DLLs and supported language version. Unity executes the emitted code
on its main thread. Repeated source reuses compiler preparation but emits a fresh
assembly identity for each call, preserving fresh snippet static state. Neither
return values nor execution are cached. Changes to reference DLL identities
invalidate cached compilation. The compiler has a 30-second limit, also bounded
by the remaining command deadline; that limit cannot forcibly interrupt arbitrary
C# code already executing inside Unity.

Project C# edits still need Unity compilation, for example
`refresh --compile request --wait`. The independent compiler applies to `exec`
snippets; it does not bypass Unity's project compilation pipeline.

### Raw Connector Commands

```powershell
unity-bridge list
unity-bridge call list
unity-bridge call console --params '{"count":20,"type":"error,warning"}'
unity-bridge call manage_editor --params '{"action":"play","wait_for_completion":true}'
unity-bridge call my_custom_tool --params '{"key":"value"}'
```

### Direct Custom Tools

```powershell
unity-bridge spawn --x 1 --y 0 --z 5 --prefab Enemy
unity-bridge spawn --params '{"x":1,"y":0,"z":5,"prefab":"Enemy"}'
unity-bridge my_custom_tool --key value --enabled
unity-bridge my_custom_tool --no-enabled
unity-bridge my_custom_tool first second
```

Unknown command names are sent directly as connector commands. Flags such as
`--x 1` become params like `{"x": 1}`, and `--my-value` becomes `my_value`.
Flags without values are sent as `true`; `--no-name` is sent as `false`.
Plain positional arguments are sent in an `args` array.

Custom Unity-side tools should use the connector namespace and attribute:

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

Reserved names such as `profiler`, `console`, and `test` are handled by
UnityBridge's built-in CLI first. If a built-in command needs detailed
parameters that are not exposed as short flags yet, use
`unity-bridge call <command> --params '{...}'`.
