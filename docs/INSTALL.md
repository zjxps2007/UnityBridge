# UnityBridge Installation

[한국어](INSTALL.ko.md) | English | [README](../README.md)

This document covers standalone CLI installation, Unity package version pinning,
updates, and release assets. Python package mode is documented separately in
[PYTHON_PACKAGE.md](PYTHON_PACKAGE.md).

The stable release is **v0.2.3**. The independent host described below is part of
the **v0.3.0-rc.2 prerelease**. Install it explicitly using the [RC instructions](#prerelease);
default installation continues to select stable.

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

## Host-Enabled Prerelease Builds

The v0.3.0-rc.2 bundles also contain a self-contained .NET 10/Roslyn
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

`unity-bridge status` shows host availability separately; its Unity PID, port,
state, and Heartbeat age still describe the Editor. Use `--json status` for the
project's compiler `prewarm_state`. `--backend host` requires the new service,
`--backend legacy` selects direct communication, and `--backend auto` uses a
registered compatible host when available. See [backend behavior](COMMANDS.md#execution-backend).

Use the [tagged RC installer](#prerelease) to install and register the host.
To build locally, follow [development instructions](DEVELOPMENT.md#independent-host-and-compiler).
Manually extracting an archive alone does not register its host; register its
absolute executable and worker paths as described there. Installing only the
Python package does not download the compiler runtime.

## Install A Specific Release

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.2.3
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.2.3
```

## Upgrade To v0.2.3

v0.2.3 is the stable release of the faster Heartbeat state publication and optional
GitHub authentication for version checks. It includes the startup improvements,
CLI refactoring, and Connector version fix from v0.2.2. Update both the CLI and
Unity package. Default installation and plain `unity-bridge update` select the
latest stable release.

From v0.2.2, a v0.2.2 release candidate, or v0.2.3-rc.2:

```text
unity-bridge update --ref v0.2.3
```

For a fresh installation or v0.2.1 and earlier, run the tagged installer. Older
updaters expect the previous single-file release format.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.3/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.2.3
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.3/install.sh -o /tmp/unity-bridge-install.sh
sh /tmp/unity-bridge-install.sh --version v0.2.3
```

Unity Package Manager Git URL:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.2.3
```

After Unity finishes compiling, `unity-bridge status` should show
`Connector: 0.2.3`. Check the CLI with
`unity-bridge update --check --ref v0.2.3`. The CLI updater does not change the
Unity package reference automatically.

## Prerelease

For **v0.3.0-rc.2**, use both the installer script and release assets from that tag.
This is also the upgrade path from v0.2.3 or older: their updater downloads the
`main` installer, which does not register the new host. If the existing CLI lives
in a custom directory, add `-InstallDir <existing-directory>` or
`--install-dir <existing-directory>` to the installation command.

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP 'unity-bridge-install-rc.ps1'
iwr https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.0-rc.2/install.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Version v0.3.0-rc.2
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.3.0-rc.2/install.sh -o /tmp/unity-bridge-install-rc.sh
sh /tmp/unity-bridge-install-rc.sh --version v0.3.0-rc.2
```

Pin the Unity Package Manager Git URL to the same tag:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.3.0-rc.2
```

After Unity finishes compiling, `unity-bridge status` should show
`Connector: 0.3.0-rc.2`. Check the CLI with:

```text
unity-bridge update --check --ref v0.3.0-rc.2
```

Once the RC CLI is installed, keep the explicit RC reference when updating or
reinstalling it:

```text
unity-bridge update --ref v0.3.0-rc.2
```

The RC updater selects the installer from that tag and preserves the current
installation directory. Plain standalone `unity-bridge update` selects the latest
stable release and can replace this RC with v0.2.3. The CLI updater does not update
the Unity package automatically, so also change its tag when switching versions.
Default installation does not opt into RC versions.
The Heartbeat changes from v0.2.3-rc.2 are included in stable v0.2.3; use the
[upgrade instructions above](#upgrade-to-v023) to move from that RC to stable.

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

RC2 includes the post-RC1 speed changes. Install both the CLI and Connector from
the RC2 tag to use them. ReadyToRun
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
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.2.3
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
