"""ReviewGraphState: durable state carried through the review workflow (sec 5).

Checkpointed for human pause/resume. In the Tuesday local slice this is an
in-process dataclass; Wednesday binds it to a LangGraph checkpointer backed by
AgentCore Memory (seven-day TTL).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .case import CaseIntake
from .common import Citation, Conflict
from .packet import Packet
from .policy import PolicyResult
from .servicenow import HumanDecision, WritePreview, WriteResult
from .software import SoftwareMatch


class WorkflowStatus(str, Enum):
    INTAKE = "intake"
    LOOKUP = "lookup"
    AWAITING_MATCH_CONFIRMATION = "awaiting_match_confirmation"
    POLICY = "policy"
    ANALYSIS = "analysis"
    PACKET = "packet"
    AWAITING_REVIEW = "awaiting_review"
    WRITEBACK = "writeback"
    CLOSED = "closed"
    ESCALATED = "escalated"


@dataclass(slots=True)
class ReviewGraphState:
    case_id: str
    case_input: CaseIntake
    status: WorkflowStatus = WorkflowStatus.INTAKE
    workflow_version: str = "0.1.0"
    document_ids: list[str] = field(default_factory=list)
    software_candidates: list[SoftwareMatch] = field(default_factory=list)
    confirmed_match_id: str | None = None
    policy_result: PolicyResult | None = None
    specialist_results: dict[str, dict | None] = field(
        default_factory=lambda: {"security": None, "accessibility": None}
    )
    evidence_gaps: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    draft_packet: Packet | None = None
    human_edits: list[dict] = field(default_factory=list)
    human_decision: HumanDecision | None = None
    connector_target: dict | None = None
    write_preview: WritePreview | None = None
    write_result: WriteResult | None = None
    idempotency_key: str | None = None
    repair_passes_used: int = 0
    # Immutable identifier for this analysis run, set once by the workflow
    # runner (issue #50) and carried through checkpoints/audit correlation so
    # a restart resumes the same run rather than minting a new identity.
    run_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "run_id": self.run_id,
            "status": self.status.value,
            "workflow_version": self.workflow_version,
            "case_input": self.case_input.to_dict(),
            "document_ids": list(self.document_ids),
            "software_candidates": [m.to_dict() for m in self.software_candidates],
            "confirmed_match_id": self.confirmed_match_id,
            "policy_result": self.policy_result.to_dict() if self.policy_result else None,
            "specialist_results": self.specialist_results,
            "evidence_gaps": list(self.evidence_gaps),
            "citations": [c.to_dict() for c in self.citations],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "draft_packet": self.draft_packet.to_dict() if self.draft_packet else None,
            "human_edits": list(self.human_edits),
            "human_decision": self.human_decision.to_dict() if self.human_decision else None,
            "connector_target": self.connector_target,
            "write_preview": self.write_preview.to_dict() if self.write_preview else None,
            "write_result": self.write_result.to_dict() if self.write_result else None,
            "idempotency_key": self.idempotency_key,
            "repair_passes_used": self.repair_passes_used,
        }
