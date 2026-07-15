"""ServiceNow operation contracts (FR-7).

Field and table selection is deterministic configuration, never
model-generated. Every prototype write is simulated and labeled as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReviewAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_INFO = "request_info"


@dataclass(frozen=True, slots=True)
class HumanDecision:
    case_id: str
    decision_version: int
    reviewer_id: str
    action: ReviewAction
    decided_at: str
    approved_fields: dict = field(default_factory=dict)
    comments: str | None = None
    edits: tuple[dict, ...] = ()

    @property
    def idempotency_key(self) -> str:
        """FR-7 idempotency key: case_id + decision_version."""
        return f"{self.case_id}:{self.decision_version}"

    def to_dict(self) -> dict:
        data = {
            "case_id": self.case_id,
            "decision_version": self.decision_version,
            "reviewer_id": self.reviewer_id,
            "action": self.action.value,
            "approved_fields": dict(self.approved_fields),
            "edits": [dict(edit) for edit in self.edits],
            "decided_at": self.decided_at,
        }
        if self.comments is not None:
            data["comments"] = self.comments
        return data


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    from_value: object
    to_value: object

    def to_dict(self) -> dict:
        return {"field": self.field, "from": self.from_value, "to": self.to_value}


@dataclass(slots=True)
class WritePreview:
    case_id: str
    decision_version: int
    table: str
    record_id: str
    expected_record_version: int
    before: dict
    after: dict
    packet_version: int | None = None
    packet_sha256: str | None = None
    field_changes: list[FieldChange] = field(default_factory=list)
    simulated: bool = True

    def to_dict(self) -> dict:
        data = {
            "case_id": self.case_id,
            "decision_version": self.decision_version,
            "table": self.table,
            "record_id": self.record_id,
            "expected_record_version": self.expected_record_version,
            "before": self.before,
            "after": self.after,
            "field_changes": [fc.to_dict() for fc in self.field_changes],
            "simulated": True,
        }
        if self.packet_version is not None:
            data["packet_version"] = self.packet_version
        if self.packet_sha256 is not None:
            data["packet_sha256"] = self.packet_sha256
        return data


@dataclass(slots=True)
class Attachment:
    attachment_id: str
    sha256: str
    already_present: bool = False

    def to_dict(self) -> dict:
        return {
            "attachment_id": self.attachment_id,
            "sha256": self.sha256,
            "already_present": self.already_present,
        }


@dataclass(slots=True)
class WriteResult:
    idempotency_key: str
    record_id: str
    record_version: int
    committed: bool
    duplicate_suppressed: bool = False
    attachment: Attachment | None = None
    connector_response: dict = field(default_factory=dict)
    simulated: bool = True

    def to_dict(self) -> dict:
        return {
            "idempotency_key": self.idempotency_key,
            "record_id": self.record_id,
            "record_version": self.record_version,
            "committed": self.committed,
            "duplicate_suppressed": self.duplicate_suppressed,
            "attachment": self.attachment.to_dict() if self.attachment else None,
            "connector_response": dict(self.connector_response),
            "simulated": True,
        }
