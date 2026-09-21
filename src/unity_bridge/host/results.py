"""Completion states shared by local transports; importing this starts no service."""


def not_started(reason: str, message: str) -> dict:
    return {"success": False, "message": message, "data": {"completion": "not_started", "reason": reason}}


def unknown(command: str) -> dict:
    return {"success": True, "message": f"{command} sent; completion could not be confirmed",
            "data": {"accepted": True, "completion": "unknown", "command": command}}
