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
    # Compare Unity's SemVer spelling (0.2.2-rc.1) with Python's normalized
    # package metadata (0.2.2rc1). A final release sorts after all its RCs.
    match = re.fullmatch(
        r"v?(\d+(?:\.\d+){0,3})"
        r"(?:[-_.]?(alpha|a|beta|b|preview|pre|rc)[-_.]?(\d*))?"
        r"(?:\+[0-9a-z]+(?:[.-][0-9a-z]+)*)?",
        value.strip(),
        re.IGNORECASE,
    )
    if not match:
        return None
    numbers = [int(part) for part in match.group(1).split(".")]
    while len(numbers) < 4:
        numbers.append(0)
    stage = (match.group(2) or "final").lower()
    rank = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "preview": 2, "pre": 2, "rc": 2, "final": 3}[stage]
    return (*numbers, rank, int(match.group(3) or 0))
