"""Platform detection and installer commands for standalone builds."""
from __future__ import annotations

import platform
import sys
from pathlib import Path

from ..client import DiscoveryError


DEFAULT_WINDOWS_ASSET_NAME = "unity-bridge-windows-amd64.zip"
DEFAULT_INSTALL_POWERSHELL_SCRIPT_URL = "https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1"
DEFAULT_INSTALL_SHELL_SCRIPT_URL = "https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh"


def is_standalone_build() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_mode() -> str:
    return "standalone" if is_standalone_build() else "python"


def standalone_update_version(ref: str) -> str:
    ref = (ref or "").strip()
    if not ref or ref == "main":
        return "latest"
    if ref.startswith("refs/tags/"):
        return ref[len("refs/tags/") :]
    return ref


def standalone_update_command(version: str, *, wait_pid: int | None = None) -> list[str]:
    if sys.platform == "win32":
        return _standalone_windows_update_command(version, wait_pid=wait_pid)
    return _standalone_posix_update_command(version, wait_pid=wait_pid)


def _standalone_windows_update_command(version: str, *, wait_pid: int | None = None) -> list[str]:
    wait_script = ""
    if wait_pid is not None and wait_pid > 0:
        wait_script = f"try {{ Wait-Process -Id {int(wait_pid)} -Timeout 30 -ErrorAction SilentlyContinue }} catch {{ }}; "
    script = (
        "$ErrorActionPreference = 'Stop'; "
        + wait_script
        + "$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'; "
        + f"Invoke-WebRequest -Uri '{DEFAULT_INSTALL_POWERSHELL_SCRIPT_URL}' -OutFile $script; "
        + f"& $script -Version '{_escape_powershell_single_quoted(version)}' "
        + f"-InstallDir '{_escape_powershell_single_quoted(str(Path(sys.executable).parent))}' -NoPathUpdate"
    )
    return [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "& { " + script + " }",
    ]


def _standalone_posix_update_command(version: str, *, wait_pid: int | None = None) -> list[str]:
    wait_script = ""
    if wait_pid is not None and wait_pid > 0:
        wait_script = (
            f"i=0; while kill -0 {int(wait_pid)} 2>/dev/null && [ $i -lt 30 ]; "
            "do i=$((i + 1)); sleep 1; done; "
        )
    script = (
        "set -e; "
        + wait_script
        + "script=\"${TMPDIR:-/tmp}/unity-bridge-install-$$.sh\"; "
        + "if command -v curl >/dev/null 2>&1; then "
        + f"curl -fsSL {_sh_quote(DEFAULT_INSTALL_SHELL_SCRIPT_URL)} -o \"$script\"; "
        + "elif command -v wget >/dev/null 2>&1; then "
        + f"wget -qO \"$script\" {_sh_quote(DEFAULT_INSTALL_SHELL_SCRIPT_URL)}; "
        + "else echo 'curl or wget is required to update UnityBridge.' >&2; exit 1; fi; "
        + f"sh \"$script\" --version {_sh_quote(version)} "
        + f"--install-dir {_sh_quote(str(Path(sys.executable).parent))} --no-path-update; "
        + "rm -f \"$script\""
    )
    return ["sh", "-c", script]


def standalone_asset_name() -> str:
    os_name = _standalone_os_name()
    arch_name = _standalone_arch_name()
    if os_name == "windows" and arch_name == "amd64":
        return DEFAULT_WINDOWS_ASSET_NAME
    extension = ".zip" if os_name == "windows" else ".tar.gz"
    return f"unity-bridge-{os_name}-{arch_name}{extension}"


def _standalone_os_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    raise DiscoveryError(f"unsupported standalone platform: {sys.platform}")


def _standalone_arch_name() -> str:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "amd64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    raise DiscoveryError(f"unsupported standalone architecture: {machine}")


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _escape_powershell_single_quoted(value: str) -> str:
    return value.replace("'", "''")
