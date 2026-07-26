# UnityBridge Installation

[한국어](INSTALL.ko.md) | English | [README](../README.md)

This document covers standalone CLI installation, Unity package version pinning,
updates, and release assets. Python package mode is documented separately in
[PYTHON_PACKAGE.md](PYTHON_PACKAGE.md).

## Unity Package

In Unity Editor, open `Window > Package Manager > + > Add package from git URL...`
and paste:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#main
```

The connector supports Unity 2020.3 LTS and newer Editor versions, including
Unity 6.

This URL follows the `main` branch. When newer versions land on `main`, use the
Package Manager `Update` button to fetch the latest connector commit. If you
want to pin a specific release, use the [version pinning](#version-pinning)
format below.

The connector starts automatically when the Unity Editor opens. It writes
heartbeat files under `~/.unity-bridge/instances/`, then the CLI can discover
the running Editor and send commands to `http://127.0.0.1:{port}/command`.
Heartbeat files are written through a temporary file and atomic replacement so
clients do not read partially written JSON during discovery.

## Recommended Editor Setting

By default, Unity can throttle Editor updates when the window is not focused.
UnityBridge dispatches Unity API work on the Editor main thread, so CLI command
handling may be delayed while the Editor is in the background.

For the most reliable background responsiveness, set:

```text
Edit > Preferences > General > Interaction Mode > No Throttling
```

The connector also requests PlayerLoop updates whenever a CLI request arrives,
but `No Throttling` is still recommended for stable response times.

## Standalone CLI

The recommended installation downloads a standalone `unity-bridge` executable
from the latest GitHub Release, so Python is not required on the target machine.

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1 | iex
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh | sh
```

## Install A Specific Release

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.1.6
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.1.6
```

## Update

```powershell
unity-bridge update --check
unity-bridge update
```

For standalone builds, `update` reruns the release installer for the current OS
and downloads the matching release executable. The command also prints the Unity
Connector Git package URL, but it does not edit a Unity project's
`Packages/manifest.json` automatically.

Normal CLI commands check for a CLI update at most once per day and print a
short notice only when a newer version is available. The notice is skipped for
`--json` output and for the `update` command itself. Set
`UNITY_BRIDGE_SKIP_UPDATE_CHECK=1` or pass `--no-update-check` to skip it.

## Release Assets

Standalone installation requires the GitHub Release to contain the matching
asset for your platform:

```text
unity-bridge-windows-amd64.exe
unity-bridge-linux-amd64
unity-bridge-linux-arm64
unity-bridge-darwin-amd64
unity-bridge-darwin-arm64
```

Windows installers also fall back to the older `unity-bridge-windows-x64.exe`
asset for previous releases.

## Version Pinning

After tags are published, append the tag to the Unity package URL:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.1.6
```

## Local Installer

```powershell
git clone https://github.com/zjxps2007/UnityBridge.git
cd UnityBridge
.\install.cmd
```

If you prefer running the PowerShell script directly, bypass the execution
policy for this process only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```
