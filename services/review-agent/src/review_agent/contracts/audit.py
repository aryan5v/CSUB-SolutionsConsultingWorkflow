"""Structured audit event contract (sec 7).

Audit events carry identifiers, versions, hashes, latency, and error metadata.
They never carry document bodies, credentials, or sensitive prompts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class ActorType(str, Enum):
    REQUESTER = "requester"
    REVIEWER = "reviewer"
    SYSTEM = "system"
    MODEL = "model"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    event_type: str
    case_id: str
    occurred_at: str
    actor_type: ActorType
    actor_id: str | None = None
    correlation_id: str | None = None
    workflow_version: str | None = None
    policy_version: str | None = None
    decision_version: int | None = None
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["actor_type"] = self.actor_type.value
        return {k: v for k, v in data.items() if v is not None}
