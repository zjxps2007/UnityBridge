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

The connector supports Unity 2020.3 LTS through Unity 6.

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

When CLI requests arrive, the connector posts queue processing to the Editor
main thread and coalesces overlapping wake-ups. The regular Editor update loop
also drains the queue. `No Throttling` is still recommended for stable response
times.

## Standalone CLI

The recommended installation downloads a standalone `unity-bridge` bundle
from the latest GitHub Release, so Python is not required on the target machine.
New builds use PyInstaller's one-folder layout: the installer unpacks the archive
once instead of extracting the runtime on every command. v0.2.1 and older releases
still use a single executable; the installer falls back to those assets.

The command stays at the same installation path. Keep its adjacent
`_unity_bridge_runtime_<build-id>` directory; copying only the executable will not
work. Updates verify the downloaded bundle before replacing the command and keep
older runtime directories for commands still running against them. Once all
UnityBridge CLI processes are closed, obsolete runtime directories can be removed;
keep the directory belonging to the currently installed build. The `update` command
preserves a custom installation directory.

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
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.2.1
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.2.1
```

## Upgrade To v0.2.2

v0.2.2 is the stable release of the startup improvements, CLI refactoring, and
Connector version fix tested in RC2. Update both the CLI and Unity package.

If the CLI is on RC1 or RC2, run `unity-bridge update --ref v0.2.2`.
For v0.2.1 or earlier, rerun the installer from the new tag because older
updaters expect the single-file release format.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.2/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.2.2
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.2/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.2.2
```

Unity Package Manager Git URL:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.2.2
```

After Unity finishes compiling, `unity-bridge status` should report
`Connector: 0.2.2`. Use `unity-bridge update --check --ref v0.2.2` to verify the
CLI version. CLI updates do not edit the Unity project's package reference.

## Prerelease

v0.2.3-rc.1 publishes Heartbeat state changes sooner while keeping the regular
0.5-second interval. Select this prerelease explicitly for both components.
Default installation and plain `unity-bridge update` select stable v0.2.2.

From v0.2.2 or a v0.2.2 release candidate:

```text
unity-bridge update --ref v0.2.3-rc.1
```

For a fresh installation or v0.2.1 and earlier, run the tagged installer.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.3-rc.1/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.2.3-rc.1
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.3-rc.1/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.2.3-rc.1
```

Unity Package Manager Git URL:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.2.3-rc.1
```

After Unity finishes compiling, `unity-bridge status` should show
`Connector: 0.2.3-rc.1`. Check the CLI with
`unity-bridge update --check --ref v0.2.3-rc.1`. The CLI updater does not change the
Unity package reference automatically.

## Update

```powershell
unity-bridge update --check
unity-bridge update
```

For standalone builds, `update` reruns the release installer for the current OS
and downloads the matching release executable. The command also prints the Unity
Connector Git package URL, but it does not edit a Unity project's
`Packages/manifest.json` automatically.

Update the CLI and Unity Connector together for live `wait-ready` checks. An
older Connector returns an update error instead of accepting a saved `ready`
heartbeat. To test an unreleased branch, follow
[Install From A Branch](PYTHON_PACKAGE.md#install-from-a-branch) and use the same
Git branch for both components; the standalone installer downloads release assets.

Normal CLI commands check for a CLI update at most once per day and print a
short notice only when a newer version is available. The notice is skipped for
`--json` output and for the `update` command itself. Set
`UNITY_BRIDGE_SKIP_UPDATE_CHECK=1` or pass `--no-update-check` to skip it.

## Release Assets

Standalone installation requires the GitHub Release to contain the matching
asset for your platform:

```text
unity-bridge-windows-amd64.zip
unity-bridge-linux-amd64.tar.gz
unity-bridge-linux-arm64.tar.gz
unity-bridge-darwin-amd64.tar.gz
unity-bridge-darwin-arm64.tar.gz
```

Archives contain a `unity-bridge/` folder. For manual installation, extract the
whole folder and run the executable inside it. The installers prefer archives and
fall back to previous single-file assets (`.exe` on Windows, no extension on
macOS/Linux). Windows also supports the old `unity-bridge-windows-x64.exe` name.

## Version Pinning

After tags are published, append the tag to the Unity package URL:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.2.1
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
