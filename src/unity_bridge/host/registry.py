"""User-scoped launcher discovery and atomic host process registration."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from typing import Any, Callable

PROTOCOL = 1
_ACCESS_RETRIES = 4 if os.name == "nt" else 0


def _access_retry(action: Callable[[], Any]) -> Any:
    """Windows readers can briefly prevent replace/open; successful I/O never waits."""
    for attempt in range(_ACCESS_RETRIES + 1):
        try:
            return action()
        except PermissionError:
            if attempt == _ACCESS_RETRIES:
                raise
            time.sleep(.01)


def host_home() -> Path:
    override = os.environ.get("UNITY_BRIDGE_HOST_HOME")
    return Path(override).expanduser().resolve() if override else Path.home() / ".unity-bridge" / "host"


def normalized_project(path: str | Path) -> str:
    # macOS commonly exposes the same temporary directory as /var/... and
    # /private/var/.... Compare physical paths consistently with registry writes.
    return os.path.normcase(os.path.realpath(path)).replace("\\", "/")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(_access_retry(lambda: path.read_text(encoding="utf-8")))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".host-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        _access_retry(lambda: os.replace(temporary, path))
    finally:
        try:
            _access_retry(lambda: os.unlink(temporary))
        except FileNotFoundError:
            pass


def valid_runtime_id(value: object) -> bool:
    return isinstance(value, str) and len(value) == 32 and all(c in "0123456789abcdef" for c in value)


def valid_launcher(value: dict[str, Any] | None) -> bool:
    if not value or value.get("protocol") != PROTOCOL or not valid_runtime_id(value.get("runtimeId")):
        return False
    token, argv, worker = value.get("token"), value.get("argv"), value.get("workerPath")
    return (isinstance(token, str) and len(token) == 64 and all(c in "0123456789abcdef" for c in token)
            and isinstance(argv, list) and bool(argv) and all(isinstance(a, str) and a for a in argv)
            and Path(argv[0]).is_absolute() and isinstance(worker, str) and Path(worker).is_absolute())


def load_launcher(root: Path | None = None, runtime_id: str | None = None) -> dict[str, Any] | None:
    root = root or host_home()
    if runtime_id is not None and not valid_runtime_id(runtime_id):
        return None
    path = root / "launchers" / f"{runtime_id}.json" if runtime_id else root / "launcher.json"
    value = read_json(path)
    return value if valid_launcher(value) else None


def register_launcher(executable: str, worker: str, *, python_module: bool = False,
                      version: str, root: Path | None = None,
                      instances_dir: str | None = None) -> dict[str, Any]:
    root = root or host_home()
    executable_path, worker_path = Path(executable).resolve(), Path(worker).resolve()
    if not executable_path.is_file() or not worker_path.is_file():
        raise ValueError("Host registration requires an existing executable and compiler worker")
    identity = json.dumps([str(executable_path), version, str(worker_path), python_module], separators=(",", ":"))
    runtime_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
    previous = load_launcher(root, runtime_id)
    prefix = [str(executable_path)] + (["-m", "unity_bridge"] if python_module else [])
    argv = prefix + ["_host", "serve", "--runtime-id", runtime_id]
    value: dict[str, Any] = {
        "protocol": PROTOCOL, "runtimeId": runtime_id, "version": version,
        "argv": argv, "workerPath": str(worker_path),
        "token": previous["token"] if previous else secrets.token_hex(32),
    }
    if instances_dir is not None:
        value["instancesDir"] = str(Path(instances_dir).resolve())
    atomic_json(root / "launchers" / f"{runtime_id}.json", value)
    atomic_json(root / "launcher.json", value)
    return value


def endpoint_path(root: Path, runtime_id: str) -> Path:
    if not valid_runtime_id(runtime_id):
        raise ValueError("Invalid host runtime identity")
    return root / "instances" / f"{runtime_id}.json"


def process_alive(pid: object) -> bool:
    from ..client import is_process_dead
    return isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 and not is_process_dead(pid)


def launch(root: Path | None = None) -> dict[str, Any]:
    root = root or host_home()
    descriptor = load_launcher(root)
    if descriptor is None:
        raise ValueError("No compatible UnityBridge host launcher is registered")
    endpoint = read_json(endpoint_path(root, descriptor["runtimeId"]))
    if (endpoint and endpoint.get("protocol") == PROTOCOL
            and endpoint.get("runtimeId") == descriptor["runtimeId"]
            and endpoint.get("version") == descriptor["version"]
            and endpoint.get("token") == descriptor["token"]
            and process_alive(endpoint.get("pid"))):
        # PIDs can be reused after a crash. Only launch/recovery does this bounded
        # authenticated probe; normal command routing and file status never do.
        from .transport import TransportError, post
        try:
            health = post(endpoint.get("port"), descriptor["token"], "/health", {}, 1.)
        except TransportError:
            health = None
        if (health and health.get("protocol") == PROTOCOL
                and health.get("runtimeId") == descriptor["runtimeId"]
                and health.get("version") == descriptor["version"]
                and health.get("pid") == endpoint["pid"]):
            return {"started": False, "pid": endpoint["pid"], "runtimeId": descriptor["runtimeId"]}
    env = dict(os.environ, UNITY_BRIDGE_HOST_HOME=str(root))
    child = subprocess.Popen(descriptor["argv"], env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                             start_new_session=os.name != "nt")
    return {"started": True, "pid": child.pid, "runtimeId": descriptor["runtimeId"]}


class ProcessLock:
    """An OS lock, rather than PID-only election, prevents duplicate host processes."""

    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0, os.SEEK_END)
                if not stream.tell():
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self.stream = stream
        return True

    def close(self) -> None:
        if self.stream is not None:
            self.stream.close()
            self.stream = None
