"""Case intake contract (FR-1)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class DataClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    LEVEL1 = "level1"
    LEVEL2 = "level2"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Requester:
    name: str
    email: str
    department: str | None = None


@dataclass(frozen=True, slots=True)
class CaseIntake:
    """Requester-provided intake. Uploaded/retrieved content is untrusted and
    validated separately from this structured record."""

    product_name: str
    vendor_name: str
    requester: Requester
    use_case: str
    expected_users: int
    platform: list[str]
    data_classification: DataClassification
    estimated_cost_usd: float
    integrations: list[str] = field(default_factory=list)
    uses_sso: bool = False
    uses_ai: bool = False
    accessibility_context: str | None = None
    official_domain: str | None = None
    classroom_or_public_use: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["data_classification"] = self.data_classification.value
        return data
