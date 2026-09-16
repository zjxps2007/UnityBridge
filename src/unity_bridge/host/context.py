"""Compilation metadata prepared once for each negotiated Unity context."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .registry import normalized_project


@dataclass(frozen=True)
class PreparedContext:
    domain_id: str
    reference_generation: int
    language_version: str
    project_id: str
    references: list[dict[str, Any]]
    compiler_reference_generation: str

    @classmethod
    def from_connector(cls, context: dict[str, Any]) -> PreparedContext:
        # Own the negotiated snapshot; later heartbeat updates must not modify it.
        references = [dict(reference) for reference in context["references"]]
        identity = sorted((str(ref["path"]), str(ref["mvid"])) for ref in references)
        generation = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        return cls(context["domainId"], context["referenceGeneration"], context["languageVersion"],
                   normalized_project(context["projectPath"]), references, generation)
