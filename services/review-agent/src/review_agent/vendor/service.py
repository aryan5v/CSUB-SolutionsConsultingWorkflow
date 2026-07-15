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
from typing import Any, Callable
from urllib.parse import quote, urlsplit

from ..adapters.extraction import DeterministicEvidenceExtractor, EvidenceExtractor
from ..adapters.storage import StorageClient
from ..contracts.vendor import (
    DEFAULT_WORKSPACE_ID,
    ApprovalScope,
    CaseLifecycle,
    CoverageItem,
    EvidenceArtifact,
    EvidenceExpiryRecord,
    EvidenceValidationFinding,
    IntegrationEvent,
    RenewalRecord,
    InviteStatus,
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
from ..evidence.validation import (
    EXPIRY_RULE_SOURCE,
    RULE_SOURCE,
    classify_evidence_type,
    compute_expires_on,
    validate_evidence,
    validate_identity,
)
from ..profiles.service import ProfileError, ReviewProfileService
from .repository import VendorRepository

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")
_NORMALIZE = re.compile(r"[^a-z0-9]+")
_NORMALIZE_TOKENS = re.compile(r"[^a-z0-9]+")


class VendorBackendError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class VendorBackend:
    MAX_RUN_VERSION = 2

    def __init__(
        self,
        repository: VendorRepository,
        profiles: ReviewProfileService,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        clock: Callable[[], datetime.datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
        invite_ttl: datetime.timedelta = datetime.timedelta(days=7),
        reminder_interval: datetime.timedelta = datetime.timedelta(days=7),
        evidence_storage: StorageClient | None = None,
        extractor: EvidenceExtractor | None = None,
        expiry_lead_days: tuple[int, ...] = (60, 30, 7),
        intake_base_url: str = "https://vetted.invalid/intake",
        link_secret: bytes | None = None,
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
        self.reminder_interval = reminder_interval
        # Evidence bytes are optional: small files arrive inline with the
        # metadata (content_base64) and are stored for content validation;
        # files above the inline cap still register metadata only and skip
        # content validation (documented limitation until presigned uploads).
        self._evidence_storage = evidence_storage
        self._extractor = extractor or DeterministicEvidenceExtractor()
        if not expiry_lead_days or any(days <= 0 for days in expiry_lead_days):
            raise ValueError("expiry_lead_days must be positive")
        self.expiry_lead_days = tuple(sorted(set(expiry_lead_days)))
        self.intake_base_url = intake_base_url.rstrip("/#")
        # Keyed secret for sealing invite tokens so reminder emails can repeat
        # the vendor's intake link without ever persisting a raw token. When
        # not configured, a per-process secret is generated: links stay
        # available for the process lifetime and reminders degrade gracefully
        # (no link, generic copy) after a restart.
        self._link_secret = link_secret or secrets.token_bytes(32)

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

    def issue_invite(self, case_id: str, contact_id: str) -> dict[str, Any]:
        case = self._require("case", case_id, VendorCase)
        contact = self._require("contact", contact_id, VendorContact)
        product = self._require("product", case.product_id, VendorProduct)
        if contact.vendor_id != product.vendor_id:
            raise VendorBackendError(
                "contact_product_mismatch", "contact and product must belong to the same vendor"
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
        old = self._require("invite", invite_id, VendorInvite)
        if old.status is InviteStatus.SUBMITTED:
            raise VendorBackendError("already_submitted", "submitted invitation cannot be resent", status=409)
        now = self._now()
        self._put(
            "invite",
            old.invite_id,
            replace(old, status=InviteStatus.REVOKED, revoked_at=now),
        )
        issued = self.issue_invite(old.case_id, old.contact_id)
        replacement = self._require(
            "invite", issued["invite"]["invite_id"], VendorInvite
        )
        replacement = replace(replacement, replaced_invite_id=old.invite_id)
        self._put("invite", replacement.invite_id, replacement)
        issued["invite"] = replacement.to_reviewer_dict()
        self._event("invite.resent", "invite", replacement.invite_id, case_id=old.case_id)
        return issued

    def revoke_invite(self, invite_id: str) -> dict[str, Any]:
        invite = self._require("invite", invite_id, VendorInvite)
        if invite.status is InviteStatus.SUBMITTED:
            raise VendorBackendError("already_submitted", "submitted invitation cannot be revoked", status=409)
        revoked = replace(invite, status=InviteStatus.REVOKED, revoked_at=self._now())
        self._put("invite", invite_id, revoked)
        self._event("invite.revoked", "invite", invite_id, case_id=invite.case_id)
        return revoked.to_reviewer_dict()

    def list_invites(self, case_id: str | None = None) -> list[VendorInvite]:
        invites = self._list("invite", VendorInvite)
        return [invite for invite in invites if case_id is None or invite.case_id == case_id]

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
        return {
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
        size = payload.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= 50_000_000:
            raise VendorBackendError("invalid_size", "size_bytes must be between 0 and 50000000")
        digest = self._text(payload.get("sha256"), "sha256").lower()
        if not _SHA256.fullmatch(digest):
            raise VendorBackendError("invalid_hash", "sha256 must be 64 hexadecimal characters")
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
        expires = datetime.datetime.fromisoformat(invite.expires_at)
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
        # Content validation (issue #36): a COI/pentest/PCI document that fails
        # its deterministic checks produces cited findings and must not count
        # as received, so its artifact is excluded from auto-coverage below.
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
        host = urlsplit(submission.trust_center_url).hostname or "unknown"
        research_summary = (
            f"Reviewed trust-center host {host}; inventoried {len(evidence)} evidence "
            f"artifact(s); auto-covered {len(auto_covered)} requirement(s) by deterministic "
            f"extraction; recorded {len(findings)} content-validation finding(s)."
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
                "simulated": True,
            },
        )
        return finished

    def _validate_evidence_contents(
        self, submission: Submission, evidence: list[EvidenceArtifact]
    ) -> list[EvidenceValidationFinding]:
        """Extract and check COI/pentest/PCI fields; persist and return failures.

        Extraction is a swappable adapter (deterministic locally, model on AWS)
        but every pass/fail decision is made by ``evidence.validation``'s pure
        rules. Artifacts whose bytes never reached the evidence store are
        skipped: with nothing to read there is nothing to validate.
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
            text = self._evidence_text(artifact)
            if text is None:
                continue
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
            if evidence_type is not None:
                failures.extend(
                    validate_evidence(evidence_type=evidence_type, fields=fields, today=today)
                )
            for failure in failures:
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
                        **RULE_SOURCE,
                        "filename": artifact.filename,
                        "sha256": artifact.sha256,
                    },
                    workspace_id=self.workspace_id,
                )
                self._put("finding", finding.finding_id, finding)
                findings.append(finding)
            if not failures and evidence_type is not None:
                self._record_expiry(submission, artifact, evidence_type, fields)
        return findings

    def _record_expiry(
        self,
        submission: Submission,
        artifact: EvidenceArtifact,
        evidence_type: str,
        fields: dict[str, Any],
    ) -> None:
        """Persist when a validated time-bound document stops being current (issue #53).

        Next-check dates come only from validated fields (issue #36 cited rules);
        a document with no validated date produced findings instead and is never
        monitored. The record captures the approval context — scope, owner,
        contact, and the profile/policy + evidence versions — so a later sweep
        can act on the expiry without re-deriving it (issue #53).
        """
        expires_on = compute_expires_on(evidence_type, fields)
        if expires_on is None:
            return
        for existing in self._list("expiry", EvidenceExpiryRecord):
            if (
                existing.submission_id == submission.submission_id
                and existing.artifact_id == artifact.artifact_id
            ):
                return
        approval_scope, contact_id, owner, profile_version_ids = self._approval_context(submission)
        record = EvidenceExpiryRecord(
            expiry_id=self._id("expiry", "expiry"),
            case_id=submission.case_id,
            submission_id=submission.submission_id,
            artifact_id=artifact.artifact_id,
            filename=artifact.filename,
            evidence_type=evidence_type,
            expires_on=expires_on.isoformat(),
            source_citation={
                **EXPIRY_RULE_SOURCE,
                "filename": artifact.filename,
                "sha256": artifact.sha256,
            },
            approval_scope=approval_scope,
            owner=owner,
            contact_id=contact_id,
            profile_version_ids=profile_version_ids,
            evidence_version=artifact.sha256,
            state="active",
            workspace_id=self.workspace_id,
        )
        self._put("expiry", record.expiry_id, record)
        # Keep explicit active/superseded state on the chain in sync (issue #53).
        self._resync_expiry_states(evidence_type, self._chain_case_ids(submission.case_id))
        # Recording refreshed evidence on a renewal case completes that open
        # renewal (issue #53 lifecycle): its job — collecting the replacement —
        # is done, so it no longer blocks a future renewal if this evidence
        # later expires again.
        self._complete_renewal_for_case(submission.case_id)

    def _approval_context(
        self, submission: Submission
    ) -> tuple[dict[str, Any], str | None, str | None, tuple[str, ...]]:
        """Approval scope, vendor contact, owner, and profile/policy versions.

        The scope mirrors :class:`ApprovalScope` (product, use case, scope,
        submission version, active profile versions). ``owner`` is the campus
        owner of the approval when tracked (TBD in the prototype); ``contact_id``
        is the vendor contact from the case's authoritative invite.
        """
        profile_version_ids = tuple(
            profile.profile_version_id for profile in self.profiles.active_profiles()
        )
        case = self.repository.get("case", submission.case_id, workspace_id=self.workspace_id)
        use_case = case.use_case if isinstance(case, VendorCase) else ""
        scope_text = case.scope if isinstance(case, VendorCase) else ""
        approval_scope = ApprovalScope(
            product_id=submission.product_id,
            use_case=use_case,
            scope=scope_text,
            submission_version=submission.version,
            profile_version_ids=profile_version_ids,
        ).to_dict()
        contact_id = None
        invites = [
            invite
            for invite in self.list_invites(submission.case_id)
            if invite.status is not InviteStatus.REVOKED
        ]
        if invites:
            contact_id = max(invites, key=lambda item: item.issued_at).contact_id
        return approval_scope, contact_id, None, profile_version_ids

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

    def _evidence_text(self, artifact: EvidenceArtifact) -> str | None:
        if self._evidence_storage is None:
            return None
        key = f"evidence/{artifact.sha256}"
        if not self._evidence_storage.exists(key=key):
            return None
        return self._evidence_storage.get_object(key=key).decode("utf-8", errors="replace")

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
            {CaseLifecycle.NEEDS_REVIEW, CaseLifecycle.ANALYZING, CaseLifecycle.CHANGES_REQUESTED}
        ),
        CaseLifecycle.DECLINED: frozenset(
            {CaseLifecycle.NEEDS_REVIEW, CaseLifecycle.ANALYZING, CaseLifecycle.CHANGES_REQUESTED,
             CaseLifecycle.DECLINED}
        ),
        CaseLifecycle.WRITEBACK_COMPLETE: frozenset(
            {CaseLifecycle.APPROVED, CaseLifecycle.WRITEBACK_COMPLETE}
        ),
    }

    def transition_case(self, case_id: str, target: CaseLifecycle) -> VendorCase:
        """Persist a reviewer/analysis lifecycle transition (issue #27).

        Idempotent (target == current is a no-op) and validated against the
        documented forward transition map. Emits an integration event so the
        state change is auditable and observable in the demo.
        """
        case = self.repository.get("case", case_id, workspace_id=self.workspace_id)
        if not isinstance(case, VendorCase):
            # A case that was never registered as a vendor case has no lifecycle
            # to persist; callers treat this as a benign no-op.
            return None  # type: ignore[return-value]
        if case.lifecycle is target:
            return case
        allowed = self._ALLOWED_TRANSITIONS.get(target)
        if allowed is None or case.lifecycle not in allowed:
            raise VendorBackendError(
                "invalid_transition",
                f"cannot move case from {case.lifecycle.value} to {target.value}",
                status=409,
            )
        updated = replace(case, lifecycle=target)
        self._put("case", case_id, updated)
        self._event(
            "case.transitioned",
            "case",
            case_id,
            case_id=case_id,
            detail={"from": case.lifecycle.value, "to": target.value},
        )
        return updated

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
            if now >= datetime.datetime.fromisoformat(invite.expires_at):
                continue
            current = authoritative.get(invite.case_id)
            if current is None or (invite.issued_at, invite.invite_id) > (
                current.issued_at,
                current.invite_id,
            ):
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
            claim = self.repository.get(
                "reminder_claim", dedupe_key, workspace_id=self.workspace_id
            )
            if isinstance(claim, ReminderClaim) and (
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

    def claim_reminder(self, *, dedupe_key: str, case_id: str, invite_id: str) -> bool:
        """Claim one cadence period for one case before any email is sent.

        Returns False when the period is already claimed (pending or sent) or
        its failed attempts are exhausted, so a concurrent or retried sweep
        never duplicates a send. The claim is persisted as a whole record keyed
        by the deterministic dedupe key; a DynamoDB adapter makes this write a
        conditional put.
        """
        existing = self.repository.get(
            "reminder_claim", dedupe_key, workspace_id=self.workspace_id
        )
        attempts = 0
        if isinstance(existing, ReminderClaim):
            if existing.status != "failed" or existing.attempts >= self.MAX_REMINDER_ATTEMPTS:
                return False
            attempts = existing.attempts
        claim = ReminderClaim(
            dedupe_key=dedupe_key,
            case_id=case_id,
            invite_id=invite_id,
            status="pending",
            attempts=attempts + 1,
            claimed_at=self._now(),
            workspace_id=self.workspace_id,
        )
        self._put("reminder_claim", dedupe_key, claim)
        return True

    def record_reminder(
        self,
        *,
        invite_id: str,
        case_id: str,
        dedupe_key: str,
        summary: str,
        delivery: dict[str, Any],
    ) -> IntegrationEvent:
        """Persist one reminder attempt with its truthful delivery result.

        A failed delivery marks the claim ``failed`` so the next sweep retries
        (bounded by :attr:`MAX_REMINDER_ATTEMPTS`) instead of treating the
        failure as cadence satisfaction; a delivered send marks it ``sent``,
        suppressing further reminders for the period. Every attempt is recorded
        as an auditable event; the recipient is stored as a SHA-256 digest,
        never as a raw address.
        """
        claim = self.repository.get(
            "reminder_claim", dedupe_key, workspace_id=self.workspace_id
        )
        if isinstance(claim, ReminderClaim):
            outcome = "failed" if delivery.get("delivery") == "failed" else "sent"
            self._put("reminder_claim", dedupe_key, replace(claim, status=outcome))
        detail = {
            "summary": summary,
            "delivery": delivery.get("delivery"),
            "simulated": delivery.get("simulated", True),
            "channel": delivery.get("channel"),
            "dedupe_key": dedupe_key,
        }
        if delivery.get("to"):
            detail["recipient_sha256"] = self._hash_recipient(str(delivery["to"]))
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
        issued = datetime.datetime.fromisoformat(invite.issued_at)
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

    # Post-approval expiry monitoring (issue #53) -------------------------------

    _EXPIRY_EVENT = "evidence.expiry_notice"
    # A failed delivery is retried on later sweeps, but never unboundedly
    # (mirrors the reminder cadence in issue #37).
    MAX_EXPIRY_ATTEMPTS = 3
    # Only decided-and-approved cases are monitored; historical approvals are
    # never mutated by monitoring, only projected as current/expiring/expired.
    _MONITORED_LIFECYCLES = frozenset(
        {CaseLifecycle.APPROVED, CaseLifecycle.WRITEBACK_COMPLETE}
    )

    def expiry_status(self) -> list[dict[str, Any]]:
        """Per approved case and evidence type: the latest validated expiry.

        Renewal cases roll up into their source case's chain, so replacement
        evidence recomputes the next date (superseding the old record) without
        touching the historical approval. States: ``current`` (beyond every
        lead time), ``expiring`` (within the largest lead time), ``expired``.
        ``renewal_case_id`` is the currently *open* renewal for the chain (issue
        #53 lifecycle) — a completed/superseded/closed renewal no longer blocks
        opening a new one.
        """
        today = self._now_datetime().date()
        renewals = self._list("renewal", RenewalRecord)
        renewals_by_source: dict[str, list[RenewalRecord]] = {}
        for renewal in renewals:
            renewals_by_source.setdefault(renewal.source_case_id, []).append(renewal)
        renewal_case_ids = {renewal.renewal_case_id for renewal in renewals}
        expiry_records = self._list("expiry", EvidenceExpiryRecord)
        items: list[dict[str, Any]] = []
        for case in self._list("case", VendorCase):
            if case.lifecycle not in self._MONITORED_LIFECYCLES:
                continue
            if case.case_id in renewal_case_ids:
                # A renewal case reports through its source case's chain.
                continue
            chain = {case.case_id} | {
                renewal.renewal_case_id
                for renewal in renewals_by_source.get(case.case_id, [])
            }
            records = [record for record in expiry_records if record.case_id in chain]
            latest: dict[str, EvidenceExpiryRecord] = {}
            for record in records:
                current = latest.get(record.evidence_type)
                if current is None or record.expires_on > current.expires_on:
                    latest[record.evidence_type] = record
            open_renewals = [
                renewal
                for renewal in renewals_by_source.get(case.case_id, [])
                if renewal.state == "open"
            ]
            renewal_case_id = (
                max(open_renewals, key=lambda item: item.sequence).renewal_case_id
                if open_renewals
                else None
            )
            product = self._require("product", case.product_id, VendorProduct)
            for evidence_type in sorted(latest):
                record = latest[evidence_type]
                expires = datetime.date.fromisoformat(record.expires_on)
                days = (expires - today).days
                if days < 0:
                    state = "expired"
                elif days <= max(self.expiry_lead_days):
                    state = "expiring"
                else:
                    state = "current"
                items.append(
                    {
                        "case_id": case.case_id,
                        "product_name": product.name,
                        "expiry_id": record.expiry_id,
                        "artifact_id": record.artifact_id,
                        "filename": record.filename,
                        "evidence_type": evidence_type,
                        "expires_on": record.expires_on,
                        "days_until_expiry": days,
                        "state": state,
                        "record_state": record.state,
                        "approval_scope": dict(record.approval_scope),
                        "profile_version_ids": list(record.profile_version_ids),
                        "owner": record.owner,
                        "contact_id": record.contact_id,
                        "evidence_version": record.evidence_version,
                        "renewal_case_id": renewal_case_id,
                        "superseded_expiry_ids": sorted(
                            item.expiry_id
                            for item in records
                            if item.evidence_type == evidence_type
                            and item.expiry_id != record.expiry_id
                        ),
                    }
                )
        return sorted(items, key=lambda item: (item["case_id"], item["evidence_type"]))

    def expiry_actions(self) -> list[dict[str, Any]]:
        """Due monitoring actions: lead-time notices, expired notices, and scoped
        renewal-case openings, deduplicated by *satisfied* claims only.

        Each (expiry record, threshold) pair and each renewal opening is guarded
        by a persisted claim (issue #37 ``ReminderClaim``, reused): a claim that
        is pending or delivered blocks the action, but a *failed* notice claim
        with attempts remaining does not — so a transient delivery failure is
        retried on the next sweep instead of silently satisfying the cadence
        (finding 2). Only the tightest due lead time fires per sweep. A new
        renewal opens only when no renewal is currently open for the chain
        (finding 3) and no concurrent claim exists (finding 4).
        """
        actions: list[dict[str, Any]] = []
        expired_by_case: dict[str, list[dict[str, Any]]] = {}
        for item in self.expiry_status():
            if item["state"] == "current":
                continue
            contact = self._monitoring_contact(item["case_id"])
            base = {**item, **contact}
            if item["state"] == "expired":
                key = self._expiry_dedupe_key(item["expiry_id"], "expired")
                if not self._notice_claim_blocks(key):
                    actions.append(
                        {"kind": "notice", "threshold": "expired", "dedupe_key": key, **base}
                    )
                if item["renewal_case_id"] is None:
                    expired_by_case.setdefault(item["case_id"], []).append(item)
                continue
            for lead in self.expiry_lead_days:
                if item["days_until_expiry"] <= lead:
                    key = self._expiry_dedupe_key(item["expiry_id"], str(lead))
                    if not self._notice_claim_blocks(key):
                        actions.append(
                            {"kind": "notice", "threshold": lead, "dedupe_key": key, **base}
                        )
                    break
        for case_id, expired_items in sorted(expired_by_case.items()):
            if self._has_open_renewal(case_id):
                continue
            sequence = self._next_renewal_sequence(case_id)
            renewal_key = self._renewal_dedupe_key(case_id, sequence)
            if self._renewal_claim_blocks(renewal_key):
                continue
            actions.append(
                {
                    "kind": "open_renewal",
                    "case_id": case_id,
                    "product_name": expired_items[0]["product_name"],
                    "renewal_case_id": f"{case_id}-R{sequence:02d}",
                    "renewal_sequence": sequence,
                    "renewal_dedupe_key": renewal_key,
                    "expired_evidence_types": sorted(
                        {item["evidence_type"] for item in expired_items}
                    ),
                    **self._monitoring_contact(case_id),
                }
            )
        return actions

    # --- Claim-before-side-effect (issue #37 ReminderClaim pattern, reused) ---
    #
    # Notices and renewal openings persist a claim *before* the side effect so a
    # concurrent or retried sweep never double-sends or double-opens (finding 4).
    # A DynamoDB adapter maps each claim write to a conditional put; the whole
    # record is replaced (never a partial ledger overwrite), and every sweep
    # reloads the latest snapshot so persisted claims dedup across invocations.

    @staticmethod
    def _expiry_dedupe_key(expiry_id: str, threshold: str) -> str:
        return f"expiry:{expiry_id}:{threshold}"

    @staticmethod
    def _renewal_dedupe_key(source_case_id: str, sequence: int) -> str:
        return f"renewal-open:{source_case_id}:{sequence}"

    def _notice_claim_blocks(self, dedupe_key: str) -> bool:
        claim = self.repository.get(
            "reminder_claim", dedupe_key, workspace_id=self.workspace_id
        )
        if not isinstance(claim, ReminderClaim):
            return False
        if claim.status == "failed":
            return claim.attempts >= self.MAX_EXPIRY_ATTEMPTS
        # pending or sent: a live claim blocks re-sending.
        return True

    def _renewal_claim_blocks(self, dedupe_key: str) -> bool:
        claim = self.repository.get(
            "reminder_claim", dedupe_key, workspace_id=self.workspace_id
        )
        return isinstance(claim, ReminderClaim)

    def claim_expiry_notice(self, *, dedupe_key: str, case_id: str, expiry_id: str) -> bool:
        """Claim one (expiry, threshold) notice before it is sent.

        Returns False when the notice is already claimed (pending/sent) or its
        failed attempts are exhausted, so a concurrent or retried sweep never
        duplicates a send (finding 2/4).
        """
        existing = self.repository.get(
            "reminder_claim", dedupe_key, workspace_id=self.workspace_id
        )
        attempts = 0
        if isinstance(existing, ReminderClaim):
            if existing.status != "failed" or existing.attempts >= self.MAX_EXPIRY_ATTEMPTS:
                return False
            attempts = existing.attempts
        claim = ReminderClaim(
            dedupe_key=dedupe_key,
            case_id=case_id,
            invite_id=expiry_id,
            status="pending",
            attempts=attempts + 1,
            claimed_at=self._now(),
            workspace_id=self.workspace_id,
        )
        self._put("reminder_claim", dedupe_key, claim)
        return True

    def claim_renewal(self, *, dedupe_key: str, case_id: str) -> bool:
        """Claim opening one scoped renewal case before it is created.

        Renewal openings are one-shot: an existing claim (regardless of status)
        blocks a duplicate open under concurrency/retry (finding 4).
        """
        if self._renewal_claim_blocks(dedupe_key):
            return False
        claim = ReminderClaim(
            dedupe_key=dedupe_key,
            case_id=case_id,
            invite_id=case_id,
            status="sent",
            attempts=1,
            claimed_at=self._now(),
            workspace_id=self.workspace_id,
        )
        self._put("reminder_claim", dedupe_key, claim)
        return True

    def record_expiry_notice(
        self,
        *,
        expiry_id: str,
        case_id: str,
        threshold: str,
        summary: str,
        delivery: dict[str, Any],
        dedupe_key: str | None = None,
    ) -> IntegrationEvent:
        """Persist one expiry notice attempt and settle its claim.

        A failed delivery marks the claim ``failed`` so the next sweep retries
        (bounded by :attr:`MAX_EXPIRY_ATTEMPTS`) instead of treating the failure
        as cadence satisfaction; a delivered send marks it ``sent`` (finding 2).
        The recipient is recorded as a SHA-256 digest, never a raw address.
        """
        if dedupe_key is None:
            dedupe_key = self._expiry_dedupe_key(expiry_id, str(threshold))
        claim = self.repository.get(
            "reminder_claim", dedupe_key, workspace_id=self.workspace_id
        )
        if isinstance(claim, ReminderClaim):
            outcome = "failed" if delivery.get("delivery") == "failed" else "sent"
            self._put("reminder_claim", dedupe_key, replace(claim, status=outcome))
        detail = {
            "expiry_id": expiry_id,
            "threshold": threshold,
            "summary": summary,
            "delivery": delivery.get("delivery"),
            "simulated": delivery.get("simulated", True),
            "channel": delivery.get("channel"),
            "dedupe_key": dedupe_key,
        }
        if delivery.get("to"):
            detail["recipient_sha256"] = self._hash_recipient(str(delivery["to"]))
        return self._event(
            self._EXPIRY_EVENT, "expiry", expiry_id, case_id=case_id, detail=detail
        )

    def record_renewal(
        self,
        *,
        source_case_id: str,
        renewal_case_id: str,
        expired_evidence_types: list[str],
        sequence: int | None = None,
    ) -> RenewalRecord:
        """Link a newly opened scoped re-review case to its source approval.

        Idempotent by ``renewal_case_id``: a retry that computes the same
        deterministic ID finds the existing renewal and returns it unchanged
        (finding 4). ``sequence`` is a collision-free chain index; when omitted
        it is derived as max-existing-sequence + 1, never ``len(existing)+1``
        (finding 5). The renewal carries the approval scope, owner, and the
        active-chain contact so acting on it needs no re-derivation (finding 6).
        """
        for existing in self._list("renewal", RenewalRecord):
            if existing.renewal_case_id == renewal_case_id:
                return existing
        if sequence is None:
            sequence = self._next_renewal_sequence(source_case_id)
        approval_scope, owner = self._source_approval_scope(source_case_id)
        contact_id = self._monitoring_contact(source_case_id).get("contact_id")
        renewal = RenewalRecord(
            renewal_id=self._id("renewal", "renewal"),
            source_case_id=source_case_id,
            renewal_case_id=renewal_case_id,
            expired_evidence_types=tuple(expired_evidence_types),
            opened_at=self._now(),
            sequence=sequence,
            state="open",
            approval_scope=approval_scope,
            owner=owner,
            contact_id=contact_id,
            workspace_id=self.workspace_id,
        )
        # Defensive: any lingering open renewal for this source is superseded by
        # the new one (issue #53 supersession state).
        for prior in self._list("renewal", RenewalRecord):
            if (
                prior.source_case_id == source_case_id
                and prior.state == "open"
                and prior.renewal_id != renewal.renewal_id
            ):
                self._put(
                    "renewal",
                    prior.renewal_id,
                    replace(prior, state="superseded", superseded_by=renewal.renewal_id),
                )
        self._put("renewal", renewal.renewal_id, renewal)
        self._event(
            "renewal.case_opened",
            "renewal",
            renewal.renewal_id,
            case_id=source_case_id,
            detail={
                "renewal_case_id": renewal_case_id,
                "sequence": sequence,
                "expired_evidence_types": list(expired_evidence_types),
            },
        )
        return renewal

    def _next_renewal_sequence(self, source_case_id: str) -> int:
        sequences = [
            renewal.sequence
            for renewal in self._list("renewal", RenewalRecord)
            if renewal.source_case_id == source_case_id
        ]
        return (max(sequences) + 1) if sequences else 1

    def _has_open_renewal(self, source_case_id: str) -> bool:
        return any(
            renewal.source_case_id == source_case_id and renewal.state == "open"
            for renewal in self._list("renewal", RenewalRecord)
        )

    def _complete_renewal_for_case(self, renewal_case_id: str) -> None:
        """Mark the open renewal whose case just received refreshed evidence
        ``completed`` (issue #53 lifecycle): it no longer blocks a future
        renewal if this evidence expires again."""
        for renewal in self._list("renewal", RenewalRecord):
            if renewal.renewal_case_id == renewal_case_id and renewal.state == "open":
                self._put(
                    "renewal",
                    renewal.renewal_id,
                    replace(renewal, state="completed", closed_at=self._now()),
                )

    def _resync_expiry_states(self, evidence_type: str, chain: set[str]) -> None:
        """Persist explicit ``active``/``superseded`` state on chain records
        (issue #53): the latest expiry per evidence type is active, older ones
        are superseded."""
        records = [
            record
            for record in self._list("expiry", EvidenceExpiryRecord)
            if record.case_id in chain and record.evidence_type == evidence_type
        ]
        if not records:
            return
        latest = max(records, key=lambda record: record.expires_on)
        for record in records:
            desired = "active" if record.expiry_id == latest.expiry_id else "superseded"
            if record.state != desired:
                self._put("expiry", record.expiry_id, replace(record, state=desired))

    def _chain_case_ids(self, case_id: str) -> set[str]:
        renewals = self._list("renewal", RenewalRecord)
        source = case_id
        for renewal in renewals:
            if renewal.renewal_case_id == case_id:
                source = renewal.source_case_id
                break
        return {source} | {
            renewal.renewal_case_id
            for renewal in renewals
            if renewal.source_case_id == source
        }

    def _latest_chain_case(self, case_id: str) -> str:
        """The most recent renewal case in the chain (by sequence), else the
        source case itself — the active renewal-chain contact lives here."""
        renewals = self._list("renewal", RenewalRecord)
        source = case_id
        for renewal in renewals:
            if renewal.renewal_case_id == case_id:
                source = renewal.source_case_id
                break
        chain = [renewal for renewal in renewals if renewal.source_case_id == source]
        if not chain:
            return source
        return max(chain, key=lambda renewal: renewal.sequence).renewal_case_id

    def _source_approval_scope(self, source_case_id: str) -> tuple[dict[str, Any], str | None]:
        """Approval scope + owner captured on the source case's latest expiry
        record, so a renewal inherits it without re-derivation (finding 6)."""
        records = [
            record
            for record in self._list("expiry", EvidenceExpiryRecord)
            if record.case_id in self._chain_case_ids(source_case_id)
        ]
        if not records:
            return {}, None
        latest = max(records, key=lambda record: record.expires_on)
        return dict(latest.approval_scope), latest.owner

    def _monitoring_contact(self, case_id: str) -> dict[str, Any]:
        """Vendor contact for expiry notices: the active renewal chain's contact.

        The most recent renewal case's live invite is authoritative; when the
        chain has no renewal (or its invite is missing) this falls back to the
        source case's latest live invite, consistent with #46/#47's
        authoritative-contact rule (finding 5).
        """
        for candidate in (self._latest_chain_case(case_id), case_id):
            invites = [
                invite
                for invite in self.list_invites(candidate)
                if invite.status is not InviteStatus.REVOKED
            ]
            if not invites:
                continue
            invite = max(invites, key=lambda item: item.issued_at)
            try:
                contact = self._require("contact", invite.contact_id, VendorContact)
            except VendorBackendError:
                continue
            return {
                "contact_name": contact.name,
                "contact_email": contact.email,
                "contact_id": contact.contact_id,
            }
        return {"contact_name": None, "contact_email": None, "contact_id": None}


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
        # Exactly one rerun per demo case: run 1 is the initial run, run 2 is the
        # single permitted rerun with custom instructions (issue #27).
        if previous is not None and previous.run_version >= self.MAX_RUN_VERSION:
            raise VendorBackendError(
                "rerun_limit_reached",
                "only one rerun is permitted per demo case",
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

    # Internal helpers --------------------------------------------------------

    def _save_progress(self, invite: VendorInvite, submission: Submission) -> None:
        self._put("submission", submission.submission_id, submission)
        if invite.status in {InviteStatus.ISSUED, InviteStatus.OPENED}:
            self._put("invite", invite.invite_id, replace(invite, status=InviteStatus.IN_PROGRESS))
        case = self._require("case", invite.case_id, VendorCase)
        self._put("case", case.case_id, replace(case, lifecycle=CaseLifecycle.IN_PROGRESS))

    def _valid_invite(self, token: str) -> VendorInvite:
        if not isinstance(token, str) or not token:
            raise VendorBackendError("invalid_invite", "invitation is invalid", status=404)
        invite = self.repository.find_invite_by_token_hash(
            self._hash_token(token), workspace_id=self.workspace_id
        )
        if invite is None:
            raise VendorBackendError("invalid_invite", "invitation is invalid", status=404)
        if invite.status is InviteStatus.REVOKED:
            raise VendorBackendError("invite_revoked", "invitation was revoked", status=410)
        if invite.status is InviteStatus.SUBMITTED:
            raise VendorBackendError("invite_submitted", "invitation was already submitted", status=409)
        expires = datetime.datetime.fromisoformat(invite.expires_at)
        if self._now_datetime() >= expires:
            expired = replace(invite, status=InviteStatus.EXPIRED)
            self._put("invite", invite.invite_id, expired)
            raise VendorBackendError("invite_expired", "invitation expired", status=410)
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
