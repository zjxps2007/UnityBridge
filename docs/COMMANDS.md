# UnityBridge Commands

[?쒓뎅??(COMMANDS.ko.md) | English | [README](../README.md)

This document lists the commands currently available in the `unity-bridge` CLI.

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
| `unity-bridge wait-ready` | Wait until Unity reaches the ready state. |
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

### Update

```powershell
unity-bridge update
unity-bridge update --check
unity-bridge update --ref main
unity-bridge update --ref v0.1.6
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
