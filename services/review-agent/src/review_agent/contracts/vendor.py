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
    # Reviewer control (issue #37): pauses automated evidence reminders for
    # this case without touching the invitation or submission state.
    reminders_paused: bool = False
    vendor_visible_comment: str | None = None
    vendor_next_actions: tuple[str, ...] = ()
    # Deterministic policy output captured at registration (issue #63). The
    # vendor-facing checklist selects only the profiles these evidence keys map
    # to; an empty tuple means "unknown" and keeps the full-profile behavior.
    required_evidence: tuple[str, ...] = ()
    policy_route: str | None = None
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["lifecycle"] = self.lifecycle.value
        data["vendor_next_actions"] = list(self.vendor_next_actions)
        data["required_evidence"] = list(self.required_evidence)
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
    # Sealed (keyed-keystream) form of the invite token so automated reminders
    # can repeat the vendor's working intake link (issue #37). The raw token is
    # never persisted: unsealing requires the backend's link secret and is
    # verified against ``token_hash``. Absent from every serializer.
    token_seal: str | None = None
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
class ReminderClaim:
    """Durable idempotency claim for one reminder period of one case (issue #37).

    The claim is persisted keyed by its deterministic ``dedupe_key``
    (``reminder:{case_id}:{period}``) *before* an email is sent, so a
    concurrent or retried sweep that finds the key already claimed never
    duplicates a send. A DynamoDB adapter maps this to a conditional put.
    """

    dedupe_key: str
    case_id: str
    invite_id: str
    status: str  # pending | sent | failed
    attempts: int
    claimed_at: str
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ThreadAuthorRole(str, Enum):
    VENDOR = "vendor"
    REVIEWER = "reviewer"


class ThreadVisibility(str, Enum):
    # Vendor messages and reviewer replies the vendor may read.
    PUBLIC = "public"
    # Reviewer-only notes on the thread; never serialized to the vendor.
    INTERNAL = "internal"


# Vendor-authored message categories (issue #41): a clarifying question about a
# requested document, a report that the document cannot be obtained, an ETA, or
# a general concern. Reviewer replies use ``reply``.
VENDOR_MESSAGE_CATEGORIES: frozenset[str] = frozenset(
    {"question", "cannot_obtain", "eta", "concern"}
)
REVIEWER_REPLY_CATEGORY = "reply"
# Untrusted free text is bounded so a single message can never be used to flood
# storage or the reviewer inbox; the frontend escapes it on render.
MAX_THREAD_BODY_CHARS = 4000
# Per-case ceiling on vendor-authored messages, a coarse rate limit that keeps
# one scoped link from generating unbounded thread volume.
MAX_VENDOR_THREAD_MESSAGES = 50


