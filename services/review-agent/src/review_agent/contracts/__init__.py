"""Domain contracts for the review agent.

These dataclasses mirror the locked JSON Schemas in
``packages/contracts/schemas`` and are the in-process source of truth for the
Python workspace. Keep both in sync; contract changes require coordinating
every consumer (see docs/ENGINEERING.md).
"""

from __future__ import annotations

from .audit import ActorType, AuditEvent
from .case import CaseIntake, DataClassification, Requester
from .common import (
    Citation,
    CitationScope,
    Conflict,
    ConflictPosition,
    SourceCoordinates,
)
from .evidence import EvidenceRecord, EvidenceType, SourceManifestEntry
from .graph_state import ReviewGraphState, WorkflowStatus
from .packet import Packet, PacketSection, PacketType
from .policy import (
    PolicyInputs,
    PolicyResult,
    PolicyRule,
    PolicyRuleSet,
    PolicyTrigger,
    RiskRoute,
    SourcePrecedence,
)
from .schema import ContractValidationError, validate
from .servicenow import (
    Attachment,
    FieldChange,
    HumanDecision,
    ReviewAction,
    WritePreview,
    WriteResult,
)
from .software import ApprovedSoftwareRecord, MatchMethod, SoftwareMatch

__all__ = [
    "ActorType",
    "ApprovedSoftwareRecord",
    "Attachment",
    "AuditEvent",
    "CaseIntake",
    "Citation",
    "CitationScope",
    "Conflict",
    "ConflictPosition",
    "ContractValidationError",
    "DataClassification",
    "EvidenceRecord",
    "EvidenceType",
    "FieldChange",
    "HumanDecision",
    "MatchMethod",
    "Packet",
    "PacketSection",
    "PacketType",
    "PolicyInputs",
    "PolicyResult",
    "PolicyRule",
    "PolicyRuleSet",
    "PolicyTrigger",
    "Requester",
    "ReviewAction",
    "ReviewGraphState",
    "RiskRoute",
    "SourceCoordinates",
    "SourceManifestEntry",
    "SourcePrecedence",
    "SoftwareMatch",
    "WorkflowStatus",
    "WritePreview",
    "WriteResult",
    "validate",
]
