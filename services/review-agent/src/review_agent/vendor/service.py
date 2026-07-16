"""Deterministic workspace-scoped vendor intake and immutable review runs."""

from __future__ import annotations

import base64
import binascii
import datetime
import hashlib
import hmac
import ipaddress
import re
import secrets
from dataclasses import replace
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import quote, urlsplit

from ..adapters.extraction import (
    EXTRACTION_COORDINATES_FIELD,
    DeterministicEvidenceExtractor,
    EvidenceExtractor,
)
from ..adapters.storage import StorageClient
from ..contracts.vendor import (
    DEFAULT_WORKSPACE_ID,
    ApprovalScope,
    CaseLifecycle,
    CoverageItem,
    EvidenceArtifact,
    EvidenceValidationFinding,
    IntegrationEvent,
    InviteStatus,
    PolicyCriteria,
    ReminderClaim,
    ReviewProfileVersion,
    ReviewRun,
    SoftwareCatalogEntry,
    Submission,
    SubmissionStatus,
    Vendor,
    VendorCase,
    VendorContact,
    VendorInvite,
    VendorProduct,
)
from ..evidence.ingestion import ACCEPTED_CONTENT_TYPES, MAX_EVIDENCE_BYTES
from ..evidence.validation import (
    RULE_SOURCE,
    classify_evidence_type,
    validate_evidence,
    validate_identity,
)
from ..profiles.service import ProfileError, ReviewProfileService
from ..timestamps import parse_utc_timestamp
from .delivery import DeliveryClaimStore, InMemoryDeliveryClaimStore
from .repository import VendorRepository

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..research import VendorResearchProvider

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")
_NORMALIZE = re.compile(r"[^a-z0-9]+")
_NORMALIZE_TOKENS = re.compile(r"[^a-z0-9]+")
_UNSET = object()


