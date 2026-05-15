# UnityBridge Python Package Mode

[한국어](PYTHON_PACKAGE.ko.md) | English | [README](../README.md)

Python package mode is for development and Python programs that need to import
`unity_bridge` directly. For normal CLI use, the standalone installer is
recommended because it does not require Python on the target machine.

## When To Use

Use Python package mode when:

- a Python program should call UnityBridge as an internal API;
- you need to compose Unity calls with other Python logic without shell parsing;
- you are developing UnityBridge itself.

Use standalone mode when:

- the user only needs the `unity-bridge` command;
- the target machine should not require Python;
- the integration will call the CLI from another tool.

## Install From Git

```powershell
python -m pip install --upgrade "git+https://github.com/zjxps2007/UnityBridge.git"
```

Install a specific tag:

```powershell
python -m pip install --upgrade "git+https://github.com/zjxps2007/UnityBridge.git@v0.1.4"
```

## Install With The Installer

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

## Run From A Cloned Repo

```powershell
git clone https://github.com/zjxps2007/UnityBridge.git
cd UnityBridge
python -m pip install -e .
```

Module form without installing:

```powershell
$env:PYTHONPATH=(Resolve-Path .\src).Path
python -m unity_bridge status
python -m unity_bridge instances
python -m unity_bridge tools
```

## Import Usage

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
are normalized by the connector. Use `wait=True` when the next step needs to
wait for a stable Unity `ready` heartbeat after refresh/import. Waited
adapter operations rediscover Unity by project path, so they can follow a
connector port change caused by domain reload.

## Raw Client Usage

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

## Update

For Python package installs, `unity-bridge update` reinstalls the package with
pip. It also prints the Unity Connector package URL, but it does not edit a
Unity project's `Packages/manifest.json` automatically.

```powershell
unity-bridge update --check
unity-bridge update
unity-bridge update --ref v0.1.4
```
