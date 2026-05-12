from __future__ import annotations

import json
import time
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .client import DEFAULT_TIMEOUT_MS
from .client import DEFAULT_READY_TIMEOUT_SEC
from .client import DEFAULT_POLL_INTERVAL_SEC
from .client import CommandResponse
from .client import DiscoveryError
from .client import Instance
from .client import ProcessDeadChecker
from .client import UnityConnectionError
from .client import UnityClient
from .client import discover_instance
from .client import wait_for_ready
from .client import wait_for_state


DEFAULT_TEST_TIMEOUT_SEC = 600
DEFAULT_TEST_POLL_INTERVAL_SEC = 0.5
DISRUPTIVE_SEND_TIMEOUT_MS = 10_000
TEST_FRAMEWORK_MISSING_MESSAGE = (
    "'run_tests' is not available.\n"
    "Install the Unity Test Framework package:\n"
    "  Window > Package Manager > search 'Test Framework' > Install"
)


@dataclass(frozen=True)
class UnityActionResult:
    tool: str
    command: str
    params: dict[str, Any]
    success: bool
    message: str
    data: Any = None

    @classmethod
    def from_response(
        cls,
        *,
        tool: str,
        command: str,
        params: dict[str, Any],
        response: CommandResponse,
    ) -> "UnityActionResult":
        return cls(
            tool=tool,
            command=command,
            params=params,
            success=response.success,
            message=response.message,
            data=response.data,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["data"] is None:
            payload.pop("data")
        return payload


class UnityBridgeAdapter:
    """Agent-friendly convenience layer over the raw Unity connector commands."""

    def __init__(
        self,
        *,
        client: UnityClient | None = None,
        project: str | Path | None = None,
        port: int | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        instances_dir: str | Path | None = None,
        status_dir: str | Path | None = None,
        cwd: str | Path | None = None,
        process_checker: ProcessDeadChecker | None = None,
    ) -> None:
        self.client = client or UnityClient(
            project=project,
            port=port,
            timeout_ms=timeout_ms,
            instances_dir=instances_dir,
            cwd=cwd,
            process_checker=process_checker,
        )
        self.status_dir = Path(status_dir) if status_dir is not None else default_status_dir()

    def call_tool(self, command: str, params: dict[str, Any] | None = None) -> UnityActionResult:
        payload = _compact(params or {})
        response = self.client.call(command, payload)
        return UnityActionResult.from_response(
            tool=command,
            command=command,
            params=payload,
            response=response,
        )

    def list_tools(self) -> UnityActionResult:
        return self._call("tools", "list", {})

    def refresh_assets(
        self,
        *,
        mode: str = "if_dirty",
        force: bool = False,
        paths: str | Path | Iterable[str | Path] | None = None,
        compile: str = "none",
        wait: bool = False,
        timeout_sec: int = DEFAULT_READY_TIMEOUT_SEC,
        stable_sec: float = 0.5,
        poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    ) -> UnityActionResult:
        payload = _compact(
            {
                "mode": mode,
                "force": force,
                "paths": _path_list(paths),
                "compile": compile,
            }
        )
        target = self.client.discover_instance()
        response = self._send_disruptive_command("refresh_unity", payload, target) if wait else self.client.call(
            "refresh_unity",
            payload,
            instance=target,
        )
        result = UnityActionResult.from_response(
            tool="refresh",
            command="refresh_unity",
            params=payload,
            response=response,
        )
        if not wait or not response.success:
            return result

        ready = wait_for_ready(
            lambda: self._resolve_same_project(target),
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
            after_timestamp=target.timestamp,
            stable_sec=stable_sec,
        )
        return _with_data(
            result,
            {
                "completion": "confirmed",
                "ready": ready.to_dict(),
                "initial_port": target.port,
                "current_port": ready.port,
            },
        )

    def wait_for_ready(
        self,
        *,
        timeout_sec: int = DEFAULT_READY_TIMEOUT_SEC,
        stable_sec: float = 0.5,
        poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    ) -> Instance:
        target = self.client.discover_instance()
        return wait_for_ready(
            lambda: self._resolve_same_project(target),
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
            after_timestamp=target.timestamp,
            stable_sec=stable_sec,
        )

    def wait_for_state(
        self,
        states: str | Iterable[str],
        *,
        timeout_sec: int = DEFAULT_READY_TIMEOUT_SEC,
        stable_sec: float = 0,
        poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
        after_timestamp: int = 0,
    ) -> Instance:
        target = self.client.discover_instance()
        return wait_for_state(
            lambda: self._resolve_same_project(target),
            states,
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
            after_timestamp=after_timestamp or target.timestamp,
            stable_sec=stable_sec,
        )

    def read_console(
        self,
        *,
        count: int | None = 50,
        types: str | Iterable[str] | None = None,
        stacktrace: str = "user",
    ) -> UnityActionResult:
        return self._call(
            "console",
            "console",
            {
                "count": count,
                "type": _join_csv(types, default="error,warning,log"),
                "stacktrace": stacktrace,
            },
        )

    def clear_console(self) -> UnityActionResult:
        return self._call("console", "console", {"clear": True})

    def run_tests(
        self,
        *,
        mode: str = "EditMode",
        filter: str | None = None,
        allow_dirty_scenes: bool = False,
        auto_save_scenes: bool = False,
        wait: bool | None = None,
        timeout_sec: int = DEFAULT_TEST_TIMEOUT_SEC,
        poll_interval_sec: float = DEFAULT_TEST_POLL_INTERVAL_SEC,
    ) -> UnityActionResult:
        payload = _compact(
            {
                "mode": mode,
                "filter": filter,
                "allow_dirty_scenes": allow_dirty_scenes,
                "auto_save_scenes": auto_save_scenes,
            }
        )
        target = self.client.discover_instance()
        should_wait = wait if wait is not None else mode.lower() == "playmode"
        is_playmode = mode.lower() == "playmode"
        try:
            response = self.client.call(
                "run_tests",
                payload,
                instance=target,
                timeout_ms=self._disruptive_send_timeout_ms() if should_wait and is_playmode else None,
            )
        except UnityConnectionError as exc:
            if not should_wait or not is_playmode:
                raise
            response = _unknown_completion_response("run_tests", exc)
        if _is_unknown_command_response(response, "run_tests"):
            response = CommandResponse(success=False, message=TEST_FRAMEWORK_MISSING_MESSAGE)
        result = UnityActionResult.from_response(
            tool="test",
            command="run_tests",
            params=payload,
            response=response,
        )
        if (
            not should_wait
            or not is_playmode
            or not response.success
            or (response.message != "running" and not response.completion_unknown)
        ):
            return result

        result_port = _response_port(response, target.port)
        final_response = wait_for_test_results(
            result_port,
            status_dir=self.status_dir,
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
            status_resolver=lambda: self._resolve_same_project(target),
        )
        return UnityActionResult.from_response(
            tool="test",
            command="run_tests",
            params=payload,
            response=final_response,
        )

    def editor_play(
        self,
        *,
        wait: bool = False,
        timeout_sec: int = DEFAULT_READY_TIMEOUT_SEC,
        poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    ) -> UnityActionResult:
        return self.manage_editor(
            "play",
            wait=wait,
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
        )

    def editor_stop(
        self,
        *,
        wait: bool = False,
        timeout_sec: int = DEFAULT_READY_TIMEOUT_SEC,
        stable_sec: float = 0.5,
        poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    ) -> UnityActionResult:
        return self.manage_editor(
            "stop",
            wait=wait,
            timeout_sec=timeout_sec,
            stable_sec=stable_sec,
            poll_interval_sec=poll_interval_sec,
        )

    def editor_pause(self) -> UnityActionResult:
        return self.manage_editor("pause")

    def manage_editor(self, action: str, **params: Any) -> UnityActionResult:
        action = action.lower()
        wait = params.pop("wait", None)
        timeout_sec = int(params.pop("timeout_sec", DEFAULT_READY_TIMEOUT_SEC))
        stable_sec = float(params.pop("stable_sec", 0.5 if action == "stop" else 0))
        poll_interval_sec = float(params.pop("poll_interval_sec", DEFAULT_POLL_INTERVAL_SEC))
        payload = {"action": action, **params}
        if wait is not None:
            payload["wait_for_completion"] = False if wait and action in {"play", "stop"} else bool(wait)

        if wait and action in {"play", "stop"}:
            target = self.client.discover_instance()
            response = self._send_disruptive_command("manage_editor", payload, target)
            result = UnityActionResult.from_response(
                tool="editor",
                command="manage_editor",
                params=payload,
                response=response,
            )
            if not response.success:
                return result
            target_state = "playing" if action == "play" else "ready"
            reached = wait_for_state(
                lambda: self._resolve_same_project(target),
                target_state,
                timeout_sec=timeout_sec,
                poll_interval_sec=poll_interval_sec,
                after_timestamp=target.timestamp,
                stable_sec=stable_sec,
                timeout_label=f"editor {action}",
            )
            return _with_data(
                result,
                {
                    "completion": "confirmed",
                    "state": reached.to_dict(),
                    "initial_port": target.port,
                    "current_port": reached.port,
                },
            )
        return self._call("editor", "manage_editor", payload)

    def execute_menu_item(self, menu_path: str) -> UnityActionResult:
        return self._call("menu", "menu", {"menu_path": menu_path})

    def save_project(self) -> UnityActionResult:
        return self.execute_menu_item("File/Save Project")

    def reserialize_assets(
        self,
        paths: str | Iterable[str] | None = None,
        *,
        wait: bool = False,
        timeout_sec: int = DEFAULT_READY_TIMEOUT_SEC,
        stable_sec: float = 0.5,
        poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    ) -> UnityActionResult:
        if paths is None:
            payload: dict[str, Any] = {}
        elif isinstance(paths, str):
            payload = {"path": paths}
        else:
            payload = {"paths": list(paths)}
        if not wait:
            return self._call("reserialize", "reserialize", payload)

        target = self.client.discover_instance()
        response = self._send_disruptive_command("reserialize", payload, target)
        result = UnityActionResult.from_response(
            tool="reserialize",
            command="reserialize",
            params=payload,
            response=response,
        )
        if not response.success:
            return result
        ready = wait_for_ready(
            lambda: self._resolve_same_project(target),
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
            after_timestamp=target.timestamp,
            stable_sec=stable_sec,
        )
        return _with_data(
            result,
            {
                "completion": "confirmed",
                "ready": ready.to_dict(),
                "initial_port": target.port,
                "current_port": ready.port,
            },
        )

    def profiler(self, *, action: str = "status", **params: Any) -> UnityActionResult:
        return self._call("profiler", "profiler", {"action": action, **params})

    def screenshot(
        self,
        *,
        view: str = "scene",
        output_path: str | Path | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> UnityActionResult:
        return self._call(
            "screenshot",
            "screenshot",
            {
                "view": view,
                "output_path": str(output_path) if output_path is not None else None,
                "width": width,
                "height": height,
            },
        )

    def exec_csharp(
        self,
        code: str,
        *,
        usings: str | Iterable[str] | None = None,
        csc: str | Path | None = None,
        dotnet: str | Path | None = None,
    ) -> UnityActionResult:
        return self._call(
            "exec",
            "exec",
            {
                "code": code,
                "usings": _list_or_csv(usings),
                "csc": str(csc) if csc is not None else None,
                "dotnet": str(dotnet) if dotnet is not None else None,
            },
        )

    def _call(self, tool: str, command: str, params: dict[str, Any]) -> UnityActionResult:
        payload = _compact(params)
        response = self.client.call(command, payload)
        return UnityActionResult.from_response(
            tool=tool,
            command=command,
            params=payload,
            response=response,
        )

    def _send_disruptive_command(
        self,
        command: str,
        payload: dict[str, Any],
        target: Instance,
    ) -> CommandResponse:
        try:
            return self.client.call(
                command,
                payload,
                instance=target,
                timeout_ms=self._disruptive_send_timeout_ms(),
            )
        except UnityConnectionError as exc:
            return _unknown_completion_response(command, exc)

    def _resolve_same_project(self, baseline: Instance) -> Instance:
        return discover_instance(
            project=baseline.project_path,
            instances_dir=self.client.instances_dir,
            cwd=self.client.cwd,
            process_checker=self.client.process_checker,
        )

    def _disruptive_send_timeout_ms(self) -> int:
        return max(1_000, min(self.client.timeout_ms, DISRUPTIVE_SEND_TIMEOUT_MS))


def _compact(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value is not None}


def _with_data(result: UnityActionResult, extra: dict[str, Any]) -> UnityActionResult:
    data: dict[str, Any]
    if isinstance(result.data, dict):
        data = dict(result.data)
    elif result.data is None:
        data = {}
    else:
        data = {"result": result.data}
    data.update(extra)
    return UnityActionResult(
        tool=result.tool,
        command=result.command,
        params=result.params,
        success=result.success,
        message=result.message,
        data=data,
    )


def _unknown_completion_response(command: str, exc: UnityConnectionError) -> CommandResponse:
    return CommandResponse(
        success=True,
        message=f"{command} sent (completion unknown: {exc})",
        data={
            "accepted": True,
            "completion": "unknown",
            "connection_error": str(exc),
            "command": command,
        },
    )


def _response_port(response: CommandResponse, default: int) -> int:
    if isinstance(response.data, dict):
        try:
            return int(response.data.get("port") or default)
        except (TypeError, ValueError):
            return default
    return default


def _is_unknown_command_response(response: CommandResponse, command: str) -> bool:
    return not response.success and "Unknown command" in response.message and command in response.message


def default_status_dir() -> Path:
    return Path.home() / ".unity-bridge" / "status"


def test_results_path(port: int, *, status_dir: str | Path | None = None) -> Path:
    directory = Path(status_dir) if status_dir is not None else default_status_dir()
    return directory / f"test-results-{port}.json"


def wait_for_test_results(
    port: int,
    *,
    status_dir: str | Path | None = None,
    timeout_sec: int = DEFAULT_TEST_TIMEOUT_SEC,
    poll_interval_sec: float = DEFAULT_TEST_POLL_INTERVAL_SEC,
    status_resolver: Any | None = None,
) -> CommandResponse:
    path = test_results_path(port, status_dir=status_dir)
    deadline = time.monotonic() + timeout_sec
    last_read_error: Exception | None = None
    while time.monotonic() < deadline:
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                last_read_error = exc
            else:
                if not isinstance(raw, dict):
                    raise DiscoveryError(f"invalid PlayMode test results file: {path}")
                try:
                    path.unlink()
                except OSError:
                    pass
                return CommandResponse.from_dict(raw)

        if status_resolver is not None:
            try:
                instance = status_resolver()
            except DiscoveryError:
                instance = None
            if isinstance(instance, Instance) and instance.state == "stopped":
                raise DiscoveryError(f"unity editor has stopped while waiting for PlayMode test results (port {port})")

        time.sleep(poll_interval_sec)
    detail = f": last read error: {last_read_error}" if last_read_error is not None else ""
    raise DiscoveryError(f"timed out waiting for PlayMode test results ({timeout_sec}s){detail}")


def _join_csv(value: str | Iterable[str] | None, *, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return ",".join(str(item) for item in value)


def _list_or_csv(value: str | Iterable[str] | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item) for item in value]


def _path_list(value: str | Path | Iterable[str | Path] | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, (str, Path)):
        return [str(value)]
    return [str(item) for item in value]
