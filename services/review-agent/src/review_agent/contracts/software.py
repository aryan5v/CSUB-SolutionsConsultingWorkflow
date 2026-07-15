"""Approved-software contracts (FR-2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .common import SourceCoordinates


class MatchMethod(str, Enum):
    EXACT = "exact"
    ALIAS = "alias"
    VENDOR_PRODUCT = "vendor_product"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"

    @property
    def requires_confirmation(self) -> bool:
        """Fuzzy and semantic matches require reviewer confirmation; a model
        must not auto-confirm them (FR-2, AGENTS.md trust boundaries)."""
        return self in (MatchMethod.FUZZY, MatchMethod.SEMANTIC)


@dataclass(slots=True)
class ApprovedSoftwareRecord:
    """Normalized workbook row. ``source_row`` preserves the original row
    losslessly (original header -> original cell value)."""

    record_id: str
    canonical_name: str
    vendor: str
    source_row: dict[str, str | None]
    aliases: list[str] = field(default_factory=list)
    short_name: str | None = None
    platform: list[str] = field(default_factory=list)
    audience: str | None = None
    department: str | None = None
    assignment: str | None = None
    support: str | None = None
    location: str | None = None
    licensing: str | None = None
    supported_software: str | None = None
    campus_license: str | None = None
    source_hash: str | None = None
    source_row_number: int | None = None
    normalized_identity: str | None = None
    workspace_id: str = "csub-demo"
    source_coordinates: SourceCoordinates | None = None
    extraction_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "workspace_id": self.workspace_id,
            "record_id": self.record_id,
            "canonical_name": self.canonical_name,
            "vendor": self.vendor,
            "source_row": dict(self.source_row),
            "aliases": list(self.aliases),
            "short_name": self.short_name,
            "platform": list(self.platform),
            "audience": self.audience,
            "department": self.department,
            "assignment": self.assignment,
            "support": self.support,
            "location": self.location,
            "licensing": self.licensing,
            "supported_software": self.supported_software,
            "campus_license": self.campus_license,
            "source_hash": self.source_hash,
            "source_row_number": self.source_row_number,
            "normalized_identity": self.normalized_identity,
            "approval_inferred": False,
            "source_coordinates": (
                self.source_coordinates.to_dict() if self.source_coordinates else None
            ),
            "extraction_warnings": list(self.extraction_warnings),
        }


@dataclass(frozen=True, slots=True)
class SoftwareMatch:
    """A single lookup candidate with a disclosed match method."""

    record_id: str
    match_method: MatchMethod
    score: float
    source_row_ref: SourceCoordinates
    canonical_name: str | None = None

    @property
    def requires_confirmation(self) -> bool:
        return self.match_method.requires_confirmation

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "canonical_name": self.canonical_name,
            "match_method": self.match_method.value,
            "score": round(self.score, 4),
            "requires_confirmation": self.requires_confirmation,
            "source_row_ref": self.source_row_ref.to_dict(),
        }
