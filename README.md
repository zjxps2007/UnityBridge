# UnityBridge

[한국어](README.ko.md) | English

Python-native client and Unity package for controlling the Unity Editor through
a local HTTP connector.

The Python client does not require a separate CLI binary. It talks directly to
the Unity connector by:

1. Reading instance heartbeat files from `~/.unity-bridge/instances/*.json`.
2. Selecting a running Unity Editor by port, exact project path, path suffix,
   current working directory, or most recent heartbeat.
3. Sending JSON to `http://127.0.0.1:{port}/command`.

## Quick Start

### 1. Install the Unity package

In Unity Editor, open `Window > Package Manager > + > Add package from git URL...`
and paste:

```text
https://github.com/zjxps2007/UnityBridge.git?path=unity-bridge-connector
```

The connector starts automatically when the Unity Editor opens. It writes
heartbeat files under `~/.unity-bridge/instances/`, then the Python client can
discover the running Editor and send commands to `http://127.0.0.1:{port}/command`.
Heartbeat files are written through a temporary file and atomic replacement so
clients do not read partially written JSON during discovery.

### Recommended Editor setting

By default, Unity can throttle Editor updates when the window is not focused.
UnityBridge dispatches Unity API work on the Editor main thread, so CLI command
handling may be delayed while the Editor is in the background.

For the most reliable background responsiveness, set:

```text
Edit > Preferences > General > Interaction Mode > No Throttling
```

The connector also requests PlayerLoop updates whenever a CLI request arrives,
but `No Throttling` is still recommended for the most stable response times.

### 2. Install the Python client

```powershell
python -m pip install --upgrade "git+https://github.com/zjxps2007/UnityBridge.git"
```

The PowerShell installer can also be run directly:

```powershell
irm https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1 | iex
```

```powershell
git clone https://github.com/zjxps2007/UnityBridge.git
cd UnityBridge
.\install.cmd
```

If you prefer running the PowerShell script directly, bypass the execution policy
for this process only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

### 3. Check the connection

Keep the Unity project open, then run:

```powershell
unity-bridge status
unity-bridge instances
unity-bridge tools
```

## Version Pinning

After tags are published, append the tag to the Unity package URL:

```text
https://github.com/zjxps2007/UnityBridge.git?path=unity-bridge-connector#v0.1.0
```

## CLI Usage

Installed command:

```powershell
unity-bridge status
unity-bridge instances
unity-bridge tools
```

The same CLI is also available as `unity_bridge`.

Add `--json` when another program or agent should parse the output:

```powershell
unity-bridge --json instances
unity-bridge --json console --count 20
```

Module form without installing:

```powershell
$env:PYTHONPATH='D:\Code\Codex\CP\UnityBridge\src'
python -m unity_bridge status
python -m unity_bridge instances
python -m unity_bridge tools
```

## Command Reference

The full CLI command list, common options, and direct custom tool syntax are
documented separately in [COMMANDS.md](COMMANDS.md).

## Python examples

```python
from unity_bridge import UnityBridgeAdapter

bridge = UnityBridgeAdapter(project=r"D:\UnityProjects\MyGame")

bridge.refresh_assets()
bridge.refresh_assets(paths=[r"D:\UnityProjects\MyGame\Assets\Scripts\Player.cs"], wait=True)
logs = bridge.read_console(count=50, types=["error", "warning", "log"])
tests = bridge.run_tests(mode="EditMode")
play = bridge.editor_play(wait=True)
```

`refresh_assets()` without paths runs a full Unity asset refresh. Passing
`paths` imports only those asset paths; absolute paths inside the Unity project
are normalized by the connector. Use `wait=True` for agent workflows that need
to wait for a stable Unity `ready` heartbeat after refresh/import. Waited
adapter operations rediscover Unity by project path, so they can follow a
connector port change caused by domain reload.

The adapter is intentionally thin. It maps friendly Python methods to connector
commands, but it does not add an allowlist or denylist policy layer. Raw access
is available through `UnityClient` when you need exact connector params:

```python
from unity_bridge import UnityClient

client = UnityClient(project=r"D:\UnityProjects\MyGame")
status = client.status()
print(status.state, status.port)

result = client.call("console", {"count": 20, "type": "error,warning"})
print(result.success, result.message, result.data)
```

## Run tests

```powershell
git clone https://github.com/zjxps2007/UnityBridge.git
cd UnityBridge
python -m pip install -e .
python -m unittest discover -s tests
```

## License

UnityBridge is licensed under the MIT License.

Third-party license notices are listed in `NOTICE.md`.
