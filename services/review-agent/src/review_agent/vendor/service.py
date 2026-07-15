"""Deterministic workspace-scoped vendor intake and immutable review runs."""

from __future__ import annotations

import datetime
import hashlib
import ipaddress
import re
import secrets
from dataclasses import replace
from difflib import SequenceMatcher
from typing import Any, Callable
from urllib.parse import urlsplit

from ..contracts.vendor import (
    DEFAULT_WORKSPACE_ID,
    ApprovalScope,
    CaseLifecycle,
    CoverageItem,
    EvidenceArtifact,
    IntegrationEvent,
    InviteStatus,
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
        invite = VendorInvite(
            invite_id=self._id("invite", "invite"),
            case_id=case_id,
            product_id=case.product_id,
            contact_id=contact_id,
            token_hash=self._hash_token(token),
            issued_at=now.isoformat(),
            expires_at=(now + self.invite_ttl).isoformat(),
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
        self._reject_extra(
            payload, {"filename", "content_type", "size_bytes", "sha256"}, required=True
        )
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
        """Active-profile requirements labeled received (covered/answered) or outstanding."""
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
                received = criterion.requirement_id in covered or criterion.requirement_id in answered
                items.append(
                    {
                        "requirement_id": criterion.requirement_id,
                        "question": criterion.question,
                        "expected_evidence": list(criterion.expected_evidence),
                        "status": "received" if received else "outstanding",
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
        if invite.status is InviteStatus.SUBMITTED:
            # A submitted invitation stays valid for status reads: the vendor's
            # part is done but the review continues.
            return invite
        expires = datetime.datetime.fromisoformat(invite.expires_at)
        if self._now_datetime() >= expires:
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
        auto_covered: list[str] = []
        for profile in self.profiles.active_profiles():
            for criterion in profile.criteria:
                if criterion.requirement_id in already_covered:
                    continue
                matched = self._extract_matches(criterion, evidence)
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
            f"extraction."
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
                "simulated": True,
            },
        )
        return finished

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
    ) -> IntegrationEvent:
        """Persist an auditable notification event with its truthful delivery mode."""
        detail = {
            "summary": summary,
            "delivery": delivery.get("delivery"),
            "simulated": delivery.get("simulated", True),
            "channel": delivery.get("channel"),
        }
        if delivery.get("to"):
            detail["recipient"] = delivery["to"]
        return self._event(
            event_type,
            "notification",
            case_id or "workspace",
            case_id=case_id,
            detail=detail,
        )

    # Weekly vendor reminders (issue #37) -------------------------------------

    _REMINDER_EVENT = "email.reminder"
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
        """Invites with missing/incomplete evidence that are due a reminder.

        An invite qualifies when it is still actionable (issued/opened/in
        progress and unexpired), its case has not moved past the vendor's part,
        its submission is an incomplete draft, and no reminder was recorded
        within ``reminder_interval``. Each candidate names the specific missing
        items so the reminder email can cite them (issue #37).
        """
        now = self._now_datetime()
        candidates: list[dict[str, Any]] = []
        for invite in self._list("invite", VendorInvite):
            if invite.status not in {
                InviteStatus.ISSUED,
                InviteStatus.OPENED,
                InviteStatus.IN_PROGRESS,
            }:
                continue
            if now >= datetime.datetime.fromisoformat(invite.expires_at):
                continue
            case = self.repository.get("case", invite.case_id, workspace_id=self.workspace_id)
            if not isinstance(case, VendorCase) or case.lifecycle not in self._REMINDER_LIFECYCLES:
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
            last_sent = self._last_reminder_at(invite.invite_id)
            if last_sent is not None and now - last_sent < self.reminder_interval:
                continue
            contact = self._require("contact", invite.contact_id, VendorContact)
            product = self._require("product", invite.product_id, VendorProduct)
            candidates.append(
                {
                    "invite_id": invite.invite_id,
                    "case_id": invite.case_id,
                    "contact_name": contact.name,
                    "contact_email": contact.email,
                    "product_name": product.name,
                    "stage": stage,
                    "missing": missing,
                }
            )
        return sorted(candidates, key=lambda item: item["invite_id"])

    def record_reminder(
        self, *, invite_id: str, case_id: str, summary: str, delivery: dict[str, Any]
    ) -> IntegrationEvent:
        """Persist one reminder send; the sweep uses this for weekly pacing."""
        detail = {
            "summary": summary,
            "delivery": delivery.get("delivery"),
            "simulated": delivery.get("simulated", True),
            "channel": delivery.get("channel"),
        }
        if delivery.get("to"):
            detail["recipient"] = delivery["to"]
        return self._event(
            self._REMINDER_EVENT,
            "invite",
            invite_id,
            case_id=case_id,
            detail=detail,
        )

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

    def _last_reminder_at(self, invite_id: str) -> datetime.datetime | None:
        stamps = [
            event.occurred_at
            for event in self._list("event", IntegrationEvent)
            if event.event_type == self._REMINDER_EVENT and event.resource_id == invite_id
        ]
        if not stamps:
            return None
        return datetime.datetime.fromisoformat(max(stamps))

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
