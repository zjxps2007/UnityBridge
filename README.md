# UnityBridge

[한국어](README.ko.md) | English

UnityBridge is a standalone CLI, Python-native client, and Unity package for
controlling the Unity Editor through a local HTTP connector.

The CLI discovers running Unity Editors through
`~/.unity-bridge/instances/*.json` heartbeat files, selects the target Editor,
and sends JSON commands to `http://127.0.0.1:{port}/command`.

## Quick Start

### 1. Install The Unity Package

In Unity Editor, open `Window > Package Manager > + > Add package from git URL...`
and paste:

```text
https://github.com/zjxps2007/UnityBridge.git?path=unity-bridge-connector
```

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
unity-bridge tools
```

```powershell
unity-bridge console --count 50
unity-bridge refresh --path Assets/Scripts/Player.cs --wait
unity-bridge test --mode EditMode
```

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

- [docs/INSTALL.md](docs/INSTALL.md): standalone installation, version pinning, updates, and release assets.
- [docs/COMMANDS.md](docs/COMMANDS.md): CLI commands, common options, custom tool calls.
- [docs/PYTHON_PACKAGE.md](docs/PYTHON_PACKAGE.md): Python package mode for development and direct Python integration.

## License

UnityBridge is licensed under the MIT License.

Third-party license notices are listed in [NOTICE.md](NOTICE.md).
