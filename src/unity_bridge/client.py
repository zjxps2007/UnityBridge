from __future__ import annotations

import ctypes
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_TIMEOUT_MS = 120_000
DEFAULT_READY_TIMEOUT_SEC = 300
DEFAULT_POLL_INTERVAL_SEC = 0.5
UNKNOWN_COMPLETION = "unknown"

ProcessDeadChecker = Callable[[int], bool]
InstanceResolver = Callable[[], "Instance"]


class UnityBridgeError(Exception):
    """Base error for the UnityBridge Python client."""


class DiscoveryError(UnityBridgeError):
    """Raised when no suitable Unity Connector instance can be found."""


class UnityConnectionError(UnityBridgeError):
    """Raised when the Unity Connector cannot be reached."""


class UnityHttpError(UnityConnectionError):
    """Raised when the Unity Connector returns a non-200 HTTP response."""

    def __init__(self, status_code: int, body: str, command: str) -> None:
        detail = body or f"HTTP {status_code} from Unity (command: {command})"
        super().__init__(detail)
        self.status_code = status_code
        self.body = body
        self.command = command


@dataclass(frozen=True)
class Instance:
    state: str
    project_path: str
    port: int
    pid: int
    unity_version: str = ""
    connector_version: str = ""
    timestamp: int = 0
    compile_errors: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Instance":
        return cls(
            state=str(data.get("state", "")),
            project_path=str(data.get("projectPath", "")),
            port=int(data.get("port") or 0),
            pid=int(data.get("pid") or 0),
            unity_version=str(data.get("unityVersion", "") or ""),
            connector_version=str(data.get("connectorVersion", "") or ""),
            timestamp=int(data.get("timestamp") or 0),
            compile_errors=bool(data.get("compileErrors", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "projectPath": self.project_path,
            "port": self.port,
            "pid": self.pid,
            "unityVersion": self.unity_version,
            "connectorVersion": self.connector_version,
            "timestamp": self.timestamp,
            "compileErrors": self.compile_errors,
        }

    @property
    def is_active(self) -> bool:
        return self.state != "stopped" and self.timestamp > 0

    @property
    def heartbeat_age_seconds(self) -> float | None:
        if self.timestamp <= 0:
            return None
        return max(0.0, (time.time() * 1000 - self.timestamp) / 1000)


@dataclass(frozen=True)
class CommandResponse:
    success: bool
    message: str
    data: Any = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommandResponse":
        return cls(
            success=bool(data.get("success", False)),
            message=str(data.get("message", "")),
            data=data.get("data"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["data"] is None:
            payload.pop("data")
        return payload

    @property
    def completion_unknown(self) -> bool:
        return isinstance(self.data, dict) and self.data.get("completion") == UNKNOWN_COMPLETION


class UnityClient:
    def __init__(
        self,
        *,
        project: str | Path | None = None,
        port: int | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        instances_dir: str | Path | None = None,
        cwd: str | Path | None = None,
        process_checker: ProcessDeadChecker | None = None,
    ) -> None:
        self.project = str(project) if project is not None else ""
        self.port = port
        self.timeout_ms = timeout_ms
        self.instances_dir = Path(instances_dir) if instances_dir is not None else default_instances_dir()
        self.cwd = Path(cwd) if cwd is not None else None
        self.process_checker = process_checker

    def scan_instances(self, *, remove_stale: bool = True) -> list[Instance]:
        return scan_instances(
            instances_dir=self.instances_dir,
            remove_stale=remove_stale,
            process_checker=self.process_checker,
        )

    def discover_instance(self) -> Instance:
        return discover_instance(
            project=self.project,
            port=self.port,
            instances_dir=self.instances_dir,
            cwd=self.cwd,
            process_checker=self.process_checker,
        )

    def status(self) -> Instance:
        if self.port is not None:
            return find_by_port(
                self.port,
                instances_dir=self.instances_dir,
                process_checker=self.process_checker,
            )
        return self.discover_instance()

    def call(
        self,
        command: str,
        params: Any | None = None,
        *,
        timeout_ms: int | None = None,
        instance: Instance | None = None,
    ) -> CommandResponse:
        target = instance or self.discover_instance()
        return send_command(target, command, params, timeout_ms=timeout_ms or self.timeout_ms)

    def wait_for_alive(self, *, timeout_ms: int | None = None) -> Instance:
        return wait_for_alive(
            self.discover_instance,
            timeout_ms=timeout_ms or self.timeout_ms,
        )

    def wait_for_ready(
        self,
        *,
        timeout_sec: int = DEFAULT_READY_TIMEOUT_SEC,
        after_timestamp: int = 0,
        stable_sec: float = 0,
    ) -> Instance:
        return wait_for_ready(
            self.status,
            timeout_sec=timeout_sec,
            after_timestamp=after_timestamp,
            stable_sec=stable_sec,
        )

    def wait_for_state(
        self,
        states: str | set[str] | tuple[str, ...] | list[str],
        *,
        timeout_sec: int = DEFAULT_READY_TIMEOUT_SEC,
        after_timestamp: int = 0,
        stable_sec: float = 0,
    ) -> Instance:
        return wait_for_state(
            self.status,
            states,
            timeout_sec=timeout_sec,
            after_timestamp=after_timestamp,
            stable_sec=stable_sec,
        )


def default_instances_dir() -> Path:
    return Path.home() / ".unity-bridge" / "instances"


def scan_instances(
    *,
    instances_dir: str | Path | None = None,
    remove_stale: bool = True,
    process_checker: ProcessDeadChecker | None = None,
) -> list[Instance]:
    directory = Path(instances_dir) if instances_dir is not None else default_instances_dir()
    checker = process_checker or is_process_dead
    if not directory.exists():
        return []

    instances: list[Instance] = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
        if path.is_dir() or path.suffix.lower() != ".json":
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            instance = Instance.from_dict(raw)
        except (OSError, ValueError, json.JSONDecodeError):
            continue

        if remove_stale and instance.pid > 0 and checker(instance.pid):
            try:
                path.unlink()
            except OSError:
                pass
            continue
        instances.append(instance)
    return instances


def find_by_port(
    port: int,
    *,
    instances_dir: str | Path | None = None,
    process_checker: ProcessDeadChecker | None = None,
) -> Instance:
    matches = [
        instance
        for instance in scan_instances(instances_dir=instances_dir, process_checker=process_checker)
        if instance.port == port
    ]
    if not matches:
        raise DiscoveryError(f"no instance on port {port}")
    return max(matches, key=lambda instance: instance.timestamp)


def find_active_by_port(
    port: int,
    *,
    instances_dir: str | Path | None = None,
    process_checker: ProcessDeadChecker | None = None,
) -> Instance:
    matches = [
        instance
        for instance in scan_instances(instances_dir=instances_dir, process_checker=process_checker)
        if instance.port == port and instance.is_active
    ]
    if not matches:
        raise DiscoveryError(f"no active instance on port {port}")
    return max(matches, key=lambda instance: instance.timestamp)


def discover_instance(
    project: str | Path | None = None,
    port: int | None = None,
    *,
    instances_dir: str | Path | None = None,
    cwd: str | Path | None = None,
    process_checker: ProcessDeadChecker | None = None,
) -> Instance:
    if port is not None and port > 0:
        return find_active_by_port(
            port,
            instances_dir=instances_dir,
            process_checker=process_checker,
        )

    directory = Path(instances_dir) if instances_dir is not None else default_instances_dir()
    instances = scan_instances(instances_dir=directory, process_checker=process_checker)
    if not instances:
        raise DiscoveryError("no Unity instances found. Is Unity running with the Connector package?")

    alive = [instance for instance in instances if instance.is_active]
    if not alive:
        raise DiscoveryError("no Unity instances running")

    project_filter = _path_key(project) if project else ""
    if project_filter:
        exact = [instance for instance in alive if _path_key(instance.project_path) == project_filter]
        if exact:
            return _most_recent(exact)

        containing = [
            instance
            for instance in alive
            if _is_same_or_child(project_filter, _path_key(instance.project_path))
        ]
        if containing:
            return _most_specific(containing)

        suffix = [
            instance
            for instance in alive
            if _has_path_suffix(_path_key(instance.project_path), project_filter)
        ]
        if len(suffix) == 1:
            return suffix[0]
        if len(suffix) > 1:
            raise DiscoveryError(
                f"multiple Unity instances match project '{project}': {_format_instance_matches(suffix)}"
            )
        raise DiscoveryError(f"no Unity instance found for project: {project}")

    cwd_path = Path(cwd) if cwd is not None else Path.cwd()
    cwd_norm = _path_key(cwd_path)
    cwd_matches = [
        instance
        for instance in alive
        if _is_same_or_child(cwd_norm, _path_key(instance.project_path))
    ]
    if cwd_matches:
        return _most_specific(cwd_matches)

    return _most_recent(alive)


def send_command(
    instance: Instance,
    command: str,
    params: Any | None = None,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> CommandResponse:
    if params is None:
        params = {}
    body = json.dumps({"command": command, "params": params}).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{instance.port}/command",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_ms / 1000) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8", errors="replace")
        except OSError:
            error_body = ""
        raise UnityHttpError(exc.code, error_body, command) from exc
    except (OSError, TimeoutError) as exc:
        raise UnityConnectionError(f"cannot connect to Unity at port {instance.port}: {exc}") from exc

    if not response_body:
        return CommandResponse(
            success=True,
            message=f"{command} sent (connection closed before response)",
            data={
                "accepted": True,
                "completion": UNKNOWN_COMPLETION,
                "connection_closed": True,
                "command": command,
            },
        )

    text = response_body.decode("utf-8", errors="replace")
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return CommandResponse(success=True, message=text)
    if not isinstance(decoded, dict):
        return CommandResponse(success=True, message=text)
    return CommandResponse.from_dict(decoded)


def wait_for_alive(
    resolve: InstanceResolver,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
) -> Instance:
    baseline = int(time.time() * 1000)
    try:
        instance = resolve()
    except DiscoveryError:
        instance = None
    else:
        baseline = instance.timestamp
        if int(time.time() * 1000) - baseline < 1000:
            return instance

    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        time.sleep(poll_interval_sec)
        try:
            instance = resolve()
        except DiscoveryError:
            continue
        if instance.timestamp > baseline:
            return instance
    raise DiscoveryError("timed out waiting for Unity")


def wait_for_ready(
    resolve: InstanceResolver,
    *,
    timeout_sec: int = DEFAULT_READY_TIMEOUT_SEC,
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    after_timestamp: int = 0,
    stable_sec: float = 0,
) -> Instance:
    return wait_for_state(
        resolve,
        "ready",
        timeout_sec=timeout_sec,
        poll_interval_sec=poll_interval_sec,
        after_timestamp=after_timestamp,
        stable_sec=stable_sec,
        timeout_label="Unity compilation",
    )


def wait_for_state(
    resolve: InstanceResolver,
    states: str | set[str] | tuple[str, ...] | list[str],
    *,
    timeout_sec: int = DEFAULT_READY_TIMEOUT_SEC,
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    after_timestamp: int = 0,
    stable_sec: float = 0,
    timeout_label: str = "Unity state",
) -> Instance:
    wanted = {states} if isinstance(states, str) else set(states)
    if not wanted:
        raise DiscoveryError("wait_for_state requires at least one state")

    deadline = time.monotonic() + timeout_sec
    latest: Instance | None = None
    state_since: float | None = None
    while time.monotonic() < deadline:
        time.sleep(poll_interval_sec)
        try:
            latest = resolve()
        except DiscoveryError:
            state_since = None
            continue
        if after_timestamp and latest.timestamp <= after_timestamp:
            state_since = None
            continue
        if latest.state in wanted:
            now = time.monotonic()
            if state_since is None:
                state_since = now
            if now - state_since >= stable_sec:
                return latest
        else:
            state_since = None
    detail = f" last_state={latest.state}" if latest is not None else ""
    states_label = ", ".join(sorted(wanted))
    raise DiscoveryError(f"timed out waiting for {timeout_label} '{states_label}' ({timeout_sec}s).{detail}")


def is_process_dead(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _is_windows_process_dead(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        return False
    return False


def _is_windows_process_dead(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32
    process_query_limited_information = 0x1000
    still_active = 259
    error_invalid_parameter = 87
    handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
    if not handle:
        return kernel32.GetLastError() == error_invalid_parameter
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value != still_active
    finally:
        kernel32.CloseHandle(handle)


def _slash_path(value: str | Path) -> str:
    return str(value).replace("\\", "/").rstrip("/")


def _path_key(value: str | Path) -> str:
    path = _slash_path(value)
    return path.casefold() if os.name == "nt" else path


def _is_same_or_child(path: str, parent: str) -> bool:
    path_parts = _path_parts(path)
    parent_parts = _path_parts(parent)
    return len(path_parts) >= len(parent_parts) and path_parts[: len(parent_parts)] == parent_parts


def _has_path_suffix(path: str, suffix: str) -> bool:
    path_parts = _path_parts(path)
    suffix_parts = _path_parts(suffix)
    return len(path_parts) >= len(suffix_parts) and path_parts[-len(suffix_parts) :] == suffix_parts


def _path_parts(value: str | Path) -> tuple[str, ...]:
    return tuple(part for part in _path_key(value).split("/") if part)


def _most_recent(instances: list[Instance]) -> Instance:
    return max(instances, key=lambda instance: instance.timestamp)


def _most_specific(instances: list[Instance]) -> Instance:
    return max(instances, key=lambda instance: (len(_path_key(instance.project_path)), instance.timestamp))


def _format_instance_matches(instances: list[Instance]) -> str:
    return ", ".join(f"{instance.project_path} (port {instance.port})" for instance in instances)
