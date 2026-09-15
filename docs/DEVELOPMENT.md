# CLI maintenance

[한국어](DEVELOPMENT.ko.md) | English

The public entry point remains `unity_bridge.cli:main`. Installed commands,
`python -m unity_bridge`, and the standalone build all use this function.
Implementation modules live in `src/unity_bridge/_cli/`.

| File | Responsibility |
|---|---|
| `cli.py` | Select the built-in or direct-tool route, create the client, print the result, and choose the exit code. |
| `_cli/arguments.py` | Built-in options and help; direct-tool flags, repeated values, positionals, and JSON parameters. |
| `_cli/commands.py` | Map parsed built-in options to `UnityClient` and `UnityBridgeAdapter` calls; read C# code input. |
| `_cli/output.py` | Text and JSON rendering, errors, Connector version warnings, and update output. |
| `_cli/updates.py` | Python package updates, scheduling standalone updates, remote versions, and daily notice caching. |
| `_cli/standalone.py` | Platform/architecture selection and platform-specific installer command construction. |
| `_cli/versions.py` | Shared version parsing and comparison. |

The `_cli` package is internal. Python integrations should use the client and
adapter APIs exported by `unity_bridge`. The existing `cli.build_parser` and
`cli.add_common_options` functions remain available.

## Changing a command

1. Define its options and add its name to `KNOWN_COMMANDS` in `arguments.py`.
2. Map those options in `commands.execute_command`. Return the client/adapter
   result; the entry point handles printing and success/failure exit codes.
3. Add request-level coverage in `tests/test_cli.py`. Command syntax, emitted
   JSON, stdout/stderr, and exit codes are compatibility contracts.

Unknown command names follow the direct-tool parser. Keep its repeated flags,
`--params`, and `--` handling independent of built-in argparse options. Direct
tools reuse the instance already discovered for the request. JSON output must
retain the shallow wrapper around response data rather than copy nested payloads.

Keep argument parsing ahead of update-module imports so help can finish early.
Installed-package metadata is loaded only when an update/version check needs it.
Automatic notices retain their existing daily cache, skip flags, and timeout.

## Validation

From the repository root:

```sh
python -m unittest discover -s tests
python -m compileall -q src tests
git diff --check
```

For CLI changes alone:

```sh
python -m unittest discover -s tests -p test_cli.py
```

`tests/test_client.py` covers discovery, HTTP, and adapters. Shared temporary
heartbeat and HTTP fixtures are in `tests/helpers.py`. `tests/fixtures/cli_requests.json`
records 21 request contracts captured before the CLI split; change these only
when an intentional command contract change also updates its documentation.
`tests/test_installers.py` uses offline fixture downloads and temporary install
directories; platform tests are skipped when the required platform or shell is absent.

For standalone changes, build an archive with `scripts/build-standalone.py`,
unpack it, and exercise the resulting executable. Compare startup with the same
Python/PyInstaller versions and build mode; source-import timing alone does not
verify the packaged command. Native Unity checks are described in
[tests/unity/README.md](../tests/unity/README.md).
