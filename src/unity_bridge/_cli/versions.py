"""Version parsing shared by update checks and Connector warnings."""
from __future__ import annotations

import re

from ..client import DiscoveryError


def parse_pyproject_version(text: str) -> str:
    match = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise DiscoveryError("pyproject.toml does not contain a project version")
    return match.group(1)


def version_status(current: str, latest: str) -> str:
    current_key = version_key(current)
    latest_key = version_key(latest)
    if current_key is None or latest_key is None:
        return "unknown"
    if current_key < latest_key:
        return "outdated"
    if current_key > latest_key:
        return "newer"
    return "current"


def version_key(value: str) -> tuple[int, ...] | None:
    if value == "unknown":
        return None
    parts = re.findall(r"\d+", value)
    if not parts:
        return None
    numbers = [int(part) for part in parts[:4]]
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers)
