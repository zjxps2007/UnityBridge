"""Package updates, remote versions, and the optional daily update notice."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from .. import __version__
from ..client import DiscoveryError
from . import DEFAULT_REPOSITORY_URL
from .output import format_shell_command, print_update_check_payload, print_update_payload
from .standalone import (
    install_mode, is_standalone_build, standalone_asset_name,
    standalone_update_command, standalone_update_version,
)
from .versions import parse_pyproject_version, version_status


AUTO_UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
AUTO_UPDATE_CHECK_TIMEOUT_SECONDS = 2


def run_update(args: argparse.Namespace) -> int:
    if args.check:
        return _run_update_check(args)
    if is_standalone_build():
        return _run_standalone_update(args)

    package_spec = args.package_spec or _git_package_spec(args.repo, args.ref)
    command = [sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall", package_spec]
    connector_url = _connector_package_url(args.repo, args.ref)
    payload = {
        "ok": True,
        "dry_run": bool(args.dry_run),
        "command": command,
        "package_spec": package_spec,
        "connector_url": connector_url,
        "note": "This updates the Python CLI package. Update the Unity Connector package separately in Unity Package Manager if needed.",
    }

    if args.dry_run:
        print_update_payload(payload, json_output=args.json)
        return 0

    if not args.json:
        print("Updating UnityBridge Python package...")
        print(format_shell_command(command))

    completed = subprocess.run(command)
    payload["ok"] = completed.returncode == 0
    payload["returncode"] = completed.returncode

    if args.json:
        print_update_payload(payload, json_output=True)
    elif completed.returncode == 0:
        print("UnityBridge Python package updated.")
        print(f"Unity Connector package URL: {connector_url}")
    else:
        print(f"UnityBridge update failed with exit code {completed.returncode}.", file=sys.stderr)
    return int(completed.returncode)


def _run_standalone_update(args: argparse.Namespace) -> int:
    if args.package_spec:
        raise DiscoveryError("--package-spec is only supported by Python package installs")

    version = standalone_update_version(args.ref)
    command = standalone_update_command(version, wait_pid=os.getpid())
    connector_ref = "main" if version == "latest" else version
    connector_url = _connector_package_url(args.repo, connector_ref)
    asset_name = standalone_asset_name()
    payload = {
        "ok": True,
        "mode": "standalone",
        "dry_run": bool(args.dry_run),
        "command": command,
        "version": version,
        "asset_name": asset_name,
        "connector_url": connector_url,
        "note": "This installs the standalone bundle from GitHub Releases. Update the Unity Connector package separately in Unity Package Manager if needed.",
    }

    if args.dry_run:
        print_update_payload(payload, json_output=args.json)
        return 0

    if not args.json:
        print("Updating UnityBridge standalone executable...")
        print(format_shell_command(command))

    try:
        popen_kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(command, **popen_kwargs)
    except OSError as exc:
        payload["ok"] = False
        payload["error"] = str(exc)
        if args.json:
            print_update_payload(payload, json_output=True)
        else:
            print(f"UnityBridge standalone update failed to start: {exc}", file=sys.stderr)
        return 1

    payload["scheduled"] = True

    if args.json:
        print_update_payload(payload, json_output=True)
    else:
        print("UnityBridge standalone executable update requested.")
        print("Open a new terminal if PATH changes were applied.")
        print(f"Unity Connector package URL: {connector_url}")
    return 0


def _run_update_check(args: argparse.Namespace) -> int:
    package_spec = args.package_spec or _git_package_spec(args.repo, args.ref)
    connector_url = _connector_package_url(args.repo, args.ref)
    current_version = _current_package_version()
    latest_version = _remote_python_version(args.repo, args.ref)
    connector_version = _remote_connector_version(args.repo, args.ref)
    status = version_status(current_version, latest_version)
    payload = {
        "ok": True,
        "check": True,
        "mode": install_mode(),
        "repo": args.repo,
        "ref": args.ref,
        "package_spec": package_spec,
        "connector_url": connector_url,
        "current_version": current_version,
        "latest_version": latest_version,
        "target_connector_version": connector_version,
        "status": status,
        "update_available": status == "outdated",
        "note": "This checks the installed UnityBridge CLI version. Update the Unity Connector package separately in Unity Package Manager if needed.",
    }
    if is_standalone_build():
        payload["asset_name"] = standalone_asset_name()
    print_update_check_payload(payload, json_output=args.json)
    return 0


def maybe_print_update_notice(args: argparse.Namespace) -> None:
    if not _should_auto_update_check(args):
        return

    cache_path = _update_check_cache_path()
    now = time.time()
    if not _auto_update_check_due(cache_path, now=now):
        return

    payload: dict[str, Any] = {"checked_at": now}
    try:
        current_version = _current_package_version()
        latest_version = _remote_python_version(
            DEFAULT_REPOSITORY_URL,
            "main",
            timeout_sec=AUTO_UPDATE_CHECK_TIMEOUT_SECONDS,
        )
        status = version_status(current_version, latest_version)
        payload.update(
            {
                "current_version": current_version,
                "latest_version": latest_version,
                "status": status,
            }
        )
        if status == "outdated":
            print(
                f"UnityBridge update available: {current_version} -> {latest_version}. Run: unity-bridge update",
                file=sys.stderr,
            )
    except Exception as exc:  # noqa: BLE001 - update notices must never break the requested command.
        payload["error"] = str(exc)
    finally:
        _write_update_check_cache(cache_path, payload)


def _should_auto_update_check(args: argparse.Namespace) -> bool:
    if getattr(args, "command", "") == "update":
        return False
    if getattr(args, "json", False):
        return False
    if getattr(args, "no_update_check", False):
        return False
    return not _env_flag_enabled("UNITY_BRIDGE_SKIP_UPDATE_CHECK")


def _env_flag_enabled(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _update_check_cache_path() -> Path:
    return Path.home() / ".unity-bridge" / "update-check.json"


def _auto_update_check_due(path: Path, *, now: float) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if not isinstance(payload, dict):
        return True
    checked_at = payload.get("checked_at")
    if not isinstance(checked_at, (int, float)):
        return True
    return now - float(checked_at) >= AUTO_UPDATE_CHECK_INTERVAL_SECONDS


def _write_update_check_cache(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _git_package_spec(repo: str, ref: str) -> str:
    repo = repo.strip()
    ref = ref.strip()
    if not ref:
        return f"git+{repo}"
    return f"git+{repo}@{ref}"


def _connector_package_url(repo: str, ref: str) -> str:
    repo = repo.strip()
    ref = ref.strip()
    suffix = f"#{ref}" if ref else ""
    return f"{repo}?path=/unity-bridge-connector{suffix}"


def _current_package_version() -> str:
    if is_standalone_build():
        return __version__
    import importlib.metadata as importlib_metadata

    try:
        return importlib_metadata.version("unity-bridge")
    except importlib_metadata.PackageNotFoundError:
        return _local_python_version()


def _local_python_version() -> str:
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    try:
        return parse_pyproject_version(pyproject.read_text(encoding="utf-8"))
    except OSError:
        return __version__ or "unknown"


def _remote_python_version(repo: str, ref: str, *, timeout_sec: float = 10) -> str:
    return parse_pyproject_version(
        _read_remote_repository_file(repo, ref, "pyproject.toml", timeout_sec=timeout_sec)
    )


def _remote_connector_version(repo: str, ref: str, *, timeout_sec: float = 10) -> str:
    text = _read_remote_repository_file(
        repo,
        ref,
        "unity-bridge-connector/package.json",
        timeout_sec=timeout_sec,
    )
    try:
        value = json.loads(text).get("version")
    except json.JSONDecodeError as exc:
        raise DiscoveryError(f"failed to parse remote connector package.json: {exc}") from exc
    if not isinstance(value, str) or not value:
        raise DiscoveryError("remote connector package.json does not contain a version")
    return value


def _read_remote_repository_file(repo: str, ref: str, path: str, *, timeout_sec: float = 10) -> str:
    owner, name = _parse_github_repo(repo)
    encoded_path = urllib.parse.quote(path, safe="/")
    encoded_ref = urllib.parse.quote(ref or "main", safe="")
    url = f"https://api.github.com/repos/{owner}/{name}/contents/{encoded_path}?ref={encoded_ref}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.raw",
            "User-Agent": "unity-bridge-cli",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raise DiscoveryError(f"failed to check remote version: GitHub returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise DiscoveryError(f"failed to check remote version: {exc.reason}") from exc

    text = body.decode("utf-8")
    if "json" not in content_type.lower():
        return text

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    content = payload.get("content")
    encoding = payload.get("encoding")
    if isinstance(content, str) and encoding == "base64":
        return base64.b64decode(content).decode("utf-8")
    return text


def _parse_github_repo(repo: str) -> tuple[str, str]:
    repo = repo.strip()
    ssh_match = re.fullmatch(r"git@github\.com:([^/]+)/(.+?)(?:\.git)?", repo)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    parsed = urllib.parse.urlparse(repo)
    if parsed.hostname not in {"github.com", "www.github.com"}:
        raise DiscoveryError("--check currently supports github.com repository URLs")
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2:
        raise DiscoveryError("--check requires a GitHub repository URL")
    name = parts[1]
    if name.endswith(".git"):
        name = name[:-4]
    return parts[0], name
