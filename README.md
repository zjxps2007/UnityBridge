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

## Documentation

- [INSTALL.md](INSTALL.md): standalone installation, version pinning, updates, and release assets.
- [COMMANDS.md](COMMANDS.md): CLI commands, common options, custom tool calls.
- [PYTHON_PACKAGE.md](PYTHON_PACKAGE.md): Python package mode for development and agent integrations.

## License

UnityBridge is licensed under the MIT License.

Third-party license notices are listed in [NOTICE.md](NOTICE.md).
