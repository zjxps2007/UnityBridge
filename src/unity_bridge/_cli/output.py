"""Human-readable and JSON output shared by every CLI route."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .. import __version__
from ..client import CommandResponse, Instance, UnityBridgeError, UnityClient
from .versions import version_key


def print_result(value: Any, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(to_jsonable(value), ensure_ascii=False, indent=2))
        return

    if isinstance(value, list):
        if not value:
            print("No Unity instances found.")
            return
        for instance in value:
            _print_instance(instance)
        return
    if isinstance(value, Instance):
        _print_instance(value)
        return
    from ..adapter import UnityActionResult
    if isinstance(value, (CommandResponse, UnityActionResult)):
        print(render_action_result(value, json_output=False), end="")
        return
    print(value)


def render_action_result(value: Any, *, json_output: bool) -> str:
    """Render a command without redirecting process-global output streams."""
    if json_output:
        return json.dumps(to_jsonable(value), ensure_ascii=False, indent=2) + "\n"
    text = str(value.message) + "\n"
    if value.data is not None:
        text += json.dumps(value.data, ensure_ascii=False, indent=2) + "\n"
    return text


def _print_instance(instance: Instance) -> None:
    age = instance.heartbeat_age_seconds
    age_label = "unknown" if age is None else f"{age:.1f}s"
    print(f"Unity (port {instance.port}): {instance.state}")
    print(f" Project: {instance.project_path}")
    print(f" Version: {instance.unity_version or 'unknown'}")
    print(f" Connector: {instance.connector_version or 'unknown'}")
    print(f" PID: {instance.pid}")
    print(f" Heartbeat age: {age_label}")
    if instance.host_status is not None:
        host = instance.host_status
        print(f" Host: {host.get('state', 'unavailable')}" +
              (f" ({host['version']})" if host.get('version') else ""))
    print_connector_version_warning(instance, json_output=False)


def warn_for_selected_connector_version(client: UnityClient, *, json_output: bool) -> None:
    if json_output:
        return
    instance = client.discover_instance()
    print_connector_version_warning(instance, json_output=json_output)


def print_connector_version_warning(instance: Instance, *, json_output: bool) -> None:
    if json_output:
        return
    warning = _connector_version_warning(instance)
    if warning:
        print(warning, file=sys.stderr)


def _connector_version_warning(instance: Instance) -> str | None:
    connector_version = (instance.connector_version or "").strip()
    if not connector_version or connector_version.lower() == "unknown":
        return None

    cli_version = __version__
    if not cli_version or cli_version == "unknown":
        return None

    connector_key = version_key(connector_version)
    cli_key = version_key(cli_version)
    versions_differ = (
        connector_key != cli_key
        if connector_key is not None and cli_key is not None
        else connector_version != cli_version
    )
    if not versions_differ:
        return None

    return (
        f"WARNING: Unity Connector version {connector_version} differs from "
        f"UnityBridge CLI version {cli_version}. Update the Unity package if "
        "commands behave unexpectedly."
    )


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Instance):
        return value.to_dict()
    if isinstance(value, CommandResponse):
        payload = {"success": value.success, "message": value.message}
        if value.data is not None:
            payload["data"] = value.data
        return payload
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    from ..adapter import UnityActionResult
    if isinstance(value, UnityActionResult):
        payload = {
            "tool": value.tool,
            "command": value.command,
            "params": value.params,
            "success": value.success,
            "message": value.message,
        }
        if value.data is not None:
            payload["data"] = value.data
        return payload
    return value


def print_update_payload(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(format_shell_command(payload["command"]))
    if payload.get("asset_name"):
        print(f"Standalone asset: {payload['asset_name']}")
    print(f"Unity Connector package URL: {payload['connector_url']}")
    print(payload["note"])


def print_update_check_payload(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    label = "UnityBridge standalone CLI" if payload.get("mode") == "standalone" else "UnityBridge Python package"
    current = payload["current_version"]
    latest = payload["latest_version"]
    status = payload["status"]
    if status == "outdated":
        print(f"{label}: {current} -> {latest} available")
        print("Run: unity-bridge update")
    elif status == "current":
        print(f"{label}: {current} (up to date)")
    elif status == "newer":
        print(f"{label}: {current} (newer than {latest})")
    else:
        print(f"{label}: {current} (latest: {latest})")
    if payload.get("asset_name"):
        print(f"Standalone asset: {payload['asset_name']}")
    print(f"Target Unity Connector version: {payload['target_connector_version']}")
    print(f"Unity Connector package URL: {payload['connector_url']}")
    print(payload["note"])


def format_shell_command(command: list[str]) -> str:
    return " ".join(_quote_command_part(part) for part in command)


def _quote_command_part(value: str) -> str:
    if not value or any(ch.isspace() for ch in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def print_error(error: UnityBridgeError, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
    else:
        print(f"ERROR: {error}", file=sys.stderr)