class VendorBackendError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class VendorBackend:
    MAX_RUN_VERSION = 3

    def __init__(
        self,
        repository: VendorRepository,
        profiles: ReviewProfileService,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        clock: Callable[[], datetime.datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
        invite_ttl: datetime.timedelta = datetime.timedelta(days=7),
        evidence_storage: StorageClient | None = None,
        extractor: EvidenceExtractor | None = None,
        reminder_interval: datetime.timedelta = datetime.timedelta(days=7),
        intake_base_url: str = "https://vetted.invalid/intake",
        link_secret: bytes | None = None,
        research_provider: VendorResearchProvider | None = None,
        delivery_claim_store: DeliveryClaimStore | None = None,
    ) -> None:
        if invite_ttl <= datetime.timedelta(0):
            raise ValueError("invite_ttl must be positive")
        if reminder_interval <= datetime.timedelta(0):
            raise ValueError("reminder_interval must be positive")
        self.repository = repository
        self.profiles = profiles
        self.workspace_id = workspace_id
        self._clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self.invite_ttl = invite_ttl
        # Evidence bytes are optional at registration, but analysis fails closed
        # when they are unavailable and excludes the artifact from auto-coverage.
        self._evidence_storage = evidence_storage
        self._extractor = extractor or DeterministicEvidenceExtractor()
        self.reminder_interval = reminder_interval
        self.intake_base_url = intake_base_url.rstrip("/#")
        # Keyed secret seals invite tokens so reminders can repeat the scoped
        # link without persisting plaintext. Production supplies a stable key.
        self._link_secret = link_secret or secrets.token_bytes(32)
        # Guarded official-domain research annotates provenance and gaps only.
        self._research = research_provider
        # Delivery claims are deliberately separate from the restored domain
        # snapshot. Production injects the DynamoDB-backed workspace store so
        # independent cold starts contend on one atomic outbox record.
        self._delivery_claims = delivery_claim_store or InMemoryDeliveryClaimStore()

    @property
    def research_provider(self) -> VendorResearchProvider | None:
        """The configured official-domain research provider, if any."""

        return self._research

    # Reviewer-owned vendor/product/contact records ---------------------------

    def create_vendor(self, name: str, official_domain: str | None = None) -> Vendor:
        domain = self._public_hostname(official_domain) if official_domain else None
        vendor = Vendor(
            vendor_id=self._id("vendor", "vendor"),
            name=self._text(name, "name"),
            official_domain=domain,
            workspace_id=self.workspace_id,
        )
        self._put("vendor", vendor.vendor_id, vendor)
        return vendor

    def update_vendor(
        self, vendor_id: str, *, name: str | None = None, official_domain: str | None = None
    ) -> Vendor:
        vendor = self._require("vendor", vendor_id, Vendor)
        updated = replace(
            vendor,
            name=self._text(name, "name") if name is not None else vendor.name,
            official_domain=(
                self._public_hostname(official_domain)
                if official_domain is not None
                else vendor.official_domain
            ),
        )
        self._put("vendor", vendor_id, updated)
        return updated

    def delete_vendor(self, vendor_id: str) -> None:
        self._require("vendor", vendor_id, Vendor)
        if any(product.vendor_id == vendor_id for product in self.list_products()):
            raise VendorBackendError("vendor_in_use", "vendor has products", status=409)
        self.repository.delete("vendor", vendor_id, workspace_id=self.workspace_id)

    def list_vendors(self) -> list[Vendor]:
        return self._list("vendor", Vendor)

    def get_vendor(self, vendor_id: str) -> Vendor:
        return self._require("vendor", vendor_id, Vendor)

    def create_product(self, vendor_id: str, name: str) -> VendorProduct:
        self._require("vendor", vendor_id, Vendor)
        product = VendorProduct(
            product_id=self._id("product", "product"),
            vendor_id=vendor_id,
            name=self._text(name, "name"),
            workspace_id=self.workspace_id,
        )
        self._put("product", product.product_id, product)
        return product

    def update_product(self, product_id: str, *, name: str) -> VendorProduct:
        product = self._require("product", product_id, VendorProduct)
        updated = replace(product, name=self._text(name, "name"))
        self._put("product", product_id, updated)
        return updated

    def delete_product(self, product_id: str) -> None:
        self._require("product", product_id, VendorProduct)
        if any(case.product_id == product_id for case in self._list("case", VendorCase)):
            raise VendorBackendError("product_in_use", "product has review cases", status=409)
        self.repository.delete("product", product_id, workspace_id=self.workspace_id)

    def list_products(self, vendor_id: str | None = None) -> list[VendorProduct]:
        products = self._list("product", VendorProduct)
        return [product for product in products if vendor_id is None or product.vendor_id == vendor_id]

    def get_product(self, product_id: str) -> VendorProduct:
        return self._require("product", product_id, VendorProduct)

    def create_contact(self, vendor_id: str, name: str, email: str) -> VendorContact:
        self._require("vendor", vendor_id, Vendor)
        clean_email = self._text(email, "email").lower()
        if not _EMAIL.fullmatch(clean_email):
            raise VendorBackendError("invalid_email", "email is invalid")
        contact = VendorContact(
            contact_id=self._id("contact", "contact"),
            vendor_id=vendor_id,
            name=self._text(name, "name"),
            email=clean_email,
            workspace_id=self.workspace_id,
        )
        self._put("contact", contact.contact_id, contact)
        return contact

    def update_contact(
        self, contact_id: str, *, name: str | None = None, email: str | None = None
    ) -> VendorContact:
        contact = self._require("contact", contact_id, VendorContact)
        clean_email = contact.email
        if email is not None:
            clean_email = self._text(email, "email").lower()
            if not _EMAIL.fullmatch(clean_email):
                raise VendorBackendError("invalid_email", "email is invalid")
        updated = replace(
            contact,
            name=self._text(name, "name") if name is not None else contact.name,
            email=clean_email,
        )
        self._put("contact", contact_id, updated)
        return updated

    def delete_contact(self, contact_id: str) -> None:
        self._require("contact", contact_id, VendorContact)
        if any(invite.contact_id == contact_id for invite in self.list_invites()):
            raise VendorBackendError("contact_in_use", "contact has invitations", status=409)
        self.repository.delete("contact", contact_id, workspace_id=self.workspace_id)

    def list_contacts(self, vendor_id: str | None = None) -> list[VendorContact]:
        contacts = self._list("contact", VendorContact)
        return [contact for contact in contacts if vendor_id is None or contact.vendor_id == vendor_id]

    def get_contact(self, contact_id: str) -> VendorContact:
        return self._require("contact", contact_id, VendorContact)

    # Case and invitation lifecycle ------------------------------------------

    def register_case(self, case_id: str, product_id: str, use_case: str, scope: str) -> VendorCase:
        product = self._require("product", product_id, VendorProduct)
        del product
        case = VendorCase(
            case_id=self._text(case_id, "case_id"),
            product_id=product_id,
            use_case=self._text(use_case, "use_case"),
            scope=self._text(scope, "scope"),
            workspace_id=self.workspace_id,
        )
        self._put("case", case.case_id, case)
        return case

    def _expire_invite_if_needed(self, invite: VendorInvite) -> VendorInvite:
        if invite.status in {
            InviteStatus.EXPIRED,
            InviteStatus.REVOKED,
            InviteStatus.SUBMITTED,
        }:
            return invite
        expires = datetime.datetime.fromisoformat(invite.expires_at)
        if self._now_datetime() < expires:
            return invite
        expired = replace(invite, status=InviteStatus.EXPIRED)
        self._put("invite", expired.invite_id, expired)
        return expired

    def issue_invite(self, case_id: str, contact_id: str) -> dict[str, Any]:
        case = self._require("case", case_id, VendorCase)
        contact = self._require("contact", contact_id, VendorContact)
        product = self._require("product", case.product_id, VendorProduct)
        if contact.vendor_id != product.vendor_id:
            raise VendorBackendError(
                "contact_product_mismatch", "contact and product must belong to the same vendor"
            )
        for existing in self.list_invites(case_id):
            if existing.contact_id == contact_id and existing.status in {
                InviteStatus.ISSUED,
                InviteStatus.OPENED,
                InviteStatus.IN_PROGRESS,
            }:
                raise VendorBackendError(
                    "active_invite_exists",
                    "an active invitation already exists; rotate or revoke it before issuing another",
                    status=409,
                )
        token = self._token_factory()
        if not isinstance(token, str) or len(token) < 32:
            raise VendorBackendError("weak_token", "token factory must provide at least 32 characters")
        now = self._now_datetime()
        invite_id = self._id("invite", "invite")
        invite = VendorInvite(
            invite_id=invite_id,
            case_id=case_id,
            product_id=case.product_id,
            contact_id=contact_id,
            token_hash=self._hash_token(token),
            issued_at=now.isoformat(),
            expires_at=(now + self.invite_ttl).isoformat(),
            token_seal=self._seal_token(invite_id, token),
            workspace_id=self.workspace_id,
        )
        self._put("invite", invite.invite_id, invite)
        submission = Submission(
            submission_id=self._id("submission", "submission"),
            invite_id=invite.invite_id,
            case_id=case.case_id,
            product_id=case.product_id,
            updated_at=now.isoformat(),
            workspace_id=self.workspace_id,
        )
        self._put("submission", submission.submission_id, submission)
        self._put("case", case.case_id, replace(case, lifecycle=CaseLifecycle.INVITED))
        self._event("invite.issued", "invite", invite.invite_id, case_id=case_id)
        return {"invite": invite.to_reviewer_dict(), "token": token}

    def resend_invite(self, invite_id: str) -> dict[str, Any]:
        old = self._expire_invite_if_needed(
            self._require("invite", invite_id, VendorInvite)
        )
        replacement = next(
            (
                invite
                for invite in self._list("invite", VendorInvite)
                if invite.replaced_invite_id == old.invite_id
            ),
            None,
        )
        if replacement is not None:
            raise VendorBackendError(
                "invite_already_rotated",
                "invitation was already rotated; use the latest invitation",
                status=409,
            )
        if old.status in {
            InviteStatus.ISSUED,
            InviteStatus.OPENED,
            InviteStatus.IN_PROGRESS,
        }:
            old = replace(old, status=InviteStatus.REVOKED, revoked_at=self._now())
            self._put("invite", old.invite_id, old)
        issued = self.issue_invite(old.case_id, old.contact_id)
        replacement = self._require(
            "invite", issued["invite"]["invite_id"], VendorInvite
        )
        replacement = replace(replacement, replaced_invite_id=old.invite_id)
        self._put("invite", replacement.invite_id, replacement)
        issued["invite"] = replacement.to_reviewer_dict()
        self._event("invite.rotated", "invite", replacement.invite_id, case_id=old.case_id)
        return issued

    def revoke_invite(self, invite_id: str) -> dict[str, Any]:
        invite = self._expire_invite_if_needed(
            self._require("invite", invite_id, VendorInvite)
        )
        if invite.status is InviteStatus.SUBMITTED:
            raise VendorBackendError(
                "already_submitted", "submitted invitation cannot be revoked", status=409
            )
        if invite.status in {InviteStatus.REVOKED, InviteStatus.EXPIRED}:
            return invite.to_reviewer_dict()
        revoked = replace(invite, status=InviteStatus.REVOKED, revoked_at=self._now())
        self._put("invite", invite_id, revoked)
        self._event("invite.revoked", "invite", invite_id, case_id=invite.case_id)
        return revoked.to_reviewer_dict()

    def list_invites(self, case_id: str | None = None) -> list[VendorInvite]:
        invites = []
        for invite in self._list("invite", VendorInvite):
            if case_id is not None and invite.case_id != case_id:
                continue
            expires = datetime.datetime.fromisoformat(invite.expires_at)
            if invite.status not in {
                InviteStatus.EXPIRED,
                InviteStatus.REVOKED,
                InviteStatus.SUBMITTED,
            } and self._now_datetime() >= expires:
                invite = replace(invite, status=InviteStatus.EXPIRED)
            invites.append(invite)
        return sorted(invites, key=lambda invite: (invite.issued_at, invite.invite_id))

    def resolve_invite(self, token: str, *, mark_open: bool = False) -> dict[str, Any]:
        invite = self._valid_invite(token)
        case = self._require("case", invite.case_id, VendorCase)
        if mark_open and invite.status is InviteStatus.ISSUED:
            now = self._now()
            invite = replace(invite, status=InviteStatus.OPENED, opened_at=now)
            self._put("invite", invite.invite_id, invite)
            self._put("case", case.case_id, replace(case, lifecycle=CaseLifecycle.OPENED))
            case = self._require("case", case.case_id, VendorCase)
            self._event("invite.opened", "invite", invite.invite_id, case_id=invite.case_id)
        submission = self._submission_for_invite(invite.invite_id)
        product = self._require("product", invite.product_id, VendorProduct)
        vendor = self._require("vendor", product.vendor_id, Vendor)
        contact = self._require("contact", invite.contact_id, VendorContact)
        review = self._vendor_review_projection(case)
        payload = {
            "invite": {
                "invite_id": invite.invite_id,
                "case_id": invite.case_id,
                "expires_at": invite.expires_at,
                "status": invite.status.value,
            },
            "vendor": {"vendor_id": vendor.vendor_id, "name": vendor.name},
            "product": {"product_id": product.product_id, "name": product.name},
            "contact": {
                "contact_id": contact.contact_id,
                "name": contact.name,
                "email": contact.email,
            },
            "submission": submission.to_vendor_dict(),
            "questions": self.unresolved_questions(token),
        }
        if review is not None:
            payload["review"] = review
        return payload

    # Vendor-only draft operations; token determines case and scope -----------

    def add_evidence(self, token: str, payload: dict[str, Any]) -> EvidenceArtifact:
        required = {"filename", "content_type", "size_bytes", "sha256"}
        self._reject_extra(payload, required | {"content_base64"})
        if not required <= set(payload):
            raise VendorBackendError("validation_error", "payload fields do not match the contract")
        invite = self._valid_invite(token)
        submission = self._draft_submission(invite)
        filename = self._text(payload.get("filename"), "filename")
        if len(filename) > 255 or "/" in filename or "\\" in filename:
            raise VendorBackendError("invalid_filename", "filename must be a basename")
        content_type = self._text(payload.get("content_type"), "content_type")
        if content_type not in ACCEPTED_CONTENT_TYPES:
            raise VendorBackendError(
                "unsupported_content_type",
                "evidence type is unsupported and must be reviewed manually",
                status=415,
            )
        size = payload.get("size_bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or not 1 <= size <= MAX_EVIDENCE_BYTES
        ):
            raise VendorBackendError(
                "invalid_size",
                f"size_bytes must be between 1 and {MAX_EVIDENCE_BYTES}",
            )
        digest = self._text(payload.get("sha256"), "sha256").lower()
        if not _SHA256.fullmatch(digest):
            raise VendorBackendError("invalid_hash", "sha256 must be 64 hexadecimal characters")
        existing = [
            item
            for item in self._list("evidence", EvidenceArtifact)
            if item.submission_id == submission.submission_id and item.sha256 == digest
        ]
        if existing:
            artifact = existing[0]
            if (
                artifact.filename != filename
                or artifact.content_type != content_type
                or artifact.size_bytes != size
            ):
                raise VendorBackendError(
                    "evidence_identity_conflict",
                    "sha256 is already registered with different immutable metadata",
                    status=409,
                )
            return artifact
        if "content_base64" in payload:
            # Small files travel inline (both runtimes cap JSON bodies at
            # ~1 MB) and land behind the storage seam so content validation
            # (issue #36) can parse them. The declared hash and size are
            # verified before storing; a mismatch fails closed.
            self._store_evidence_bytes(payload.get("content_base64"), digest, size)
        artifact = EvidenceArtifact(
            artifact_id=self._id("evidence", "evidence"),
            submission_id=submission.submission_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size,
            sha256=digest,
            workspace_id=self.workspace_id,
        )
        self._put("evidence", artifact.artifact_id, artifact)
        updated = replace(
            submission,
            evidence_artifact_ids=(*submission.evidence_artifact_ids, artifact.artifact_id),
            updated_at=self._now(),
        )
        self._save_progress(invite, updated)
        return artifact

    def evidence_upload_context(
        self, token: str, artifact_id: str
    ) -> tuple[VendorInvite, Submission, VendorProduct, Vendor, EvidenceArtifact]:
        invite = self._valid_invite(token)
        submission = self._submission_for_invite(invite.invite_id)
        if artifact_id not in submission.evidence_artifact_ids:
            raise VendorBackendError(
                "cross_case_evidence", "evidence does not belong to this submission", status=403
            )
        artifact = self._require("evidence", artifact_id, EvidenceArtifact)
        product = self._require("product", invite.product_id, VendorProduct)
        vendor = self._require("vendor", product.vendor_id, Vendor)
        return invite, submission, product, vendor, artifact

    def submission_evidence(
        self, token: str
    ) -> tuple[VendorInvite, Submission, list[EvidenceArtifact]]:
        invite = self._valid_invite(token)
        submission = self._submission_for_invite(invite.invite_id)
        allowed = set(submission.evidence_artifact_ids)
        artifacts = [
            item
            for item in self._list("evidence", EvidenceArtifact)
            if item.artifact_id in allowed
        ]
        return invite, submission, artifacts

    def case_evidence(self, case_id: str) -> list[EvidenceArtifact]:
        submission_ids = {
            item.submission_id
            for item in self._list("submission", Submission)
            if item.case_id == case_id
        }
        return [
            item
            for item in self._list("evidence", EvidenceArtifact)
            if item.submission_id in submission_ids
        ]

    def case_upload_context(self, case_id: str) -> tuple[VendorCase, VendorProduct, Vendor]:
        case = self._require("case", case_id, VendorCase)
        product = self._require("product", case.product_id, VendorProduct)
        vendor = self._require("vendor", product.vendor_id, Vendor)
        return case, product, vendor

    def set_trust_center_url(self, token: str, url: str) -> Submission:
        invite = self._valid_invite(token)
        submission = self._draft_submission(invite)
        clean_url = self._trust_url(url)
        updated = replace(submission, trust_center_url=clean_url, updated_at=self._now())
        self._save_progress(invite, updated)
        return updated

    def add_coverage(
        self, token: str, requirement_id: str, evidence_artifact_ids: list[str]
    ) -> CoverageItem:
        invite = self._valid_invite(token)
        submission = self._draft_submission(invite)
        criterion, profile = self._criterion(requirement_id)
        if (
            not isinstance(evidence_artifact_ids, list)
            or not evidence_artifact_ids
            or not all(isinstance(item, str) for item in evidence_artifact_ids)
        ):
            raise VendorBackendError("invalid_evidence", "evidence_artifact_ids are required")
        allowed = set(submission.evidence_artifact_ids)
        if not set(evidence_artifact_ids) <= allowed:
            raise VendorBackendError("cross_case_evidence", "evidence does not belong to this submission", status=403)
        coverage = CoverageItem(
            coverage_id=self._id("coverage", "coverage"),
            submission_id=submission.submission_id,
            requirement_id=criterion.requirement_id,
            profile_version_id=profile.profile_version_id,
            evidence_artifact_ids=tuple(evidence_artifact_ids),
            source_citation=dict(criterion.source_citation),
            workspace_id=self.workspace_id,
        )
        self._put("coverage", coverage.coverage_id, coverage)
        updated = replace(
            submission,
            coverage_ids=(*submission.coverage_ids, coverage.coverage_id),
            updated_at=self._now(),
        )
        self._save_progress(invite, updated)
        return coverage

    def save_answers(self, token: str, answers: dict[str, str]) -> Submission:
        invite = self._valid_invite(token)
        submission = self._draft_submission(invite)
        if not submission.intake_analysis_complete:
            raise VendorBackendError(
                "intake_analysis_pending",
                "run intake analysis before answering unresolved questions",
                status=409,
            )
        if not isinstance(answers, dict) or not answers:
            raise VendorBackendError("invalid_answers", "answers must be a non-empty object")
        unresolved = {item["requirement_id"] for item in self.unresolved_questions(token)}
        if not set(answers) <= unresolved:
            raise VendorBackendError(
                "invalid_requirement", "answers may reference only unresolved active requirements"
            )
        cleaned: dict[str, str] = {}
        for requirement_id, answer in answers.items():
            cleaned[requirement_id] = self._text(answer, f"answer {requirement_id}")
        updated = replace(
            submission,
            answers={**submission.answers, **cleaned},
            updated_at=self._now(),
        )
        self._save_progress(invite, updated)
        return updated

    def unresolved_questions(self, token: str) -> list[dict[str, Any]]:
        invite = self._valid_invite(token)
        submission = self._submission_for_invite(invite.invite_id)
        # Staged intake: unresolved requirement questions are exposed only after
        # the deterministic research/coverage/extraction step has run over the
        # submitted evidence and trust-center metadata (issue #27).
        if not submission.intake_analysis_complete:
            return []
        covered = {
            item.requirement_id
            for item in self._list("coverage", CoverageItem)
            if item.submission_id == submission.submission_id
        }
        answered = {key for key, value in submission.answers.items() if value.strip()}
        questions: list[dict[str, Any]] = []
        for profile in self.profiles.active_profiles():
            for criterion in profile.criteria:
                if criterion.requirement_id in covered or criterion.requirement_id in answered:
                    continue
                questions.append(
                    {
                        "requirement_id": criterion.requirement_id,
                        "question": criterion.question,
                        "expected_evidence": list(criterion.expected_evidence),
                    }
                )
        return sorted(questions, key=lambda item: item["requirement_id"])

    # Vendor-safe review-stage projection (issue #38): internal lifecycle states
    # collapse to the few stages a vendor may see; reviewer-only states never
    # leak through the vendor endpoints.
    _VENDOR_REVIEW_STAGES: dict[CaseLifecycle, str] = {
        CaseLifecycle.DRAFT: "collecting_evidence",
        CaseLifecycle.INVITED: "collecting_evidence",
        CaseLifecycle.OPENED: "collecting_evidence",
        CaseLifecycle.IN_PROGRESS: "collecting_evidence",
        CaseLifecycle.SUBMITTED: "under_review",
        CaseLifecycle.ANALYZING: "under_review",
        CaseLifecycle.NEEDS_REVIEW: "under_review",
        CaseLifecycle.CHANGES_REQUESTED: "changes_requested",
        CaseLifecycle.APPROVED: "decided",
        CaseLifecycle.DECLINED: "decided",
        CaseLifecycle.WRITEBACK_COMPLETE: "decided",
    }
    _VENDOR_OUTCOMES: dict[CaseLifecycle, str] = {
        CaseLifecycle.APPROVED: "approved",
        CaseLifecycle.WRITEBACK_COMPLETE: "approved",
        CaseLifecycle.DECLINED: "declined",
    }

    def review_status(self, token: str) -> dict[str, Any]:
        """Vendor-facing review status: received/outstanding checklist and stage.

        Unlike the draft operations this stays readable after the submission is
        finalized (the invite is SUBMITTED) so a vendor can track the review and
        its outcome without contacting the campus team (issue #38). The
        checklist is exposed only after intake analysis has run, consistent with
        staged intake.
        """
        invite = self._status_invite(token)
        submission = self._submission_for_invite(invite.invite_id)
        case = self._require("case", invite.case_id, VendorCase)
        product = self._require("product", invite.product_id, VendorProduct)
        vendor = self._require("vendor", product.vendor_id, Vendor)
        return {
            "invite": {
                "invite_id": invite.invite_id,
                "case_id": invite.case_id,
                "status": invite.status.value,
                "expires_at": invite.expires_at,
            },
            "vendor": {"vendor_id": vendor.vendor_id, "name": vendor.name},
            "product": {"product_id": product.product_id, "name": product.name},
            "submission_status": submission.status.value,
            "intake_analysis_complete": submission.intake_analysis_complete,
            "review_stage": self._VENDOR_REVIEW_STAGES[case.lifecycle],
            "outcome": self._VENDOR_OUTCOMES.get(case.lifecycle),
            "vendor_visible_comment": case.vendor_visible_comment,
            "next_actions": (
                list(case.vendor_next_actions)
                if case.lifecycle is CaseLifecycle.CHANGES_REQUESTED
                else []
            ),
            "checklist": self._checklist(submission),
        }

    def _checklist(self, submission: Submission) -> list[dict[str, Any]]:
        """Active-profile requirements with an honest per-requirement status.

        ``received``: an evidence artifact is linked to the requirement through
        a coverage item. ``processing``: only an unvalidated free-text answer
        exists; it is never presented as received evidence. ``outstanding``:
        nothing was provided. The contract additionally reserves ``accepted``,
        ``invalid``, and ``stale`` for evidence validation (issue #36), which
        this projection does not perform.
        """
        if not submission.intake_analysis_complete:
            # Staged intake: requirement names are exposed only after the
            # deterministic analysis step, matching unresolved_questions.
            return []
        covered = {
            item.requirement_id
            for item in self._list("coverage", CoverageItem)
            if item.submission_id == submission.submission_id
        }
        answered = {key for key, value in submission.answers.items() if value.strip()}
        items: list[dict[str, Any]] = []
        for profile in self.profiles.active_profiles():
            for criterion in profile.criteria:
                if criterion.requirement_id in covered:
                    status = "received"
                elif criterion.requirement_id in answered:
                    status = "processing"
                else:
                    status = "outstanding"
                items.append(
                    {
                        "requirement_id": criterion.requirement_id,
                        "question": criterion.question,
                        "expected_evidence": list(criterion.expected_evidence),
                        "status": status,
                    }
                )
        return sorted(items, key=lambda item: item["requirement_id"])

    def _status_invite(self, token: str) -> VendorInvite:
        """Token lookup for the read-only status view; permits submitted invites."""
        if not isinstance(token, str) or not token:
            raise VendorBackendError("invalid_invite", "invitation is invalid", status=404)
        invite = self.repository.find_invite_by_token_hash(
            self._hash_token(token), workspace_id=self.workspace_id
        )
        if invite is None:
            raise VendorBackendError("invalid_invite", "invitation is invalid", status=404)
        if invite.status is InviteStatus.REVOKED:
            raise VendorBackendError("invite_revoked", "invitation was revoked", status=410)
        # Expiry applies to submitted invitations too: the status view is
        # readable after finalize, but only within the invitation's lifetime,
        # matching the expiry semantics of every other token operation.
        expires = parse_utc_timestamp(invite.expires_at)
        if self._now_datetime() >= expires:
            if invite.status is not InviteStatus.SUBMITTED:
                self._put("invite", invite.invite_id, replace(invite, status=InviteStatus.EXPIRED))
            raise VendorBackendError("invite_expired", "invitation expired", status=410)
        return invite

    def intake_stage(self, token: str) -> dict[str, Any]:
        """Return the current staged-intake position for the vendor UI."""
        invite = self._valid_invite(token)
        submission = self._submission_for_invite(invite.invite_id)
        has_evidence = bool(submission.evidence_artifact_ids)
        has_trust_center = submission.trust_center_url is not None
        if submission.intake_analysis_complete:
            stage = "questions"
        elif has_trust_center and has_evidence:
            stage = "ready_for_analysis"
        else:
            stage = "collecting_evidence"
        return {
            "stage": stage,
            "intake_analysis_complete": submission.intake_analysis_complete,
            "has_evidence": has_evidence,
            "has_trust_center": has_trust_center,
            "research_summary": submission.research_summary,
        }

    def run_intake_analysis(self, token: str) -> Submission:
        """Deterministic research/coverage/extraction step (issue #27).

        Prerequisites: the vendor has provided trust-center metadata and at least
        one evidence artifact. The step performs deterministic "research" (records
        the validated trust-center host and evidence inventory) and "extraction"
        (matches evidence filenames/content-type tokens against each active
        requirement's expected evidence, recording auto-coverage). No model
        confirms a match and no policy threshold is set here. Only after this
        completes are unresolved requirement questions exposed.
        """
        invite = self._valid_invite(token)
        submission = self._draft_submission(invite)
        if submission.trust_center_url is None:
            raise VendorBackendError(
                "analysis_prerequisites",
                "provide a trust-center URL before running intake analysis",
                status=409,
            )
        if not submission.evidence_artifact_ids:
            raise VendorBackendError(
                "analysis_prerequisites",
                "provide at least one evidence artifact before running intake analysis",
                status=409,
            )
        evidence = [
            item
            for item in self._list("evidence", EvidenceArtifact)
            if item.artifact_id in set(submission.evidence_artifact_ids)
        ]
        already_covered = {
            item.requirement_id
            for item in self._list("coverage", CoverageItem)
            if item.submission_id == submission.submission_id
        }
        # Content validation (issue #36): a document with any failed or
        # manual-review finding (including PCI currency TBD or unavailable
        # bytes) must not count as received, so its artifact is excluded from
        # auto-coverage below.
        findings = self._validate_evidence_contents(submission, evidence)
        failed_artifact_ids = {finding.artifact_id for finding in findings}
        auto_covered: list[str] = []
        for profile in self.profiles.active_profiles():
            for criterion in profile.criteria:
                if criterion.requirement_id in already_covered:
                    continue
                matched = [
                    artifact_id
                    for artifact_id in self._extract_matches(criterion, evidence)
                    if artifact_id not in failed_artifact_ids
                ]
                if not matched:
                    continue
                coverage = CoverageItem(
                    coverage_id=self._id("coverage", "coverage"),
                    submission_id=submission.submission_id,
                    requirement_id=criterion.requirement_id,
                    profile_version_id=profile.profile_version_id,
                    evidence_artifact_ids=tuple(matched),
                    source_citation={**dict(criterion.source_citation), "extraction": "deterministic"},
                    workspace_id=self.workspace_id,
                )
                self._put("coverage", coverage.coverage_id, coverage)
                submission = replace(
                    submission,
                    coverage_ids=(*submission.coverage_ids, coverage.coverage_id),
                )
                auto_covered.append(criterion.requirement_id)
        host = urlsplit(str(submission.trust_center_url)).hostname or "unknown"
        # Official-domain research (issue #44): fetch the confirmed trust-center
        # URL through the guarded provider when one is configured, capturing
        # resolvable provenance for same-domain evidence and surfacing failures
        # as gaps. This annotates only; coverage/questions above are unchanged
        # and research never approves, sets policy, or invents requirements.
        research_dict, research_note = self._run_official_domain_research(submission)
        research_summary = (
            f"Reviewed trust-center host {host}; inventoried {len(evidence)} evidence "
            f"artifact(s); auto-covered {len(auto_covered)} requirement(s) by deterministic "
            f"extraction; recorded {len(findings)} content-validation finding(s). "
            f"{research_note}"
        )
        finished = replace(
            submission,
            intake_analysis_complete=True,
            research_summary=research_summary,
            updated_at=self._now(),
        )
        self._put("submission", finished.submission_id, finished)
        self._event(
            "intake.analyzed",
            "submission",
            finished.submission_id,
            case_id=invite.case_id,
            detail={
                "auto_covered_requirement_ids": auto_covered,
                "evidence_count": len(evidence),
                "trust_center_host": host,
                "validation_findings": [
                    {"artifact_id": finding.artifact_id, "check": finding.check}
                    for finding in findings
                ],
                "research_performed": research_dict is not None,
                "research": research_dict,
                # Deterministic extraction remains a stand-in; live research is
                # genuine only when a guarded provider returned provenance.
                "simulated": research_dict is None,
            },
        )
        return finished

    def _validate_evidence_contents(
        self, submission: Submission, evidence: list[EvidenceArtifact]
    ) -> list[EvidenceValidationFinding]:
        """Extract and check evidence fields; persist every failure or warning.

        Extraction is a swappable adapter (deterministic locally, model on AWS),
        but every disposition is deterministic. Missing bytes, unreadable bytes,
        and unknown document types fail closed with a manual-review finding so a
        filename can never auto-cover a requirement without inspectable content.
        """
        # Re-analysis replaces this submission's findings instead of appending
        # duplicates: prior findings are removed and finding IDs are derived
        # from (artifact, check), so running the analysis twice is idempotent.
        for existing in self._list("finding", EvidenceValidationFinding):
            if existing.submission_id == submission.submission_id:
                self.repository.delete(
                    "finding", existing.finding_id, workspace_id=self.workspace_id
                )
        product = self._require("product", submission.product_id, VendorProduct)
        vendor = self._require("vendor", product.vendor_id, Vendor)
        today = self._now_datetime().date()
        findings: list[EvidenceValidationFinding] = []
        for artifact in evidence:
            evidence_type = classify_evidence_type(artifact.filename, artifact.content_type)
            if evidence_type is None:
                # Issue #36 defines deterministic content rules only for COI,
                # pen-test, and PCI documents. Evidence of any other type has no
                # content check to run, so it is neither validated nor blocked
                # here: existing filename-based auto-coverage is unchanged and a
                # reviewer can still inspect the retained artifact.
                continue
            text, content_status = self._evidence_text(artifact)
            fields: dict[str, Any] = {}
            if content_status == "unavailable":
                failures = [
                    {
                        "check": "evidence.content_unavailable",
                        "reason": "Evidence bytes are unavailable, so the document cannot be "
                        "validated or used for automatic coverage; a human must review it.",
                        "disposition": "manual_review",
                    }
                ]
            elif content_status == "unreadable":
                failures = [
                    {
                        "check": "evidence.content_unreadable",
                        "reason": "Evidence bytes could not be read as supported text, so the "
                        "document cannot be validated or used for automatic coverage; a human "
                        "must review it.",
                        "disposition": "manual_review",
                    }
                ]
            else:
                assert text is not None
                fields = self._extractor.extract_fields(
                    filename=artifact.filename,
                    content_type=artifact.content_type,
                    evidence_type=evidence_type or "unknown",
                    text=text,
                )
                # A document naming another vendor/product is rejected from
                # automatic coverage regardless of its type (issue #36).
                failures = validate_identity(
                    fields=fields, vendor_name=vendor.name, product_name=product.name
                )
                failures.extend(
                    validate_evidence(evidence_type=evidence_type, fields=fields, today=today)
                )
            for failure in failures:
                line = self._finding_line(fields, failure["check"])
                finding = EvidenceValidationFinding(
                    finding_id=f"finding-{artifact.artifact_id}-{failure['check']}",
                    submission_id=submission.submission_id,
                    artifact_id=artifact.artifact_id,
                    filename=artifact.filename,
                    evidence_type=evidence_type or "unknown",
                    check=failure["check"],
                    reason=failure["reason"],
                    disposition=failure["disposition"],
                    source_citation={
                        "source_id": artifact.artifact_id,
                        "filename": artifact.filename,
                        "sha256": artifact.sha256,
                        "line": line,
                        "rule_source_id": RULE_SOURCE["source_id"],
                        "rule_section": RULE_SOURCE["section"],
                    },
                    workspace_id=self.workspace_id,
                )
                self._put("finding", finding.finding_id, finding)
                findings.append(finding)
        return findings

    @staticmethod
    def _finding_line(fields: dict[str, Any], check: str) -> int:
        """Resolve the exact extracted-field line, or line 1 for document-level results."""
        fields_by_check = {
            "coi.expired": ("expires_date",),
            "coi.expiry_unknown": ("expires_date",),
            "pentest.stale": ("report_date", "issued_date"),
            "pentest.date_unknown": ("report_date", "issued_date"),
            "pci.currency_unverified": ("assessment_date", "issued_date"),
            "evidence.vendor_mismatch": ("vendor",),
            "evidence.product_mismatch": ("product",),
        }
        coordinates = fields.get(EXTRACTION_COORDINATES_FIELD)
        if isinstance(coordinates, dict):
            for field_name in fields_by_check.get(check, ()):
                coordinate = coordinates.get(field_name)
                if isinstance(coordinate, dict):
                    line = coordinate.get("line")
                    if isinstance(line, int) and not isinstance(line, bool) and line >= 1:
                        return line
        return 1

    def _store_evidence_bytes(self, content: object, digest: str, size: int) -> None:
        if self._evidence_storage is None:
            raise VendorBackendError(
                "storage_unavailable", "evidence storage is not configured", status=503
            )
        if not isinstance(content, str) or not content:
            raise VendorBackendError("invalid_content", "content_base64 must be a base64 string")
        try:
            body = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError) as error:
            raise VendorBackendError(
                "invalid_content", "content_base64 must be a base64 string"
            ) from error
        if len(body) != size or hashlib.sha256(body).hexdigest() != digest:
            raise VendorBackendError(
                "content_mismatch", "content does not match the declared sha256 and size"
            )
        self._evidence_storage.put_object(key=f"evidence/{digest}", body=body)

    def _evidence_text(self, artifact: EvidenceArtifact) -> tuple[str | None, str | None]:
        """Return supported text or a fail-closed ``unavailable``/``unreadable`` status."""
        if self._evidence_storage is None:
            return None, "unavailable"
        key = f"evidence/{artifact.sha256}"
        try:
            if not self._evidence_storage.exists(key=key):
                return None, "unavailable"
            body = self._evidence_storage.get_object(key=key)
        except Exception:  # Storage/provider failures are reviewable, never automatic coverage.
            return None, "unavailable"
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None, "unreadable"
        if not text.strip() or any(
            ord(character) < 32 and character not in "\t\n\r" for character in text
        ):
            return None, "unreadable"
        return text, None

    def submission_findings(self, token: str) -> list[dict[str, Any]]:
        """Vendor-visible content-validation findings for the invite's submission."""
        invite = self._valid_invite(token)
        submission = self._submission_for_invite(invite.invite_id)
        return self._findings_for_submission(submission.submission_id)

    def case_evidence_findings(self, case_id: str) -> list[dict[str, Any]]:
        """Reviewer view: all content-validation findings across a case's submissions."""
        submission_ids = {
            item.submission_id
            for item in self._list("submission", Submission)
            if item.case_id == case_id
        }
        findings: list[dict[str, Any]] = []
        for finding in self._list("finding", EvidenceValidationFinding):
            if finding.submission_id in submission_ids:
                findings.append(finding.to_dict())
        return sorted(findings, key=lambda item: item["finding_id"])

    def _findings_for_submission(self, submission_id: str) -> list[dict[str, Any]]:
        return sorted(
            (
                finding.to_dict()
                for finding in self._list("finding", EvidenceValidationFinding)
                if finding.submission_id == submission_id
            ),
            key=lambda item: item["finding_id"],
        )

    def _run_official_domain_research(
        self, submission: Submission
    ) -> tuple[dict | None, str]:
        """Run guarded official-domain research for the trust-center URL.

        Returns ``(research_result_dict_or_None, human_summary_note)``. When no
        provider is configured, research is not performed and this is stated
        truthfully; nothing is fabricated. Research output is provenance/gaps
        only and does not alter coverage, questions, policy, or approval.
        """

        if self._research is None or submission.trust_center_url is None:
            return None, "Live official-domain research was not performed in this environment."
        product = self._require("product", submission.product_id, VendorProduct)
        vendor = self._require("vendor", product.vendor_id, Vendor)
        result = self._research.research(
            official_url=submission.trust_center_url,
            targets=[submission.trust_center_url],
            vendor=vendor.name,
            product=product.name,
        )
        research_dict = result.to_dict()
        note = (
            f"Official-domain research captured {len(result.findings)} provenance-backed "
            f"source(s), {len(result.gaps)} gap(s) for manual review, and quarantined "
            f"{len(result.quarantined)} off-domain link(s)."
        )
        return research_dict, note

    def intake_research(self, token: str) -> dict | None:
        """Return the provenance/gaps payload from the latest intake analysis.

        Provides reviewers/analysis a resolvable record of official-domain
        research (final URL, redirect chain, hash, MIME, scope, gaps, quarantined
        links). Returns ``None`` if analysis has not run or no provider was
        configured.
        """

        invite = self._valid_invite(token)
        submission = self._submission_for_invite(invite.invite_id)
        events = [
            event
            for event in self._list("event", IntegrationEvent)
            if event.resource_id == submission.submission_id
            and event.event_type == "intake.analyzed"
        ]
        if not events:
            return None
        latest = max(events, key=lambda event: event.occurred_at)
        return latest.detail.get("research")

    def case_intake_research(self, case_id: str) -> dict | None:
        """Reviewer-facing, case-scoped official-domain research provenance.

        Returns the provenance/gaps/quarantined payload from the latest intake
        analysis for ``case_id`` (workspace-isolated via :meth:`_require`), or
        ``None`` if analysis has not run or no provider was configured. Unlike
        :meth:`intake_research`, this is keyed by the reviewer-supplied case id --
        no invite token is required, accepted, or logged -- so a reviewer (not
        only a bearer-token vendor caller) can inspect full provenance, gaps, and
        quarantined links. Read-only; it never alters approval, policy, criteria,
        or requirements.
        """

        self._require("case", case_id, VendorCase)
        events = [
            event
            for event in self._list("event", IntegrationEvent)
            if event.event_type == "intake.analyzed" and event.case_id == case_id
        ]
        if not events:
            return None
        latest = max(events, key=lambda event: event.occurred_at)
        return latest.detail.get("research")

    @staticmethod
    def _extract_matches(criterion, evidence: list[EvidenceArtifact]) -> list[str]:
        """Deterministic token match of evidence to a requirement's expected evidence.

        Tokens are drawn from the requirement's ``expected_evidence`` phrases only
        (length >= 3) and matched as substrings against each artifact's normalized
        filename and content-type. This is a deterministic heuristic, not a model
        or semantic match; unmatched requirements stay open for the vendor.
        """
        tokens: set[str] = set()
        for phrase in criterion.expected_evidence:
            for token in _NORMALIZE_TOKENS.split(phrase.lower()):
                if len(token) >= 3:
                    tokens.add(token)
        matched: list[str] = []
        for artifact in evidence:
            haystack = _NORMALIZE.sub("", artifact.filename.lower()) + " " + artifact.content_type.lower()
            if any(token in haystack for token in tokens):
                matched.append(artifact.artifact_id)
        return matched

    def record_changes_requested(
        self,
        case_id: str,
        *,
        comment: str | None,
        next_actions: tuple[str, ...] | None = None,
    ) -> VendorCase:
        case = self._require("case", case_id, VendorCase)
        actions = next_actions if next_actions is not None else (
            "Supplement the requested evidence or answers.",
            "Finalize again when you are ready for the reviewer to continue.",
        )
        updated = replace(
            case,
            vendor_visible_comment=comment.strip() if comment and comment.strip() else None,
            vendor_next_actions=actions,
        )
        self._put("case", case.case_id, updated)
        return updated

    def reopen_submission(self, case_id: str) -> Submission | None:
        """Return a finalized vendor submission to draft so the same invite can be edited."""
        submitted = [
            invite
            for invite in self._list("invite", VendorInvite)
            if invite.case_id == case_id and invite.status is InviteStatus.SUBMITTED
        ]
        if not submitted:
            return None
        invite = max(submitted, key=lambda item: item.submitted_at or "")
        submission = self._submission_for_invite(invite.invite_id)
        if submission.status is not SubmissionStatus.FINALIZED:
            raise VendorBackendError(
                "submission_not_finalized",
                "submission is not finalized",
                status=409,
            )
        now = self._now()
        now_dt = self._now_datetime()
        expires_at = invite.expires_at
        expires = datetime.datetime.fromisoformat(expires_at)
        if expires - now_dt <= datetime.timedelta(days=1):
            expires_at = (now_dt + datetime.timedelta(days=7)).isoformat()
        reopened = replace(
            submission,
            status=SubmissionStatus.DRAFT,
            version=submission.version + 1,
            finalized_at=None,
            updated_at=now,
        )
        reopened_invite = replace(
            invite,
            status=InviteStatus.IN_PROGRESS,
            submitted_at=None,
            expires_at=expires_at,
        )
        self._put("submission", reopened.submission_id, reopened)
        self._put("invite", reopened_invite.invite_id, reopened_invite)
        self._event(
            "submission.reopened",
            "submission",
            reopened.submission_id,
            case_id=case_id,
            detail={"version": reopened.version},
        )
        return reopened

    def finalize_submission(self, token: str) -> Submission:
        invite = self._valid_invite(token)
        submission = self._draft_submission(invite)
        now = self._now()
        finalized = replace(
            submission,
            status=SubmissionStatus.FINALIZED,
            finalized_at=now,
            updated_at=now,
        )
        self._put("submission", finalized.submission_id, finalized)
        self._put(
            "invite",
            invite.invite_id,
            replace(invite, status=InviteStatus.SUBMITTED, submitted_at=now),
        )
        case = self._require("case", invite.case_id, VendorCase)
        self._put("case", case.case_id, replace(case, lifecycle=CaseLifecycle.SUBMITTED))
        self._event("submission.finalized", "submission", finalized.submission_id, case_id=case.case_id)
        return finalized

    # Reviewer-driven lifecycle transitions ----------------------------------

    _ALLOWED_TRANSITIONS: dict[CaseLifecycle, frozenset[CaseLifecycle]] = {
        CaseLifecycle.NEEDS_REVIEW: frozenset(
            {
                CaseLifecycle.DRAFT,
                CaseLifecycle.INVITED,
                CaseLifecycle.OPENED,
                CaseLifecycle.IN_PROGRESS,
                CaseLifecycle.SUBMITTED,
                CaseLifecycle.ANALYZING,
                CaseLifecycle.CHANGES_REQUESTED,
                CaseLifecycle.NEEDS_REVIEW,
            }
        ),
        CaseLifecycle.APPROVED: frozenset(
            {CaseLifecycle.NEEDS_REVIEW, CaseLifecycle.ANALYZING, CaseLifecycle.CHANGES_REQUESTED,
             CaseLifecycle.APPROVED}
        ),
        CaseLifecycle.CHANGES_REQUESTED: frozenset(
            {
                CaseLifecycle.NEEDS_REVIEW,
                CaseLifecycle.ANALYZING,
                CaseLifecycle.CHANGES_REQUESTED,
                CaseLifecycle.SUBMITTED,
            }
        ),
        CaseLifecycle.DECLINED: frozenset(
            {CaseLifecycle.NEEDS_REVIEW, CaseLifecycle.ANALYZING, CaseLifecycle.CHANGES_REQUESTED,
             CaseLifecycle.DECLINED}
        ),
        CaseLifecycle.WRITEBACK_COMPLETE: frozenset(
            {CaseLifecycle.APPROVED, CaseLifecycle.WRITEBACK_COMPLETE}
        ),
    }

    def transition_case(
        self,
        case_id: str,
        target: CaseLifecycle,
        *,
        vendor_visible_comment: str | None | object = _UNSET,
        vendor_next_actions: tuple[str, ...] | object = _UNSET,
    ) -> VendorCase:
        """Persist a reviewer/analysis lifecycle transition (issue #27).

        Public messaging is stored on the vendor-case projection, separately
        from internal reviewer comments. Analysis transitions omit these
        arguments and preserve the last public message. Human outcomes pass
        them explicitly, clearing stale actions on approve/decline. When a
        changes-requested decision has no authored actions, stable outstanding
        requirement IDs provide safe next steps without exposing findings,
        policy, risk, or reviewer notes.
        """
        case = self.repository.get("case", case_id, workspace_id=self.workspace_id)
        if not isinstance(case, VendorCase):
            # A case that was never registered as a vendor case has no lifecycle
            # to persist; callers treat this as a benign no-op.
            return None  # type: ignore[return-value]
        if case.lifecycle is not target:
            allowed = self._ALLOWED_TRANSITIONS.get(target)
            if allowed is None or case.lifecycle not in allowed:
                raise VendorBackendError(
                    "invalid_transition",
                    f"cannot move case from {case.lifecycle.value} to {target.value}",
                    status=409,
                )
        updates: dict[str, Any] = {"lifecycle": target}
        if vendor_visible_comment is not _UNSET:
            updates["vendor_visible_comment"] = vendor_visible_comment
        if vendor_next_actions is not _UNSET:
            actions = tuple(vendor_next_actions)  # type: ignore[arg-type]
            if target is CaseLifecycle.CHANGES_REQUESTED and not actions:
                actions = self._derive_vendor_next_actions(case_id)
            updates["vendor_next_actions"] = actions
        updated = replace(case, **updates)
        if updated == case:
            return case
        self._put("case", case_id, updated)
        self._event(
            "case.transitioned",
            "case",
            case_id,
            case_id=case_id,
            detail={"from": case.lifecycle.value, "to": target.value},
        )
        return updated

    def _derive_vendor_next_actions(self, case_id: str) -> tuple[str, ...]:
        requirement_ids: tuple[str, ...] = ()
        run_id = self.repository.get_current_run_id(case_id, workspace_id=self.workspace_id)
        if run_id is not None:
            run = self.repository.get("run", run_id, workspace_id=self.workspace_id)
            if isinstance(run, ReviewRun):
                requirement_ids = run.unresolved_requirement_ids
        if not requirement_ids:
            submissions = [
                item
                for item in self._list("submission", Submission)
                if item.case_id == case_id and item.intake_analysis_complete
            ]
            if submissions:
                submission = max(
                    submissions,
                    key=lambda item: item.finalized_at or item.updated_at or "",
                )
                requirement_ids = tuple(
                    item["requirement_id"]
                    for item in self._checklist(submission)
                    if item["status"] == "outstanding"
                )
        unique_ids = tuple(dict.fromkeys(sorted(requirement_ids)))[:10]
        if unique_ids:
            return tuple(
                f"Provide information or evidence for requirement {requirement_id}."
                for requirement_id in unique_ids
            )
        return ("Contact your campus reviewer to confirm the requested updates.",)

    def get_case_lifecycle(self, case_id: str) -> str | None:
        case = self.repository.get("case", case_id, workspace_id=self.workspace_id)
        return case.lifecycle.value if isinstance(case, VendorCase) else None

    def record_notification(
        self,
        *,
        case_id: str | None,
        summary: str,
        delivery: dict[str, Any],
        event_type: str = "slack.notification",
        dedupe_key: str | None = None,
    ) -> IntegrationEvent:
        """Persist an auditable notification event with its truthful delivery mode.

        The raw recipient address is never persisted: the event carries a
        SHA-256 digest instead, which stays auditable (a known address can be
        verified against it) without storing personal data in the event log.
        An optional ``dedupe_key`` is persisted so callers can record and check
        delivery idempotently (issue #38).
        """
        detail = {
            "summary": summary,
            "delivery": delivery.get("delivery"),
            "simulated": delivery.get("simulated", True),
            "channel": delivery.get("channel"),
        }
        if delivery.get("to"):
            detail["recipient_sha256"] = self._hash_recipient(str(delivery["to"]))
        if dedupe_key is not None:
            detail["dedupe_key"] = dedupe_key
        return self._event(
            event_type,
            "notification",
            case_id or "workspace",
            case_id=case_id,
            detail=detail,
        )

    def notification_recorded(self, *, event_type: str, dedupe_key: str) -> bool:
        """True when a notification with this dedupe key was already persisted."""
        return any(
            event.event_type == event_type and event.detail.get("dedupe_key") == dedupe_key
            for event in self._list("event", IntegrationEvent)
        )

    @staticmethod
    def _hash_recipient(recipient: str) -> str:
        return hashlib.sha256(recipient.strip().lower().encode("utf-8")).hexdigest()

    # Weekly vendor reminders (issue #37) -------------------------------------

    _REMINDER_EVENT = "email.reminder"
    # A failed delivery is retried on later sweeps within the same cadence
    # period, but never unboundedly.
    MAX_REMINDER_ATTEMPTS = 3
    # Reminders run only while the vendor still owes evidence; once the case
    # moves to reviewer-owned states the nagging stops.
    _REMINDER_LIFECYCLES = frozenset(
        {
            CaseLifecycle.DRAFT,
            CaseLifecycle.INVITED,
            CaseLifecycle.OPENED,
            CaseLifecycle.IN_PROGRESS,
        }
    )

    def reminder_candidates(self) -> list[dict[str, Any]]:
        """Cases with missing/incomplete evidence that are due a reminder.

        At most one candidate per case: when several invitations are active the
        most recently issued one is authoritative (consistent with the outcome
        email's submitted-contact rule). A case qualifies when its invite is
        still actionable (issued/opened/in progress and unexpired), its
        lifecycle has not moved past the vendor's part, reminders are not
        paused, its submission is an incomplete draft, and the current cadence
        period — anchored at the invite's issuance, so a new invitation only
        becomes due after one full ``reminder_interval`` — has not already been
        satisfied. Each candidate names the specific missing items and carries
        the deterministic ``dedupe_key`` the sweep must claim before sending.
        """
        now = self._now_datetime()
        authoritative: dict[str, VendorInvite] = {}
        for invite in self._list("invite", VendorInvite):
            if invite.status not in {
                InviteStatus.ISSUED,
                InviteStatus.OPENED,
                InviteStatus.IN_PROGRESS,
            }:
                continue
            if now >= parse_utc_timestamp(invite.expires_at):
                continue
            current = authoritative.get(invite.case_id)
            invite_order = (parse_utc_timestamp(invite.issued_at), invite.invite_id)
            current_order = (
                (parse_utc_timestamp(current.issued_at), current.invite_id)
                if current is not None
                else None
            )
            if current_order is None or invite_order > current_order:
                authoritative[invite.case_id] = invite
        candidates: list[dict[str, Any]] = []
        for case_id, invite in sorted(authoritative.items()):
            case = self.repository.get("case", case_id, workspace_id=self.workspace_id)
            if not isinstance(case, VendorCase) or case.lifecycle not in self._REMINDER_LIFECYCLES:
                continue
            if case.reminders_paused:
                continue
            try:
                submission = self._submission_for_invite(invite.invite_id)
            except VendorBackendError:
                continue
            if submission.status is not SubmissionStatus.DRAFT:
                continue
            stage, missing = self._missing_items(submission)
            if not missing:
                continue
            period = self._reminder_period(invite, now)
            if period < 1:
                # Not yet due: the first reminder comes one full interval
                # after the invitation, never immediately.
                continue
            dedupe_key = self._reminder_dedupe_key(case_id, period)
            claim = self._delivery_claims.get(
                workspace_id=self.workspace_id, dedupe_key=dedupe_key
            )
            if claim is not None and (
                claim.status != "failed" or claim.attempts >= self.MAX_REMINDER_ATTEMPTS
            ):
                continue
            contact = self._require("contact", invite.contact_id, VendorContact)
            product = self._require("product", invite.product_id, VendorProduct)
            candidates.append(
                {
                    "invite_id": invite.invite_id,
                    "case_id": case_id,
                    "dedupe_key": dedupe_key,
                    "contact_name": contact.name,
                    "contact_email": contact.email,
                    "product_name": product.name,
                    "intake_url": self._intake_url(invite),
                    "stage": stage,
                    "missing": missing,
                }
            )
        return candidates

    def claim_reminder(
        self, *, dedupe_key: str, case_id: str, invite_id: str
    ) -> ReminderClaim | None:
        """Atomically claim one cadence period before any email is sent.

        ``None`` means another worker owns the pending/sent attempt or the
        bounded failed-attempt budget is exhausted. The returned claim carries
        the attempt number used for conditional settlement.
        """
        return self._delivery_claims.claim(
            workspace_id=self.workspace_id,
            dedupe_key=dedupe_key,
            case_id=case_id,
            invite_id=invite_id,
            claimed_at=self._now(),
            max_attempts=self.MAX_REMINDER_ATTEMPTS,
        )

    def record_reminder(
        self,
        *,
        invite_id: str,
        case_id: str,
        dedupe_key: str,
        summary: str,
        delivery: dict[str, Any],
        claim: ReminderClaim | None = None,
    ) -> IntegrationEvent:
        """Settle and audit one reminder attempt without retaining raw email.

        Only explicit ``live`` and ``simulated`` modes satisfy cadence. Failed,
        skipped, missing, and unknown modes settle as failed and remain
        retryable until the atomic outbox reaches ``MAX_REMINDER_ATTEMPTS``.
        """
        current = claim or self._delivery_claims.get(
            workspace_id=self.workspace_id, dedupe_key=dedupe_key
        )
        mode = delivery.get("delivery") if isinstance(delivery, dict) else None
        successful = mode in {"live", "simulated"}
        if current is not None:
            self._delivery_claims.settle(
                workspace_id=self.workspace_id,
                dedupe_key=dedupe_key,
                attempts=current.attempts,
                status="sent" if successful else "failed",
            )
        detail = {
            "summary": summary,
            "delivery": mode if isinstance(mode, str) else "failed",
            "simulated": mode == "simulated",
            "channel": delivery.get("channel") if isinstance(delivery, dict) else "email",
            "dedupe_key": dedupe_key,
        }
        recipient = delivery.get("to") if isinstance(delivery, dict) else None
        if recipient:
            detail["recipient_sha256"] = self._hash_recipient(str(recipient))
        return self._event(
            self._REMINDER_EVENT,
            "invite",
            invite_id,
            case_id=case_id,
            detail=detail,
        )

    def reminder_history(self, case_id: str) -> dict[str, Any]:
        """Reviewer-facing reminder delivery history and pause state (issue #37)."""
        case = self.repository.get("case", case_id, workspace_id=self.workspace_id)
        attempts = [
            {
                "occurred_at": event.occurred_at,
                "invite_id": event.resource_id,
                "summary": event.detail.get("summary"),
                "delivery": event.detail.get("delivery"),
                "simulated": event.detail.get("simulated"),
                "dedupe_key": event.detail.get("dedupe_key"),
            }
            for event in self._list("event", IntegrationEvent)
            if event.event_type == self._REMINDER_EVENT and event.case_id == case_id
        ]
        attempts.sort(key=lambda item: item["occurred_at"] or "")
        return {
            "case_id": case_id,
            "paused": case.reminders_paused if isinstance(case, VendorCase) else False,
            "items": attempts,
        }

    def set_reminders_paused(self, case_id: str, paused: bool) -> dict[str, Any]:
        """Reviewer control: pause or resume automated reminders for one case."""
        case = self._require("case", case_id, VendorCase)
        if case.reminders_paused != paused:
            self._put("case", case_id, replace(case, reminders_paused=paused))
            self._event(
                "reminder.paused" if paused else "reminder.resumed",
                "case",
                case_id,
                case_id=case_id,
            )
        return {"case_id": case_id, "paused": paused}

    def _reminder_period(self, invite: VendorInvite, now: datetime.datetime) -> int:
        issued = parse_utc_timestamp(invite.issued_at)
        return int((now - issued) / self.reminder_interval)

    @staticmethod
    def _reminder_dedupe_key(case_id: str, period: int) -> str:
        return f"reminder:{case_id}:{period}"

    # Sealed invite links. The raw token is never persisted (only its SHA-256
    # hash authenticates requests); the seal XORs the token with an HMAC-SHA256
    # keystream keyed by the non-persisted link secret and the invite id, so
    # only a backend holding the secret can reconstruct the vendor's link.
    # Unsealing is verified against the stored token hash before use.

    def _keystream(self, invite_id: str, length: int) -> bytes:
        blocks = b""
        counter = 0
        while len(blocks) < length:
            blocks += hmac.new(
                self._link_secret, f"{invite_id}:{counter}".encode("utf-8"), hashlib.sha256
            ).digest()
            counter += 1
        return blocks[:length]

    def _seal_token(self, invite_id: str, token: str) -> str:
        raw = token.encode("utf-8")
        keystream = self._keystream(invite_id, len(raw))
        return bytes(a ^ b for a, b in zip(raw, keystream)).hex()

    def _unseal_token(self, invite: VendorInvite) -> str | None:
        if not invite.token_seal:
            return None
        try:
            sealed = bytes.fromhex(invite.token_seal)
        except ValueError:
            return None
        keystream = self._keystream(invite.invite_id, len(sealed))
        raw = bytes(a ^ b for a, b in zip(sealed, keystream))
        try:
            token = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
        if not hmac.compare_digest(self._hash_token(token), invite.token_hash):
            # Sealed under a different link secret (for example after a
            # restart without a configured secret); no link can be offered.
            return None
        return token

    def _intake_url(self, invite: VendorInvite) -> str | None:
        token = self._unseal_token(invite)
        if token is None:
            return None
        return f"{self.intake_base_url}#token={quote(token, safe='')}"

    def _missing_items(self, submission: Submission) -> tuple[str, list[dict[str, Any]]]:
        """Name what is still owed: submission gaps first, then open requirements."""
        if not submission.intake_analysis_complete:
            items: list[dict[str, Any]] = []
            if not submission.evidence_artifact_ids:
                items.append(
                    {
                        "requirement_id": None,
                        "label": "Evidence files",
                        "detail": "No evidence documents have been received yet.",
                    }
                )
            if submission.trust_center_url is None:
                items.append(
                    {
                        "requirement_id": None,
                        "label": "Trust-center URL",
                        "detail": "A public HTTPS trust-center link has not been provided.",
                    }
                )
            if not items:
                items.append(
                    {
                        "requirement_id": None,
                        "label": "Intake analysis",
                        "detail": (
                            "Evidence was received but intake analysis has not run, so "
                            "remaining questions are not yet visible. Open your "
                            "invitation link to continue."
                        ),
                    }
                )
            return "awaiting_submission", items
        covered = {
            item.requirement_id
            for item in self._list("coverage", CoverageItem)
            if item.submission_id == submission.submission_id
        }
        answered = {key for key, value in submission.answers.items() if value.strip()}
        items = []
        for profile in self.profiles.active_profiles():
            for criterion in profile.criteria:
                if criterion.requirement_id in covered or criterion.requirement_id in answered:
                    continue
                items.append(
                    {
                        "requirement_id": criterion.requirement_id,
                        "label": ", ".join(criterion.expected_evidence) or criterion.requirement_id,
                        "detail": criterion.remediation_guidance or criterion.question,
                    }
                )
        items.sort(key=lambda item: item["requirement_id"] or "")
        return "questions_open", items

    # Immutable run versions --------------------------------------------------

    def create_review_run(self, case_id: str, instructions: str | None = None) -> ReviewRun:
        case = self._require("case", case_id, VendorCase)
        submissions = [
            item
            for item in self._list("submission", Submission)
            if item.case_id == case_id and item.status is SubmissionStatus.FINALIZED
        ]
        if not submissions:
            raise VendorBackendError("submission_required", "finalized submission required", status=409)
        submission = max(submissions, key=lambda item: item.version)
        active = self.profiles.active_profiles()
        if not active:
            raise VendorBackendError("profiles_required", "active review profiles required", status=409)
        previous_id = self.repository.get_current_run_id(case_id, workspace_id=self.workspace_id)
        previous = (
            self._require("run", previous_id, ReviewRun) if previous_id is not None else None
        )
        # Demo cases allow the initial run plus reruns after vendor resubmission.
        if previous is not None and previous.run_version >= self.MAX_RUN_VERSION:
            raise VendorBackendError(
                "rerun_limit_reached",
                "review rerun limit reached for this case",
                status=409,
            )
        clean_instructions: str | None = None
        if instructions is not None:
            clean_instructions = self._text(instructions, "instructions")
        version = 1 if previous is None else previous.run_version + 1
        unresolved = tuple(item["requirement_id"] for item in self._questions_for_submission(submission))
        run = ReviewRun(
            run_id=f"run-{case_id}-{version:03d}",
            case_id=case_id,
            run_version=version,
            approval_scope=ApprovalScope(
                product_id=case.product_id,
                use_case=case.use_case,
                scope=case.scope,
                submission_version=submission.version,
                profile_version_ids=tuple(profile.profile_version_id for profile in active),
            ),
            submission_id=submission.submission_id,
            created_at=self._now(),
            unresolved_requirement_ids=unresolved,
            previous_run_id=previous.run_id if previous else None,
            decision_valid=False,
            write_preview_valid=False,
            instructions=clean_instructions,
            workspace_id=self.workspace_id,
        )
        self._put("run", run.run_id, run)
        self.repository.set_current_run(case_id, run.run_id, workspace_id=self.workspace_id)
        self._put("case", case.case_id, replace(case, lifecycle=CaseLifecycle.ANALYZING))
        self._event(
            "review.rerun_created" if previous else "review.run_created",
            "run",
            run.run_id,
            case_id=case_id,
            detail={
                "run_version": version,
                "stale_decision_invalidated": previous is not None,
                "has_instructions": clean_instructions is not None,
            },
        )
        return run

    def list_review_runs(self, case_id: str) -> list[ReviewRun]:
        return [run for run in self._list("run", ReviewRun) if run.case_id == case_id]

    # Catalog -----------------------------------------------------------------

    def put_catalog_entries(self, entries: list[SoftwareCatalogEntry]) -> None:
        for entry in entries:
            if entry.workspace_id != self.workspace_id:
                raise VendorBackendError("workspace_mismatch", "catalog workspace mismatch")
            self._put("catalog", entry.record_id, entry)

    def search_catalog(self, query: str, vendor: str | None = None) -> dict[str, Any]:
        query_text = self._text(query, "query")
        norm = self._normalize(query_text)
        vendor_norm = self._normalize(vendor) if vendor else None
        entries = self._list("catalog", SoftwareCatalogEntry)
        results: list[dict[str, Any]] = []
        for entry in entries:
            method: str | None = None
            score = 0.0
            if self._normalize(entry.canonical_name) == norm:
                method, score = "exact", 1.0
            elif norm in {self._normalize(value) for value in entry.aliases if value}:
                method, score = "alias", 0.98
            elif vendor_norm and self._normalize(entry.vendor) == vendor_norm and norm in self._normalize(entry.canonical_name):
                method, score = "vendor_product", 0.9
            else:
                ratio = SequenceMatcher(None, norm, self._normalize(entry.canonical_name)).ratio()
                if ratio >= 0.82:
                    method, score = "fuzzy", ratio
            if method is None:
                continue
            result = entry.to_dict()
            result.update(
                {
                    "match_method": method,
                    "score": round(score, 4),
                    "requires_human_confirmation": method in {"fuzzy", "semantic"},
                }
            )
            results.append(result)
        results.sort(key=lambda item: (-item["score"], item["source_row"]))
        return {
            "matches": results,
            "semantic_disclosure": "semantic search unavailable in deterministic local mode",
            "catalog_membership_is_approval": False,
        }

    def list_catalog(
        self, *, query: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Paginated catalog listing for the Vendors page.

        Unlike :meth:`search_catalog` (which requires a non-empty query and only
        returns scored matches), this lists **all** rows so the frontend can page
        through the full imported catalog. An optional ``query`` filters by a
        case-insensitive substring across canonical name, vendor, and aliases.
        Every original catalog field is preserved; catalog membership is never
        treated as approval.
        """
        if limit < 1 or limit > 500:
            raise VendorBackendError("invalid_limit", "limit must be between 1 and 500")
        if offset < 0:
            raise VendorBackendError("invalid_offset", "offset must be non-negative")
        entries = self._list("catalog", SoftwareCatalogEntry)
        if query:
            needle = query.strip().lower()
            if needle:
                def matches(entry: SoftwareCatalogEntry) -> bool:
                    haystack = [entry.canonical_name.lower(), entry.vendor.lower()]
                    haystack.extend(alias.lower() for alias in entry.aliases if alias)
                    if entry.short_name:
                        haystack.append(entry.short_name.lower())
                    return any(needle in value for value in haystack)

                entries = [entry for entry in entries if matches(entry)]
        entries.sort(key=lambda entry: (entry.source_row, entry.record_id))
        total = len(entries)
        window = entries[offset : offset + limit]
        return {
            "items": [entry.to_dict() for entry in window],
            "total": total,
            "limit": limit,
            "offset": offset,
            "catalog_membership_is_approval": False,
        }

    def confirm_catalog_match(
        self, record_id: str, match_method: str, reviewer_id: str
    ) -> dict[str, Any]:
        entry = self._require("catalog", record_id, SoftwareCatalogEntry)
        if match_method not in {"exact", "alias", "vendor_product", "fuzzy", "semantic"}:
            raise VendorBackendError("invalid_match_method", "match method is invalid")
        reviewer = self._text(reviewer_id, "reviewer_id")
        event = self._event(
            "catalog.match_confirmed",
            "catalog",
            entry.record_id,
            detail={"match_method": match_method, "reviewer_id": reviewer},
        )
        return {
            "record_id": entry.record_id,
            "match_method": match_method,
            "confirmed": True,
            "confirmed_by": reviewer,
            "event_id": event.event_id,
            "approval_granted": False,
        }

    # Evidence policy criteria (issue #52) ------------------------------------

    def get_policy_criteria(self) -> PolicyCriteria:
        """Active reviewer-editable evidence-validation criteria.

        The highest persisted version is authoritative; before any edit the
        provisional, non-authoritative default applies (issue #52 stays open
        until CSUB confirms these values).
        """
        versions = self._list("policy_criteria", PolicyCriteria)
        if not versions:
            return PolicyCriteria.default(workspace_id=self.workspace_id)
        return max(versions, key=lambda item: item.version)

    def update_policy_criteria(
        self,
        *,
        updated_by: str,
        pentest_max_age_days: int | None,
        pci_attestation_max_age_days: int | None,
        coi_required_coverages: tuple[str, ...],
        evidence_expiry_days: int | None,
        provisional: bool = True,
    ) -> PolicyCriteria:
        """Record a new immutable criteria version with reviewer attribution.

        Thresholds are validated positive-or-None (``None`` means "no confirmed
        rule", which downstream validation treats as manual review rather than
        an invented pass/fail). Every change is auditable.
        """
        current = self.get_policy_criteria()
        version = current.version + 1
        coverages = tuple(
            dict.fromkeys(
                self._text(item, "coi_required_coverages").lower()
                for item in coi_required_coverages
            )
        )
        criteria = PolicyCriteria(
            criteria_version_id=f"policy-criteria-{self.workspace_id}-{version:03d}",
            version=version,
            updated_at=self._now(),
            updated_by=self._text(updated_by, "updated_by"),
            pentest_max_age_days=self._positive_or_none(pentest_max_age_days, "pentest_max_age_days"),
            pci_attestation_max_age_days=self._positive_or_none(
                pci_attestation_max_age_days, "pci_attestation_max_age_days"
            ),
            coi_required_coverages=coverages,
            evidence_expiry_days=self._positive_or_none(evidence_expiry_days, "evidence_expiry_days"),
            provisional=provisional,
            workspace_id=self.workspace_id,
        )
        self._put("policy_criteria", criteria.criteria_version_id, criteria)
        self._event(
            "policy.criteria_updated",
            "policy_criteria",
            criteria.criteria_version_id,
            detail={
                "version": version,
                "provisional": provisional,
                "updated_by": criteria.updated_by,
            },
        )
        return criteria

    @staticmethod
    def _positive_or_none(value: int | None, field_name: str) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise VendorBackendError(
                "invalid_policy_criteria", f"{field_name} must be a positive integer or null"
            )
        return value

    # Internal helpers --------------------------------------------------------

    def _save_progress(self, invite: VendorInvite, submission: Submission) -> None:
        self._put("submission", submission.submission_id, submission)
        if invite.status in {InviteStatus.ISSUED, InviteStatus.OPENED}:
            self._put("invite", invite.invite_id, replace(invite, status=InviteStatus.IN_PROGRESS))
        case = self._require("case", invite.case_id, VendorCase)
        if case.lifecycle is not CaseLifecycle.CHANGES_REQUESTED:
            self._put("case", case.case_id, replace(case, lifecycle=CaseLifecycle.IN_PROGRESS))

    @staticmethod
    def _vendor_review_projection(case: VendorCase) -> dict[str, Any] | None:
        if case.lifecycle is not CaseLifecycle.CHANGES_REQUESTED:
            return None
        return {
            "review_stage": "changes_requested",
            "comment": case.vendor_visible_comment,
            "next_actions": list(case.vendor_next_actions),
        }

    def _valid_invite(self, token: str) -> VendorInvite:
        if not isinstance(token, str) or not token:
            raise VendorBackendError("invalid_invite", "invitation is invalid", status=404)
        invite = self.repository.find_invite_by_token_hash(
            self._hash_token(token), workspace_id=self.workspace_id
        )
        if invite is None:
            raise VendorBackendError("invalid_invite", "invitation is invalid", status=404)
        invite = self._expire_invite_if_needed(invite)
        if invite.status is InviteStatus.REVOKED:
            raise VendorBackendError("invite_revoked", "invitation was revoked", status=410)
        if invite.status is InviteStatus.EXPIRED:
            raise VendorBackendError("invite_expired", "invitation expired", status=410)
        if invite.status is InviteStatus.SUBMITTED:
            raise VendorBackendError("invite_submitted", "invitation was already submitted", status=409)
        return invite

    def _draft_submission(self, invite: VendorInvite) -> Submission:
        submission = self._submission_for_invite(invite.invite_id)
        if submission.status is not SubmissionStatus.DRAFT:
            raise VendorBackendError("submission_finalized", "submission is immutable", status=409)
        return submission

    def _submission_for_invite(self, invite_id: str) -> Submission:
        matches = [
            item
            for item in self._list("submission", Submission)
            if item.invite_id == invite_id
        ]
        if len(matches) != 1:
            raise VendorBackendError("submission_not_found", "submission not found", status=404)
        return matches[0]

    def _criterion(self, requirement_id: str):
        for profile in self.profiles.active_profiles():
            for criterion in profile.criteria:
                if criterion.requirement_id == requirement_id:
                    return criterion, profile
        raise VendorBackendError(
            "invalid_requirement", "requirement is not part of an active profile"
        )

    def _questions_for_submission(self, submission: Submission) -> list[dict[str, Any]]:
        covered = {
            item.requirement_id
            for item in self._list("coverage", CoverageItem)
            if item.submission_id == submission.submission_id
        }
        answered = {key for key, value in submission.answers.items() if value.strip()}
        questions = []
        for profile in self.profiles.active_profiles():
            for criterion in profile.criteria:
                if criterion.requirement_id not in covered | answered:
                    questions.append({"requirement_id": criterion.requirement_id})
        return sorted(questions, key=lambda item: item["requirement_id"])

    def _event(
        self,
        event_type: str,
        resource_type: str,
        resource_id: str,
        *,
        case_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> IntegrationEvent:
        event = IntegrationEvent(
            event_id=self._id("event", "event"),
            event_type=event_type,
            occurred_at=self._now(),
            resource_type=resource_type,
            resource_id=resource_id,
            case_id=case_id,
            detail=dict(detail or {}),
            workspace_id=self.workspace_id,
        )
        self._put("event", event.event_id, event)
        return event

    def _require(self, kind: str, record_id: str | None, expected_type):
        if record_id is None:
            raise VendorBackendError("not_found", f"{kind} not found", status=404)
        value = self.repository.get(kind, record_id, workspace_id=self.workspace_id)
        if not isinstance(value, expected_type):
            raise VendorBackendError("not_found", f"{kind} not found", status=404)
        return value

    def _list(self, kind: str, expected_type):
        return [
            item
            for item in self.repository.list(kind, workspace_id=self.workspace_id)
            if isinstance(item, expected_type)
        ]

    def _put(self, kind: str, record_id: str, value: object) -> None:
        self.repository.put(kind, record_id, value, workspace_id=self.workspace_id)

    def _id(self, kind: str, prefix: str) -> str:
        return f"{prefix}-{len(self.repository.list(kind, workspace_id=self.workspace_id)) + 1:04d}"

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize(value: str | None) -> str:
        return _NORMALIZE.sub("", (value or "").lower())

    @staticmethod
    def _text(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise VendorBackendError("validation_error", f"{field_name} is required")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise VendorBackendError("validation_error", f"{field_name} contains control characters")
        return value.strip()

    @staticmethod
    def _reject_extra(payload: object, allowed: set[str], *, required: bool = False) -> None:
        if not isinstance(payload, dict):
            raise VendorBackendError("validation_error", "payload must be an object")
        if set(payload) - allowed:
            raise VendorBackendError("validation_error", "payload contains unsupported fields")
        if required and set(payload) != allowed:
            raise VendorBackendError("validation_error", "payload fields do not match the contract")

    @classmethod
    def _public_hostname(cls, hostname: str | None) -> str:
        value = cls._text(hostname, "official_domain").lower().rstrip(".")
        if ":" in value or "/" in value or value == "localhost" or "." not in value:
            raise VendorBackendError("invalid_hostname", "hostname must be a public DNS name")
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            address = None
        if address is not None or value.endswith((".local", ".internal", ".localhost")):
            raise VendorBackendError("invalid_hostname", "hostname must be a public DNS name")
        labels = value.split(".")
        if any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not all(char.isalnum() or char == "-" for char in label)
            for label in labels
        ):
            raise VendorBackendError("invalid_hostname", "hostname must be a public DNS name")
        return value

    @classmethod
    def _trust_url(cls, url: str) -> str:
        value = cls._text(url, "trust_center_url")
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise VendorBackendError("invalid_trust_url", "trust-center URL must use HTTPS")
        try:
            port = parsed.port
        except ValueError as error:
            raise VendorBackendError(
                "invalid_trust_url", "trust-center URL has an invalid port"
            ) from error
        if port not in (None, 443):
            raise VendorBackendError("invalid_trust_url", "trust-center URL must use the HTTPS port")
        cls._public_hostname(parsed.hostname)
        return value

    def _now_datetime(self) -> datetime.datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise VendorBackendError("invalid_clock", "clock must be timezone-aware")
        return value.astimezone(datetime.timezone.utc)

    def _now(self) -> str:
        return self._now_datetime().isoformat()
