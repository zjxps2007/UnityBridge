"""Public Python API, loaded on demand for short-lived CLI invocations."""

__version__ = "0.3.1-rc.1"

__all__ = [
    "CommandResponse",
    "DiscoveryError",
    "Instance",
    "UnityActionResult",
    "UnityBridgeAdapter",
    "UnityClient",
    "UnityBridgeError",
    "UnityConnectionError",
    "UnityHttpError",
    "discover_instance",
    "find_active_by_port",
    "find_by_port",
    "scan_instances",
    "send_command",
    "wait_for_state",
    "__version__",
]


def __getattr__(name):
    if name not in __all__ or name == "__version__":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name in {"UnityActionResult", "UnityBridgeAdapter"}:
        from . import adapter
        value = getattr(adapter, name)
    else:
        from . import client
        value = getattr(client, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
