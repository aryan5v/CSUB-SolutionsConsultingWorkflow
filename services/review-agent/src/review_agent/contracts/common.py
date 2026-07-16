"""Shared contract primitives (source coordinates, citations, conflicts).

These dataclasses mirror the locked JSON Schemas in
``packages/contracts/schemas``. Keep field names in sync with those schemas;
they are the cross-language source of truth.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class CitationScope(str, Enum):
    """Retrieval scope a source came from. Policy and case/vendor scopes stay isolated."""

    POLICY = "policy"
    CASE_EVIDENCE = "case_evidence"
    OFFICIAL_VENDOR = "official_vendor"
    STANDARDS = "standards"


@dataclass(frozen=True, slots=True)
class SourceCoordinates:
    """Traceable pointer back to an institutional source location."""

    source_id: str
    filename: str | None = None
    sheet: str | None = None
    cell: str | None = None
    row: int | None = None
    column: str | None = None
    page: int | None = None
    line: int | None = None
    node_id: str | None = None
    version: str | None = None
    sha256: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True, slots=True)
class Citation:
    """A grounding link from a generated claim to an institutional source (FR-5)."""

    claim: str
    source: SourceCoordinates
    scope: CitationScope = CitationScope.POLICY
    verified: bool = False

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "source": self.source.to_dict(),
            "scope": self.scope.value,
            "verified": self.verified,
        }


@dataclass(frozen=True, slots=True)
class ConflictPosition:
    value: str
    source: SourceCoordinates
    precedence: int  # 1=partner override .. 5=model inference

    def to_dict(self) -> dict:
        return {"value": self.value, "source": self.source.to_dict(), "precedence": self.precedence}


@dataclass(slots=True)
class Conflict:
    """A registered disagreement between institutional sources (FR-3).

    ``resolution`` stays ``None`` until a human/partner resolves it; a model
    must never populate it.
    """

    conflict_id: str
    topic: str
    positions: list[ConflictPosition] = field(default_factory=list)
    resolution: str | None = None

    def to_dict(self) -> dict:
        return {
            "conflict_id": self.conflict_id,
            "topic": self.topic,
            "positions": [p.to_dict() for p in self.positions],
            "resolution": self.resolution,
        }
