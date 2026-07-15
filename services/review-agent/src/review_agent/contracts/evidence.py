"""Evidence and source-manifest contracts (FR-4, sec 5)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

from .common import SourceCoordinates


class EvidenceType(str, Enum):
    HECVAT = "hecvat"
    SOC2 = "soc2"
    PCI = "pci"
    PENTEST = "pentest"
    VPAT_ACR = "vpat_acr"
    COI = "coi"
    EMAIL = "email"
    TAAP = "taap"
    COMPLETED_REVIEW = "completed_review"
    OTHER = "other"


@dataclass(slots=True)
class EvidenceRecord:
    """Metadata for one piece of case or vendor evidence. Retrieval must not
    cross case, vendor, or product boundaries."""

    evidence_id: str
    case_id: str
    evidence_type: EvidenceType
    source_sha256: str
    vendor: str | None = None
    product: str | None = None
    authority: str | None = None
    issued_date: str | None = None
    expires_date: str | None = None
    version: str | None = None
    source_coordinates: SourceCoordinates | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SourceManifestEntry:
    """One entry in the ingestion SourceManifest (sec 5).

    Retains the original Box identity and hash so normalized data stays
    traceable. Source files themselves are never committed to Git.
    """

    source_id: str
    filename: str
    mime_type: str
    sha256: str
    version: str
    category: str
    ingested_at: str
    vendor: str | None = None
    product: str | None = None
    authority: str | None = None
    allowed_use: str | None = None
    retention: str | None = None
    extraction_state: str = "pending"
    warnings: list[str] = field(default_factory=list)
    source_locations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
