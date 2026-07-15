"""Packet contracts (FR-6)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum

from .common import Citation


class PacketType(str, Enum):
    LOW_RISK = "low_risk"
    MEDIUM_RISK = "medium_risk"


@dataclass(slots=True)
class PacketSection:
    key: str
    title: str
    body: str
    editable: bool = True
    citations: list[Citation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "body": self.body,
            "editable": self.editable,
            "citations": [c.to_dict() for c in self.citations],
        }


@dataclass(slots=True)
class Packet:
    packet_id: str
    case_id: str
    packet_version: int
    packet_type: PacketType
    sections: list[PacketSection] = field(default_factory=list)
    recommendation_clause_ids: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    sha256: str | None = None

    def to_dict(self) -> dict:
        data = {
            "packet_id": self.packet_id,
            "case_id": self.case_id,
            "packet_version": self.packet_version,
            "packet_type": self.packet_type.value,
            "sections": [s.to_dict() for s in self.sections],
            "recommendation_clause_ids": list(self.recommendation_clause_ids),
            "unsupported_claims": list(self.unsupported_claims),
            "citations": [c.to_dict() for c in self.citations],
        }
        if self.sha256 is not None:
            data["sha256"] = self.sha256
        return data

    def compute_sha256(self) -> str:
        """Deterministic content hash used for attach idempotency (FR-7)."""
        payload = dict(self.to_dict())
        payload.pop("sha256", None)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
