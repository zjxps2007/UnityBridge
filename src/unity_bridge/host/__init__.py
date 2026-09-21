"""Optional external-host routing. Importing this module never starts a process."""
from __future__ import annotations

import time
from typing import Any
import uuid

from .registry import (PROTOCOL, endpoint_path, host_home, load_launcher,
                       normalized_project, process_alive, read_json)


def _endpoint(instance=None, instances_dir=None):
    root = host_home()
    descriptor = load_launcher(root)
    if descriptor is None:
        return None, None, False
    endpoint = read_json(endpoint_path(root, descriptor["runtimeId"]))
    if (not endpoint or endpoint.get("protocol") != PROTOCOL
            or endpoint.get("runtimeId") != descriptor["runtimeId"]
            or endpoint.get("token") != descriptor["token"]
            or not isinstance(endpoint.get("port"), int) or not 0 < endpoint["port"] < 65536
            or not process_alive(endpoint.get("pid"))):
        return descriptor, None, False
    if instances_dir is not None and normalized_project(endpoint.get("instancesDir", "")) != normalized_project(instances_dir):
        return descriptor, endpoint, False
    projects = endpoint.get("projects", [])
    if not isinstance(projects, list):
        projects = []
    registered = instance is None or any(
        isinstance(project, dict) and project.get("protocol") == PROTOCOL
        and project.get("pid") == instance.pid
        and normalized_project(project.get("projectPath", "")) == normalized_project(instance.project_path)
        for project in projects
    )
    return descriptor, endpoint, registered


def host_status(instance=None, instances_dir=None) -> dict[str, Any]:
    """Inspect only the private registry and process liveness; never call Unity."""
    descriptor, endpoint, registered = _endpoint(instance, instances_dir)
    if endpoint is None:
        return {"state": "unavailable", "registered": descriptor is not None, "project_registered": False}
    value = {"state": "running", "version": endpoint.get("version", ""), "pid": endpoint["pid"],
             "port": endpoint["port"], "project_registered": registered, "protocol": PROTOCOL}
    if registered and instance is not None:
        project = next((p for p in endpoint.get("projects", []) if isinstance(p, dict)
                        and p.get("pid") == instance.pid and normalized_project(p.get("projectPath", ""))
                        == normalized_project(instance.project_path)), {})
        value["prewarm_state"] = project.get("prewarmState", "unknown")
        if project.get("prewarmError"):
            value["prewarm_error"] = project["prewarmError"]
    return value


def try_host_command(instance, command: str, params: Any, timeout_ms: int,
                     instances_dir=None, *, connection_pool=None, parent_request_id=None):
    """Return None only when no host request has been submitted.

    Once a POST is attempted, an ambiguous result is represented as unknown
    completion. The caller must never retry that command through the direct route.
    """
    from ..client import CommandResponse
    if command == "exec" and isinstance(params, dict) and (params.get("csc") or params.get("dotnet")):
        return None
    descriptor, endpoint, registered = _endpoint(instance, instances_dir)
    if endpoint is None or not registered:
        return None
    from .transport import TransportError, post
    deadline = int(time.time() * 1000) + max(1, int(timeout_ms))
    payload = {"command": command, "params": params if params is not None else {},
               "target": {"projectPath": instance.project_path, "pid": instance.pid, "port": instance.port},
               "request_id": uuid.uuid4().hex, "deadline_unix_ms": deadline}
    if parent_request_id is not None:
        payload['parent_request_id'] = parent_request_id
    try:
        response = post(endpoint["port"], descriptor["token"], "/command", payload, max(.001, timeout_ms / 1000),
                        pool=connection_pool,
                        key=(normalized_project(instance.project_path), "control" if command == "get_editor_state" else "execute"),
                        identity=(endpoint["pid"], descriptor["runtimeId"], instance.pid,
                                  instance.port, instance.domain_id, instance.reference_generation))
        if not isinstance(response.get("success"), bool) or not isinstance(response.get("message"), str):
            raise TransportError("Host returned an invalid command result")
        return CommandResponse.from_dict(response)
    except TransportError:
        return CommandResponse(success=True, message=f"{command} sent to host; completion could not be confirmed",
                               data={"accepted": True, "completion": "unknown", "command": command})


def main(argv: list[str] | None = None) -> int:
    # Keep argparse/compiler/server imports off the normal CLI/status startup path.
    from .cli import main as host_main
    return host_main(argv)


__all__ = ["host_status", "try_host_command", "main"]
