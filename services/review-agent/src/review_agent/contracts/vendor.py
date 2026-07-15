"""Workspace-scoped contracts for vendor intake and review configuration.

These records are persistence-neutral.  Service code replaces whole records rather
than exposing mutable storage objects, which maps cleanly to conditional DynamoDB
writes later.  Invite token hashes are intentionally absent from every serializer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

DEFAULT_WORKSPACE_ID = "csub-demo"


class CaseLifecycle(str, Enum):
    DRAFT = "draft"
    INVITED = "invited"
    OPENED = "opened"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    ANALYZING = "analyzing"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    DECLINED = "declined"
    WRITEBACK_COMPLETE = "writeback_complete"


class InviteStatus(str, Enum):
    ISSUED = "issued"
    OPENED = "opened"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class SubmissionStatus(str, Enum):
    DRAFT = "draft"
    FINALIZED = "finalized"


class ProfileStatus(str, Enum):
    DRAFT = "draft"
    ACTIVATED = "activated"


@dataclass(frozen=True, slots=True)
class SoftwareCatalogEntry:
    record_id: str
    canonical_name: str
    vendor: str
    normalized_identity: str
    source_row: int
    source_hash: str
    raw_values: dict[str, str | None]
    supported_software: str | None = None
    campus_license: str | None = None
    aliases: tuple[str, ...] = ()
    short_name: str | None = None
    platform: tuple[str, ...] = ()
    audience: str | None = None
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "record_id": self.record_id,
            "canonical_name": self.canonical_name,
            "vendor": self.vendor,
            "normalized_identity": self.normalized_identity,
            "source_row": self.source_row,
            "source_hash": self.source_hash,
            "raw_values": dict(self.raw_values),
            "supported_software": self.supported_software,
            "campus_license": self.campus_license,
            "aliases": list(self.aliases),
            "short_name": self.short_name,
            "platform": list(self.platform),
            "audience": self.audience,
            "approval_inferred": False,
        }


@dataclass(frozen=True, slots=True)
class Vendor:
    vendor_id: str
    name: str
    official_domain: str | None = None
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VendorProduct:
    product_id: str
    vendor_id: str
    name: str
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VendorContact:
    contact_id: str
    vendor_id: str
    name: str
    email: str
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VendorCase:
    case_id: str
    product_id: str
    use_case: str
    scope: str
    lifecycle: CaseLifecycle = CaseLifecycle.DRAFT
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["lifecycle"] = self.lifecycle.value
        return data


@dataclass(frozen=True, slots=True)
class VendorInvite:
    invite_id: str
    case_id: str
    product_id: str
    contact_id: str
    token_hash: str
    issued_at: str
    expires_at: str
    status: InviteStatus = InviteStatus.ISSUED
    opened_at: str | None = None
    revoked_at: str | None = None
    submitted_at: str | None = None
    replaced_invite_id: str | None = None
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_reviewer_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "invite_id": self.invite_id,
            "case_id": self.case_id,
            "product_id": self.product_id,
            "contact_id": self.contact_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "status": self.status.value,
            "opened_at": self.opened_at,
            "revoked_at": self.revoked_at,
            "submitted_at": self.submitted_at,
            "replaced_invite_id": self.replaced_invite_id,
        }


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    artifact_id: str
    submission_id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    untrusted: bool = True
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceValidationFinding:
    """One failed content check on a vendor evidence artifact (issue #36).

    Only failures are persisted; a validated document simply covers its
    requirement. Findings keep the affected requirement unresolved so the
    reminder flow and the vendor checklist treat the document as not received.
    """

    finding_id: str
    submission_id: str
    artifact_id: str
    filename: str
    evidence_type: str
    check: str
    reason: str
    source_citation: dict[str, Any]
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceExpiryRecord:
    """When a validated, time-bound evidence document stops being current (issue #53).

    Created only from fields that passed content validation; documents without
    a validated date are never monitored. ``expires_on`` is an ISO date.
    """

    expiry_id: str
    case_id: str
    submission_id: str
    artifact_id: str
    filename: str
    evidence_type: str
    expires_on: str
    source_citation: dict[str, Any]
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RenewalRecord:
    """A scoped re-review opened because approved evidence expired (issue #53).

    Links the historical approval (never mutated) to the new immutable case
    that collects refreshed evidence.
    """

    renewal_id: str
    source_case_id: str
    renewal_case_id: str
    expired_evidence_types: tuple[str, ...]
    opened_at: str
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["expired_evidence_types"] = list(self.expired_evidence_types)
        return data


@dataclass(frozen=True, slots=True)
class CoverageItem:
    coverage_id: str
    submission_id: str
    requirement_id: str
    profile_version_id: str
    evidence_artifact_ids: tuple[str, ...]
    source_citation: dict[str, Any]
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_artifact_ids"] = list(self.evidence_artifact_ids)
        return data


@dataclass(frozen=True, slots=True)
class Submission:
    submission_id: str
    invite_id: str
    case_id: str
    product_id: str
    version: int = 1
    status: SubmissionStatus = SubmissionStatus.DRAFT
    trust_center_url: str | None = None
    answers: dict[str, str] = field(default_factory=dict)
    evidence_artifact_ids: tuple[str, ...] = ()
    coverage_ids: tuple[str, ...] = ()
    intake_analysis_complete: bool = False
    research_summary: str | None = None
    updated_at: str | None = None
    finalized_at: str | None = None
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_vendor_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["evidence_artifact_ids"] = list(self.evidence_artifact_ids)
        data["coverage_ids"] = list(self.coverage_ids)
        return data


VendorSubmission = Submission


@dataclass(frozen=True, slots=True)
class ReviewCriterion:
    requirement_id: str
    question: str
    source_citation: dict[str, Any]
    expected_evidence: tuple[str, ...]
    output_fields: tuple[str, ...]
    remediation_guidance: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["expected_evidence"] = list(self.expected_evidence)
        data["output_fields"] = list(self.output_fields)
        return data


@dataclass(frozen=True, slots=True)
class ReviewProfileVersion:
    profile_version_id: str
    profile_key: str
    version: int
    criteria: tuple[ReviewCriterion, ...]
    created_at: str
    status: ProfileStatus = ProfileStatus.DRAFT
    fixture_tested_at: str | None = None
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "profile_version_id": self.profile_version_id,
            "profile_key": self.profile_key,
            "version": self.version,
            "criteria": [criterion.to_dict() for criterion in self.criteria],
            "created_at": self.created_at,
            "status": self.status.value,
            "fixture_tested_at": self.fixture_tested_at,
        }


@dataclass(frozen=True, slots=True)
class ApprovalScope:
    product_id: str
    use_case: str
    scope: str
    submission_version: int
    profile_version_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["profile_version_ids"] = list(self.profile_version_ids)
        return data


@dataclass(frozen=True, slots=True)
class ReviewRun:
    run_id: str
    case_id: str
    run_version: int
    approval_scope: ApprovalScope
    submission_id: str
    created_at: str
    unresolved_requirement_ids: tuple[str, ...]
    previous_run_id: str | None = None
    decision_valid: bool = False
    write_preview_valid: bool = False
    instructions: str | None = None
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "run_version": self.run_version,
            "approval_scope": self.approval_scope.to_dict(),
            "submission_id": self.submission_id,
            "created_at": self.created_at,
            "unresolved_requirement_ids": list(self.unresolved_requirement_ids),
            "previous_run_id": self.previous_run_id,
            "decision_valid": self.decision_valid,
            "write_preview_valid": self.write_preview_valid,
            "instructions": self.instructions,
        }


@dataclass(frozen=True, slots=True)
class IntegrationEvent:
    event_id: str
    event_type: str
    occurred_at: str
    resource_type: str
    resource_id: str
    case_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
