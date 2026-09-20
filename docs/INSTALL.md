# UnityBridge Installation

[한국어](INSTALL.ko.md) | English | [README](../README.md)

This document covers standalone CLI installation, Unity package version pinning,
updates, and release assets. Python package mode is documented separately in
[PYTHON_PACKAGE.md](PYTHON_PACKAGE.md).

The stable release is **v0.3.0**, including the independent host and bundled compiler.
Default installation and unqualified updates select the latest stable release.
Follow [upgrading to v0.3.0](#upgrade-to-v030) to update both CLI and Connector.

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
UnityBridge CLI, host, and compiler processes are closed, obsolete runtime directories can be removed;
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

## Host-Enabled Builds

The v0.3.0 bundles also contain a self-contained .NET 10/Roslyn
compiler. The installer checks the worker and registers the exact CLI and worker
paths under `~/.unity-bridge/host/`; Unity Hub does not need to inherit a CLI PATH
entry. Keep the entire runtime directory, including `compiler/`. The user does
not install a separate .NET runtime or SDK. Host-enabled installers fail if the
bundled compiler cannot start, before replacing the existing installation.

The worker requires a [.NET 10 supported operating system](https://github.com/dotnet/core/blob/main/release-notes/10.0/supported-os.md)
and the relevant native OS dependencies. Supporting the Connector API in Unity
2020.3 does not imply that the worker runs on every older OS supported by that
Editor. Older systems can retain v0.2.3, or use source/Python mode with the
`legacy` backend where that existing setup works.

With a matching Connector, Unity starts the host in the background after startup
and the service warms the compiler against that project's references. It manages
multiple projects and stays alive across domain reloads. When all tracked Editors
are closed and no requests remain, it shuts down after 30 seconds. An update
registers the new runtime; the previous service exits after outstanding work drains.
The host uses authenticated loopback communication and keeps its process registry
separate from Unity heartbeat files.

v0.3.0 starts external preparation early during Editor initialization. It keeps the same installer layout and registered absolute
paths. Nuitka bundles are comparison artifacts only; use the PyInstaller archive
with these installers. See [startup and packaging validation](PYTHON_STARTUP.md).

`unity-bridge status` shows host availability separately; its Unity PID, port,
state, and Heartbeat age still describe the Editor. Use `--json status` for the
project's compiler `prewarm_state`. `--backend host` requires the new service,
`--backend legacy` selects direct communication, and `--backend auto` uses a
registered compatible host when available. See [backend behavior](COMMANDS.md#execution-backend).

Use the [tagged stable installer](#upgrade-to-v030) to install and register the host.
To build locally, follow [development instructions](DEVELOPMENT.md#independent-host-and-compiler).
Manually extracting an archive alone does not register its host; register its
absolute executable and worker paths as described there. Installing only the
Python package does not download the compiler runtime.

## Install A Specific Release

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.3.0
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.3.0
```

## Upgrade To v0.3.0

v0.3.0 is the stable release of the independent Python host, bundled .NET 10/Roslyn
compiler and persistent command sessions. Update both the CLI and Unity package.
Default installation and plain `unity-bridge update` select the latest stable release.

From v0.2.3 or a v0.3.0 release candidate:

```text
unity-bridge update --ref v0.3.0
```

For a fresh installation or v0.2.1 and earlier, run the tagged installer below.
For a custom installation, append `-InstallDir <existing-folder>` on Windows or
`--install-dir <existing-folder>` on macOS/Linux.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.0/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.3.0
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.0/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.3.0
```

Unity Package Manager Git URL:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.3.0
```

After Unity finishes compiling, `unity-bridge status` should show `Connector: 0.3.0`.
Check the CLI with `unity-bridge update --check`. The installer registers the exact
host executable paths but does not change the Unity package reference automatically.

## Prerelease

Default installation selects the latest stable release. To explicitly test a
release candidate, use that RC tag for the installer's `-Version` / `--version`
or `unity-bridge update --ref`, and select the same Unity package tag. Download
the installer script itself from that tag too. An unqualified update returns to
the latest stable release. Existing v0.3.0 RC users can follow the
[stable upgrade instructions](#upgrade-to-v030).

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

If GitHub denies unauthenticated version checks, `UNITY_BRIDGE_GITHUB_TOKEN` can
supply a token with read access to the repository contents. It is optional and
applies to version checks; the CLI sends it only to the initial GitHub API request.

## Release Assets

v0.3.0 includes the independent host and speed changes validated during the RCs.
Install both the CLI and Connector from the v0.3.0 tag. ReadyToRun
compiler publication changes bundle size, but the extraction and installation
procedure is unchanged and users still do not install Python or a .NET SDK for
standalone bundles. See [measured tradeoffs](SPEED_FOLLOWUP.md).

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
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.3.0
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
