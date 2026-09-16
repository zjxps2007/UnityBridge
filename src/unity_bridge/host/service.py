"""Persistent local control service with FIFO Unity execution and isolated compilation."""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from typing import Any
import uuid

from .compiler import CompilerError, CompilerWorker
from .context import PreparedContext
from .registry import (PROTOCOL, atomic_json, endpoint_path, load_launcher, normalized_project,
                       process_alive, read_json)
from .transport import MAX_MESSAGE_BYTES, TransportError, post

BUSY_STATES = {"compiling", "refreshing", "reloading", "entering_playmode", "exiting_playmode"}


def not_started(reason: str, message: str) -> dict[str, Any]:
    return {"success": False, "message": message, "data": {"completion": "not_started", "reason": reason}}


def unknown(command: str) -> dict[str, Any]:
    return {"success": True, "message": f"{command} sent; completion could not be confirmed",
            "data": {"accepted": True, "completion": "unknown", "command": command}}


@dataclass
class Job:
    payload: dict[str, Any]
    deadline: float
    signature: str
    state: str = "queued"
    response: dict[str, Any] | None = None
    done: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def complete(self, response: dict[str, Any]) -> None:
        with self.lock:
            if self.response is None:
                self.response = response
                self.state = "completed"
                self.done.set()

    def expire(self) -> dict[str, Any]:
        with self.lock:
            if self.response is None:
                self.response = (unknown(str(self.payload["command"])) if self.state == "dispatched"
                                 else not_started("expired", "Request expired before Unity execution"))
                self.state = "completed"
                self.done.set()
            return self.response


class Project:
    def __init__(self, snapshot: dict[str, Any]):
        self.snapshot = snapshot
        self.context: PreparedContext | None = None
        self.context_key: tuple | None = None
        self.negotiating = False
        self.next_negotiate = 0.
        self.warmed_key: tuple | None = None
        self.prewarm_state = "pending"
        self.prewarm_error = ""
        self.alive = True
        self.condition = threading.Condition()
        self.pending: deque[Job] = deque()
        self.jobs: OrderedDict[str, Job] = OrderedDict()
        self.worker_started = False
        self.running = False

    @staticmethod
    def key(snapshot: dict[str, Any]) -> tuple:
        return (snapshot.get("pid"), snapshot.get("domainId"), snapshot.get("referenceGeneration"), snapshot.get("port"))


