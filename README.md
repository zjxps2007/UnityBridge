# UnityBridge

[한국어](README.ko.md) | English

UnityBridge is a standalone CLI, Python-native client, and Unity package for
controlling the Unity Editor through a local HTTP connector.

The CLI discovers running Unity Editors through
`~/.unity-bridge/instances/*.json` heartbeat files, selects the target Editor,
and sends JSON commands through the registered local host when available, or
directly to `http://127.0.0.1:{port}/command`.

New standalone builds ship as an archive containing the executable and its runtime,
unpacked once during installation. Keep the runtime folder beside the executable.
The installer also supports the single-file assets used by v0.2.1 and older releases.
See [installation and updates](docs/INSTALL.md#standalone-cli).

Stable [v0.3.0](https://github.com/zjxps2007/UnityBridge/releases/tag/v0.3.0)
includes the independent host, bundled compiler, earlier preparation and persistent
sessions. Follow [upgrading to v0.3.0](docs/INSTALL.md#upgrade-to-v030) to update
both the CLI and Unity Connector. Default installation and unqualified updates
select the latest stable release.

This branch provides [v0.3.1-rc.2](https://github.com/zjxps2007/UnityBridge/releases/tag/v0.3.1-rc.2),
with parallel reference validation and an opt-in `session --pipeline` for preparing
the next inline command while Unity executes the previous one. The CLI, Python
package and Connector use **0.3.1-rc.2**. RC2 refines cached-reference checks and
command initialization. See [prerelease installation](docs/INSTALL.md#prerelease)
and [session usage](docs/COMMANDS.md#optional-session-pipeline-v031-rc1).

## Independent Host And Compiler

**v0.3.0** promotes the RC3 implementation to stable and is integrated into `main`.
The quick-start commands below install stable. The stable CLI, Python package and
Unity Connector all use version **0.3.0**.

The new host stays outside Unity's reloadable domain and keeps pending requests
while Unity recompiles. A bundled Roslyn worker prepares C# independently; Unity
loads the result and executes Unity API calls on its main thread. Project script
changes still require Unity compilation and domain reload.

- Unity starts the registered host asynchronously and prepares the compiler using
  the project's references. The host exits after 30 seconds without a running
  Editor or pending work.
- Repeated snippets reuse compiler preparation, while every invocation emits a
  fresh assembly identity and executes again. Results and static state are not cached.
- Connector network I/O runs in the background. Tool invocation and result
  serialization remain on Unity's main thread.
- `--backend auto|host|legacy` selects routing. `auto` uses a compatible registered
  host when ready and supports the direct route otherwise. `Host: running` does
  not mean Unity is ready; `wait-ready` still requires Unity's live response.

Host-enabled bundles include their .NET runtime; end users do not need an SDK.
They require a [.NET 10 supported operating system](https://github.com/dotnet/core/blob/main/release-notes/10.0/supported-os.md),
which is a separate requirement from the Connector's Unity version compatibility.
See [backend behavior](docs/COMMANDS.md#execution-backend) and
[installation requirements](docs/INSTALL.md#host-enabled-builds).
The [initial validation report](docs/HOST_VALIDATION.md) records the comparison
with v0.2.3, including cold-start costs, memory use, and verification limits.
The [follow-up optimization report](docs/HOST_OPTIMIZATION.md) records later
changes measured on earlier alpha development commits.

The release includes lighter
CLI startup, a persistent JSONL `session`, immediate host state-change hints,
operation-specific completion checks, shared-reference cache accounting, and
ReadyToRun compiler publishing.
See the [measurements and tradeoffs](docs/SPEED_FOLLOWUP.md). Automatic update
checks keep their existing behavior.

The CLI and host remain in Python while reducing single `exec`
startup work when a compatible host is running. Existing command syntax and
per-request execution are preserved. See the [exec comparison](docs/EXEC_OPTIMIZATION.md)
for the separate follow-up measurement collected before the RC2 version bump.

The release starts preparation earlier, forwards lightweight commands,
and reuses session connections and compiler preparation. See the
[Python startup comparison](docs/PYTHON_STARTUP.md) for historical measurements
and their verification scope.

## Quick Start

### 1. Install The Unity Package

In Unity Editor, open `Window > Package Manager > + > Add package from git URL...`
and paste:

```text
https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#main
```

The connector supports Unity 2020.3 LTS through Unity 6.

This URL follows the `main` branch. When newer versions land on `main`, use the
Package Manager `Update` button to fetch the latest connector commit.

### 2. Install The CLI

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1 | iex
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh | sh
```

### 3. Check The Connection

Keep the Unity project open, then run:

```powershell
unity-bridge status
unity-bridge tools
```

### Recommended Editor Setting

For more reliable background responsiveness, set:

```text
Edit > Preferences > General > Interaction Mode > No Throttling
```

More details are covered in [docs/INSTALL.md](docs/INSTALL.md#recommended-editor-setting).

## Essential Commands

```powershell
unity-bridge instances
unity-bridge status
unity-bridge wait-ready --timeout-sec 300
unity-bridge tools
```

`status` reads the saved heartbeat; `wait-ready` confirms the current state with
the Editor and returns on `ready` without a fixed 0.5-second settling delay.
Update both the CLI and Unity Connector to use live readiness checks. For branch
builds, install both from the same branch as described in
[Python package mode](docs/PYTHON_PACKAGE.md#install-from-a-branch).
After editing scripts, request compilation and wait for completion:

```powershell
unity-bridge console --count 50
unity-bridge refresh --path Assets/Scripts/Player.cs --compile request --wait
unity-bridge test --mode EditMode
```

Standalone `wait-ready` does not request compilation or wait for unrelated work
that starts after the Editor responds. See [CLI commands](docs/COMMANDS.md) for
the readiness and refresh options.

v0.2.3 keeps the periodic heartbeat interval at 0.5 seconds.
Server start and pause/resume events publish immediately; other observed state
changes publish on the next Editor update. `Heartbeat age` is the age of that
saved snapshot. A busy or throttled Editor can take longer to update it.

```powershell
unity-bridge editor play --wait
unity-bridge editor stop --wait
unity-bridge exec --file .\query.cs
```

Use `--json` when another program should parse the output:

```powershell
unity-bridge --json status
unity-bridge --json console --count 20
```

Custom Unity-side tools can be called directly by name:

```powershell
unity-bridge my_custom_tool --key value
unity-bridge call my_custom_tool --params '{"key":"value"}'
```

Update the CLI:

```powershell
unity-bridge update --check
unity-bridge update
```

## Documentation

- [Release notes](docs/RELEASE_NOTES.md): changes, upgrade requirements, and validation for the current release.
- [docs/INSTALL.md](docs/INSTALL.md): standalone installation, version pinning, updates, and release assets.
- [docs/COMMANDS.md](docs/COMMANDS.md): CLI commands, common options, custom tool calls.
- [docs/PYTHON_PACKAGE.md](docs/PYTHON_PACKAGE.md): Python package mode for development and direct Python integration.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): CLI module ownership, command changes, and regression checks.

## License

UnityBridge is licensed under the MIT License.

Third-party license notices are listed in [NOTICE.md](NOTICE.md).
