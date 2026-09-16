# UnityBridge Python Package Mode

[한국어](PYTHON_PACKAGE.ko.md) | English | [README](../README.md)

Python package mode is for development and Python programs that need to import
`unity_bridge` directly. For normal CLI use, the standalone installer is
recommended because it does not require Python on the target machine.

The current public stable version is **v0.2.3**. The independent-host options in
this document describe the unreleased **0.3.0-alpha.1** branch. Installing the
Python package alone does not download .NET or the Roslyn worker.

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
python -m pip install --upgrade "git+https://github.com/zjxps2007/UnityBridge.git@v0.2.3"
```

## Install From A Branch

To test changes before a release, install the Python CLI and Unity Connector from
the same Git branch. When the development branch is available on the remote,
use the independent-host branch as follows; unpushed work must be installed from
the local checkout instead.

Windows PowerShell:

```powershell
python -m pip install --upgrade --force-reinstall "git+https://github.com/zjxps2007/UnityBridge.git@codex/external-host-compiler"
```

macOS/Linux, in the Python environment you use for UnityBridge:

```sh
python3 -m pip install --upgrade --force-reinstall "git+https://github.com/zjxps2007/UnityBridge.git@codex/external-host-compiler"
```

In Unity Package Manager, use the matching Git URL:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#codex/external-host-compiler
```

Repeat the CLI install command and update the Unity package when the branch
changes. Branch commits can share a package version, so the version number alone
does not identify the installed commit. Check `python -m pip freeze` (`python3` on
macOS/Linux) and the Unity project's `Packages/packages-lock.json` for Git refs
and revisions. The standalone installer downloads release assets rather than
selecting this branch.

This updates the Python client and Connector, not the external compiler runtime.
Without a registered compatible host, `auto` uses the existing direct route.
To test the independent compiler, also build and register it using
[the development guide](DEVELOPMENT.md#independent-host-and-compiler), or use a
matching locally built standalone installation that has registered its host.

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

The optional backend is selected on `UnityClient`; an explicit value overrides
`UNITY_BRIDGE_BACKEND` (`auto` when unset). Pass that client to an adapter when
you need the same choice throughout a workflow:

```python
from unity_bridge import UnityBridgeAdapter, UnityClient

client = UnityClient(project=r"D:\UnityProjects\MyGame", backend="host")
bridge = UnityBridgeAdapter(client=client)
result = client.call("exec", {"code": "return 42;"})
if result.completion_unknown:
    print("Check Unity before retrying: execution could not be confirmed.")
```

`host` requires a compatible, running registered service; `legacy` uses the
direct Connector. `auto` chooses the host when available and falls back only
before submitting work. An explicit `csc` or `dotnet` exec parameter always uses
the legacy compiler route. Host response loss after dispatch returns unknown
completion and is never automatically replayed through the direct route.
`status()` still reads Unity's saved state, with separate host metadata; a live
service is not proof that Unity is ready.

`UnityClient.wait_for_ready()` is a low-level state wait: its defaults may return
an existing `ready` heartbeat immediately. Use `UnityBridgeAdapter.wait_for_ready()`
to confirm the live editor state without a fixed settling delay. Set its optional
`stable_sec` only when your workflow needs an extra stability window. Live checks
require an updated Unity Connector as well as the Python CLI. After changing
scripts, use `bridge.refresh_assets(compile="request", wait=True)` to request the
work and wait for readiness. The low-level `after_timestamp` and `stable_sec`
arguments remain available for custom synchronization.

## Update

For Python package installs, `unity-bridge update` reinstalls the package with
pip. It also prints the Unity Connector package URL, but it does not edit a
Unity project's `Packages/manifest.json` automatically.

```powershell
unity-bridge update --check
unity-bridge update
unity-bridge update --ref v0.2.3
```