class HostService:
    def __init__(self, root: Path, descriptor: dict[str, Any], *, instances_dir: Path | None = None,
                 compiler: Any = None, idle_seconds: float = 30., scan_interval: float = .5):
        from ..client import default_instances_dir
        self.root, self.descriptor = root, descriptor
        self.instances_dir = instances_dir or (Path(descriptor["instancesDir"]) if descriptor.get("instancesDir")
                                              else default_instances_dir())
        self.compiler = compiler or CompilerWorker(descriptor["workerPath"])
        self.idle_seconds, self.scan_interval = idle_seconds, scan_interval
        self.projects: dict[tuple[str, int], Project] = {}
        self.projects_lock = threading.Lock()
        self.registry_lock = threading.Lock()
        self.stopping = threading.Event()
        self.server: ThreadingHTTPServer | None = None
        self.last_registry = None
        self.last_active = time.monotonic()
        self.compiler_error = ""

    @property
    def port(self) -> int:
        return int(self.server.server_address[1]) if self.server else 0

    def _project_list(self) -> list[Project]:
        with self.projects_lock:
            return list(self.projects.values())

    def _write_registry(self) -> None:
        if not self.server or self.stopping.is_set():
            return
        with self.registry_lock:
            targets = []
            for project in self._project_list():
                with project.condition:
                    if project.context is not None and project.alive:
                        snapshot = project.snapshot
                        targets.append({"projectPath": snapshot["projectPath"], "pid": snapshot["pid"],
                                        "port": snapshot["port"], "protocol": PROTOCOL,
                                        "prewarmState": project.prewarm_state,
                                        "prewarmError": project.prewarm_error})
            targets.sort(key=lambda p: (p["projectPath"], p["pid"]))
            value = {"protocol": PROTOCOL, "runtimeId": self.descriptor["runtimeId"],
                     "version": self.descriptor["version"], "pid": os.getpid(), "port": self.port,
                     "token": self.descriptor["token"], "instancesDir": str(self.instances_dir.resolve()),
                     "projects": targets}
            if value != self.last_registry:
                try:
                    atomic_json(endpoint_path(self.root, self.descriptor["runtimeId"]), value)
                except PermissionError:
                    # Keep the last published snapshot and retry on the next scan.
                    # A transient reader lock must not terminate discovery/prewarm.
                    return
                self.last_registry = value

    def _negotiate(self, project: Project) -> None:
        with project.condition:
            snapshot = dict(project.snapshot)
            key = Project.key(snapshot)
        request_id = uuid.uuid4().hex
        try:
            response = post(int(snapshot["port"]), self.descriptor["token"], "/command", {
                "command": "bridge_context", "params": {}, "request_id": request_id,
                "deadline_unix_ms": int(time.time() * 1000) + 2000,
            }, 2.)
            context = response.get("data")
            if (not response.get("success") or not isinstance(context, dict)
                    or context.get("protocol") != PROTOCOL or context.get("pid") != snapshot["pid"]
                    or normalized_project(context.get("projectPath", "")) != normalized_project(snapshot["projectPath"])
                    or context.get("domainId") != snapshot.get("domainId")
                    or context.get("referenceGeneration") != snapshot.get("referenceGeneration")
                    or not isinstance(context.get("references"), list)
                    or not isinstance(context.get("languageVersion"), str)):
                return
            prepared = PreparedContext.from_connector(context)
            warm_context = False
            with project.condition:
                if Project.key(project.snapshot) == key:
                    project.context = prepared
                    project.context_key = key
                    if project.warmed_key != key:
                        project.warmed_key = key
                        project.prewarm_state = "warming"
                        project.prewarm_error = ""
                        warm_context = True
                    project.condition.notify_all()
            if warm_context:
                threading.Thread(target=self._prewarm_context, args=(project, prepared, key),
                                 daemon=True, name="unity-host-reference-prewarm").start()
        except (TransportError, ValueError, TypeError, KeyError, OSError):
            pass
        finally:
            with project.condition:
                project.negotiating = False
                project.next_negotiate = time.monotonic() + 1.
            self._write_registry()

    def _prewarm_context(self, project: Project, context: PreparedContext, key: tuple) -> None:
        # Compile an innocuous wrapper only. Its assembly is never loaded into Unity.
        job = Job({"command": "exec", "params": {"code": "return null;"}},
                  time.monotonic() + 30., "prewarm")
        state, error = "ready", ""
        try:
            self._compile(context, job)
        except CompilerError as exc:
            state, error = "failed", str(exc)
        except Exception:
            state, error = "failed", "Compiler context preparation failed"
        with project.condition:
            if project.warmed_key == key:
                project.prewarm_state, project.prewarm_error = state, error
        self._write_registry()

    def scan_once(self) -> None:
        found: set[tuple[str, int]] = set()
        stopped: set[tuple[str, int]] = set()
        try:
            paths = list(self.instances_dir.glob("*.json"))
        except OSError:
            paths = []
        for path in paths:
            snapshot = read_json(path)
            if (snapshot and isinstance(snapshot.get("projectPath"), str)
                    and isinstance(snapshot.get("pid"), int)
                    and (snapshot.get("state") == "stopped" or snapshot.get("bridgeProtocol") != PROTOCOL)):
                stopped.add((normalized_project(snapshot["projectPath"]), snapshot["pid"]))
            if (not snapshot or snapshot.get("bridgeProtocol") != PROTOCOL
                    or not isinstance(snapshot.get("projectPath"), str)
                    or not isinstance(snapshot.get("domainId"), str)
                    or not isinstance(snapshot.get("referenceGeneration"), int)
                    or not isinstance(snapshot.get("port"), int)
                    or not 0 < snapshot["port"] < 65536
                    or snapshot.get("state") == "stopped" or not process_alive(snapshot.get("pid"))):
                continue
            key = (normalized_project(snapshot["projectPath"]), snapshot["pid"])
            found.add(key)
            with self.projects_lock:
                project = self.projects.get(key)
                if project is None:
                    project = Project(snapshot)
                    self.projects[key] = project
            start_negotiation = False
            with project.condition:
                project.snapshot, project.alive = snapshot, True
                project.condition.notify_all()
                if (project.context_key != Project.key(snapshot) and not project.negotiating
                        and time.monotonic() >= project.next_negotiate
                        and snapshot.get("state") not in BUSY_STATES):
                    project.negotiating = True
                    start_negotiation = True
            if start_negotiation:
                threading.Thread(target=self._negotiate, args=(project,), daemon=True,
                                 name="unity-host-negotiate").start()
        with self.projects_lock:
            projects = list(self.projects.items())
        for key, project in projects:
            if key not in found:
                with project.condition:
                    # Atomic file replacement can momentarily deny a read on Windows.
                    # Missing/corrupt snapshots alone cannot prove a live editor exited.
                    project.alive = key not in stopped and process_alive(key[1])
                    project.condition.notify_all()
        self._write_registry()

    def has_work(self) -> bool:
        for project in self._project_list():
            with project.condition:
                if project.running or any(not job.done.is_set() for job in project.jobs.values()):
                    return True
        return False

    def _scan_loop(self) -> None:
        while not self.stopping.is_set():
            try:
                active = load_launcher(self.root)
                if active and active["runtimeId"] != self.descriptor["runtimeId"] and not self.has_work():
                    self.request_stop()
                    return
                self.scan_once()
                if any(p.alive for p in self._project_list()) or self.has_work():
                    self.last_active = time.monotonic()
                elif time.monotonic() - self.last_active >= self.idle_seconds:
                    self.request_stop()
                    return
            except OSError:
                # Transient file replacement/permissions do not terminate the control service.
                pass
            self.stopping.wait(self.scan_interval)

    def _wait_context(self, project: Project, job: Job) -> PreparedContext | None:
        with project.condition:
            while not job.done.is_set() and not self.stopping.is_set():
                remaining = job.deadline - time.monotonic()
                if remaining <= 0:
                    return None
                if not project.alive:
                    job.complete(not_started("editor_unavailable", "The target Unity process is no longer available"))
                    return None
                if (project.snapshot.get("state") not in BUSY_STATES
                        and project.context is not None and project.context_key == Project.key(project.snapshot)):
                    return project.context
                project.condition.wait(min(.1, remaining))
        return None

    def _compile(self, context: PreparedContext, job: Job) -> dict[str, Any]:
        params = job.payload.get("params") or {}
        if not isinstance(params, dict):
            raise CompilerError("compile_error", "exec parameters must be an object")
        code = params.get("code")
        if code is None and isinstance(params.get("args"), list) and params["args"]:
            code = str(params["args"][0])
        if not isinstance(code, str) or not code:
            raise CompilerError("compile_error", "'code' required")
        usings = params.get("usings", [])
        if isinstance(usings, str):
            usings = usings.split(",")
        if not isinstance(usings, list) or any(not isinstance(item, str) for item in usings):
            raise CompilerError("compile_error", "Additional using directives must be strings")
        generation = context.compiler_reference_generation
        result = self.compiler.request({
            "operation": "compile", "code": code, "usings": usings,
            "language_version": context.language_version, "references": context.references,
            "project_id": context.project_id,
            "reference_generation": generation, "fresh_identity": True,
        }, deadline=job.deadline)
        if (result.get("reference_generation") != generation
                or not isinstance(result.get("assembly_base64"), str)):
            raise CompilerError("compiler_protocol", "Compiler returned a mismatched assembly result")
        return result

    def _invalidate_context(self, project: Project) -> None:
        with project.condition:
            project.context_key = None
            project.next_negotiate = 0.
            project.condition.notify_all()

    def _execute(self, project: Project, job: Job) -> None:
        command = str(job.payload["command"])
        for attempt in range(2):
            context = self._wait_context(project, job)
            if context is None:
                if not job.done.is_set():
                    job.expire()
                return
            forwarded_command, forwarded_params = command, job.payload.get("params", {})
            if command == "exec" and not (isinstance(forwarded_params, dict)
                                           and (forwarded_params.get("csc") or forwarded_params.get("dotnet"))):
                try:
                    compiled = self._compile(context, job)
                except CompilerError as exc:
                    if exc.code == "stale_reference" and attempt == 0:
                        self._invalidate_context(project)
                        continue
                    response = not_started(exc.code, str(exc))
                    if exc.diagnostics:
                        response["data"]["diagnostics"] = exc.diagnostics
                    job.complete(response)
                    return
                forwarded_command = "bridge_exec_assembly"
                forwarded_params = {"assembly": compiled["assembly_base64"]}
            with project.condition:
                snapshot = dict(project.snapshot)
                context_stale = (project.context_key != Project.key(snapshot)
                                 or context.domain_id != snapshot.get("domainId")
                                 or context.reference_generation != snapshot.get("referenceGeneration"))
            if context_stale:
                if attempt == 0:
                    continue
                job.complete(not_started("stale_domain", "Unity changed while preparing the request"))
                return
            remaining = job.deadline - time.monotonic()
            with job.lock:
                if job.done.is_set():
                    return
                if remaining <= 0:
                    # Do not call expire while holding the same non-reentrant lock.
                    expired = True
                else:
                    expired = False
                    job.state = "dispatched"
            if expired:
                job.expire()
                return
            forwarded = {
                "command": forwarded_command, "params": forwarded_params,
                "request_id": job.payload["request_id"],
                "deadline_unix_ms": min(job.payload["deadline_unix_ms"], int(time.time() * 1000 + remaining * 1000)),
                "domain_id": context.domain_id, "reference_generation": context.reference_generation,
            }
            try:
                response = post(snapshot["port"], self.descriptor["token"], "/command", forwarded, remaining)
            except TransportError:
                job.complete(unknown(command))
                return
            detail = response.get("data")
            if (attempt == 0 and not response.get("success") and isinstance(detail, dict)
                    and detail.get("completion") == "not_started"
                    and detail.get("reason") in {"stale_domain", "stale_references", "not_ready"}):
                with job.lock:
                    if job.done.is_set():
                        return
                    job.state = "queued"
                self._invalidate_context(project)
                continue
            job.complete(response)
            return
        job.complete(not_started("stale_domain", "Unity changed while preparing the request"))

    def _project_loop(self, project: Project) -> None:
        while not self.stopping.is_set():
            with project.condition:
                while not project.pending and not self.stopping.is_set():
                    if not project.alive:
                        project.worker_started = False
                        return
                    project.condition.wait(.5)
                if self.stopping.is_set():
                    return
                job = project.pending.popleft()
                project.running = True
            try:
                if not job.done.is_set():
                    self._execute(project, job)
            except Exception:
                with job.lock:
                    dispatched = job.state == "dispatched"
                job.complete(unknown(str(job.payload["command"])) if dispatched
                             else not_started("host_error", "Host could not prepare the Unity request"))
            finally:
                with project.condition:
                    project.running = False
                    while len(project.jobs) > 256:
                        first_id, first = next(iter(project.jobs.items()))
                        if not first.done.is_set():
                            break
                        project.jobs.pop(first_id)

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        command, target = payload.get("command"), payload.get("target")
        request_id, unix_deadline = payload.get("request_id"), payload.get("deadline_unix_ms")
        if (not isinstance(command, str) or not command or not isinstance(target, dict)
                or not isinstance(target.get("projectPath"), str)
                or not isinstance(target.get("pid"), int)
                or not isinstance(request_id, str) or not 0 < len(request_id) <= 128
                or not isinstance(unix_deadline, (int, float)) or isinstance(unix_deadline, bool)):
            return not_started("invalid_request", "Invalid host command envelope")
        remaining = (unix_deadline - time.time() * 1000) / 1000
        if not 0 < remaining <= 86400:
            return not_started("expired", "Request deadline has expired or is invalid")
        if command in {"bridge_context", "bridge_exec_assembly"}:
            return not_started("invalid_request", "Internal Connector operations cannot be invoked through this endpoint")
        key = (normalized_project(target["projectPath"]), target["pid"])
        with self.projects_lock:
            project = self.projects.get(key)
        if project is None:
            return not_started("unsupported_connector", "The host has not negotiated this Unity Connector")
        signature = hashlib.sha256(json.dumps({"command": command, "params": payload.get("params"), "target": key},
                                             sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        control = command == "get_editor_state"
        with project.condition:
            if project.context is None:
                return not_started("unsupported_connector", "The Unity Connector is not available")
            job = project.jobs.get(request_id)
            if job is not None:
                if job.signature != signature:
                    return not_started("request_id_conflict", "Request ID was already used for different work")
            else:
                # Bound finished request deduplication even for control-only clients.
                if len(project.jobs) >= 256:
                    for previous_id, previous in list(project.jobs.items()):
                        if len(project.jobs) < 256:
                            break
                        if previous.done.is_set():
                            project.jobs.pop(previous_id)
                if sum(not item.done.is_set() for item in project.jobs.values()) >= 256:
                    return not_started("queue_full", "The project's request queue is full")
                job = Job(dict(payload), time.monotonic() + remaining, signature)
                project.jobs[request_id] = job
                if control:
                    threading.Thread(target=self._run_control, args=(project, job), daemon=True,
                                     name="unity-host-control").start()
                else:
                    project.pending.append(job)
                    if not project.worker_started:
                        project.worker_started = True
                        threading.Thread(target=self._project_loop, args=(project,), daemon=True,
                                         name="unity-host-project").start()
                    project.condition.notify_all()
        if not job.done.wait(max(0., min(job.deadline - time.monotonic(), remaining))):
            return job.expire()
        return job.response

    def _run_control(self, project: Project, job: Job) -> None:
        # Live readiness observes compiling/reloading states as well as ready.
        with project.condition:
            snapshot = dict(project.snapshot)
        remaining = job.deadline - time.monotonic()
        if remaining <= 0:
            job.expire()
            return
        with job.lock:
            if job.done.is_set():
                return
            job.state = "dispatched"
        try:
            result = post(snapshot["port"], self.descriptor["token"], "/command", {
                "command": "get_editor_state", "params": job.payload.get("params", {}),
                "request_id": job.payload["request_id"], "deadline_unix_ms": job.payload["deadline_unix_ms"],
            }, remaining)
            job.complete(result)
        except TransportError:
            job.complete(unknown("get_editor_state"))

    def request_stop(self) -> None:
        self.stopping.set()
        for project in self._project_list():
            with project.condition:
                for job in project.pending:
                    job.complete(not_started("host_stopping", "Host stopped before Unity execution"))
                project.condition.notify_all()
        if self.server is not None:
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"
            # Headers and a small JSON body are written separately. Nagle can hold
            # the second write until a delayed ACK (~40 ms), adding a round trip
            # even on loopback. Disable it on accepted host sockets, not globally.
            disable_nagle_algorithm = True

            def log_message(self, format, *args):
                pass

            def do_POST(self):
                if self.headers.get("Origin") is not None:
                    self.reply(403, {"error": "Browser requests are not allowed"})
                    return
                if not hmac.compare_digest(self.headers.get("X-UnityBridge-Token", "").encode("utf-8"),
                                           service.descriptor["token"].encode("utf-8")):
                    self.reply(403, {"error": "Authentication required"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_MESSAGE_BYTES:
                        raise ValueError()
                    self.connection.settimeout(5.)
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError()
                except (ValueError, OSError):
                    self.reply(400, {"error": "Invalid JSON request"})
                    return
                if self.path == "/health":
                    self.reply(200, {"protocol": PROTOCOL, "version": service.descriptor["version"],
                                     "runtimeId": service.descriptor["runtimeId"],
                                     "pid": os.getpid(), "compiler": service.compiler.last_info,
                                     "compilerError": service.compiler_error,
                                     "projects": (service.last_registry or {}).get("projects", [])})
                elif self.path == "/stop":
                    if service.has_work():
                        self.reply(409, {"error": "Host has active work"})
                    else:
                        self.reply(200, {"stopped": True})
                        service.request_stop()
                elif self.path == "/command":
                    if service.stopping.is_set():
                        self.reply(200, not_started("host_stopping", "Host is stopping"))
                    else:
                        self.reply(200, service.submit(payload))
                else:
                    self.reply(404, {"error": "Unknown host operation"})

            def reply(self, status, value):
                raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass

        return Handler

    def serve(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server.daemon_threads = True
        self._write_registry()

        def prewarm():
            try:
                self.compiler.prewarm()
            except CompilerError as exc:
                self.compiler_error = str(exc)

        threading.Thread(target=prewarm, name="unity-host-prewarm", daemon=True).start()
        threading.Thread(target=self._scan_loop, name="unity-host-discovery", daemon=True).start()
        try:
            self.server.serve_forever(poll_interval=.1)
        finally:
            self.stopping.set()
            self.server.server_close()
            self.compiler.close()
            path = endpoint_path(self.root, self.descriptor["runtimeId"])
            saved = read_json(path)
            if saved and saved.get("pid") == os.getpid() and saved.get("port") == self.port:
                try:
                    path.unlink()
                except OSError:
                    pass