@dataclass(frozen=True, slots=True)
class ThreadMessage:
    """One immutable case-scoped clarification-thread message (issue #41).

    Message ``body``, ``author_role``, ``author_id``, ``category``, and
    ``created_at`` are write-once history: services only ever replace the record
    to flip the mutable ``read_by_reviewer`` / ``resolved`` flags. The body is
    stored and surfaced as untrusted data — it never influences policy criteria,
    requirements, or agent instructions. Reviewer identity (``author_id``) and
    ``INTERNAL`` reviewer notes are absent from the vendor serializer, so a
    vendor sees only public replies and never which reviewer authored them.
    """

    message_id: str
    case_id: str
    author_role: ThreadAuthorRole
    category: str
    body: str
    created_at: str
    requirement_id: str | None = None
    submission_id: str | None = None
    submission_version: int | None = None
    author_id: str | None = None
    visibility: ThreadVisibility = ThreadVisibility.PUBLIC
    resolved: bool = False
    read_by_reviewer: bool = False
    in_reply_to: str | None = None
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_reviewer_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["author_role"] = self.author_role.value
        data["visibility"] = self.visibility.value
        return data

    def to_vendor_dict(self) -> dict[str, Any]:
        """Vendor-safe projection: no reviewer identity, no internal notes."""
        return {
            "message_id": self.message_id,
            "case_id": self.case_id,
            "author_role": self.author_role.value,
            "category": self.category,
            "body": self.body,
            "created_at": self.created_at,
            "requirement_id": self.requirement_id,
            "submission_version": self.submission_version,
            "resolved": self.resolved,
            "in_reply_to": self.in_reply_to,
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
    """One failed or manual-review check on a retained evidence artifact (issue #36).

    Findings keep the affected requirement unresolved so the reminder flow and
    vendor checklist do not treat a filename as evidence. ``manual_review``
    includes unavailable bytes, unreadable or unknown documents, identity
    mismatches, unreadable dates, and a TBD rule such as PCI currency. Every
    source citation identifies the artifact bytes and a one-based line; line 1
    is the deterministic document coordinate for document-level findings.
    """

    finding_id: str
    submission_id: str
    artifact_id: str
    filename: str
    evidence_type: str
    check: str
    reason: str
    source_citation: dict[str, Any]
    disposition: str = "failed"
    workspace_id: str = DEFAULT_WORKSPACE_ID

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


# Provisional evidence-policy defaults (issue #52 external decision track).
# These are NOT CSUB-confirmed authoritative policy: they are safe starting
# values a reviewer can adjust from app settings. A ``None`` threshold means
# "no confirmed rule" and forces manual review instead of an invented pass/fail
# (PLAN.md: an agent must never fill in unknown CSUB criteria). ``pentest`` is
# defaulted to the one-year freshness check confirmed in the 2026-07-15 feedback
# call (issue #36); PCI currency stays ``None`` until CSUB confirms it (a human
# may still set it here) so it is never an agent-invented threshold.
_DEFAULT_PENTEST_MAX_AGE_DAYS = 365
_DEFAULT_EVIDENCE_EXPIRY_DAYS = 365
_DEFAULT_COI_REQUIRED_COVERAGES = ("cyber",)


@dataclass(frozen=True, slots=True)
class PolicyCriteria:
    """Reviewer-editable, versioned evidence-validation thresholds (issue #52).

    Every edit creates a new immutable version with attribution so decisions
    remain reproducible against the criteria that were active when they ran.
    Values remain ``provisional`` until CSUB confirms them; the flag is surfaced
    in the UI and audit so a provisional threshold is never mistaken for
    authoritative policy.
    """

    criteria_version_id: str
    version: int
    updated_at: str
    updated_by: str
    pentest_max_age_days: int | None = _DEFAULT_PENTEST_MAX_AGE_DAYS
    pci_attestation_max_age_days: int | None = None
    coi_required_coverages: tuple[str, ...] = _DEFAULT_COI_REQUIRED_COVERAGES
    evidence_expiry_days: int | None = _DEFAULT_EVIDENCE_EXPIRY_DAYS
    provisional: bool = True
    workspace_id: str = DEFAULT_WORKSPACE_ID

    @classmethod
    def default(cls, *, workspace_id: str = DEFAULT_WORKSPACE_ID) -> "PolicyCriteria":
        """The provisional, non-authoritative baseline used before any edit."""
        return cls(
            criteria_version_id=f"policy-criteria-{workspace_id}-000",
            version=0,
            updated_at="",
            updated_by="system:default",
            workspace_id=workspace_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "criteria_version_id": self.criteria_version_id,
            "version": self.version,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
            "pentest_max_age_days": self.pentest_max_age_days,
            "pci_attestation_max_age_days": self.pci_attestation_max_age_days,
            "coi_required_coverages": list(self.coi_required_coverages),
            "evidence_expiry_days": self.evidence_expiry_days,
            "provisional": self.provisional,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PolicyCriteria":
        return cls(
            criteria_version_id=str(value["criteria_version_id"]),
            version=int(value["version"]),
            updated_at=str(value.get("updated_at", "")),
            updated_by=str(value.get("updated_by", "")),
            pentest_max_age_days=_optional_positive_int(value.get("pentest_max_age_days")),
            pci_attestation_max_age_days=_optional_positive_int(
                value.get("pci_attestation_max_age_days")
            ),
            coi_required_coverages=tuple(
                str(item) for item in (value.get("coi_required_coverages") or ())
            ),
            evidence_expiry_days=_optional_positive_int(value.get("evidence_expiry_days")),
            provisional=bool(value.get("provisional", True)),
            workspace_id=str(value.get("workspace_id", DEFAULT_WORKSPACE_ID)),
        )


def _optional_positive_int(value: Any) -> int | None:
    """Coerce a stored/submitted threshold to a positive int, or None for TBD."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("threshold must be a positive integer or null")
    if value < 1:
        raise ValueError("threshold must be a positive integer or null")
    return value


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
