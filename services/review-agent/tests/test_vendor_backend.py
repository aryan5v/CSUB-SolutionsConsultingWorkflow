"""Vendor intake, isolation, profile, and immutable-run behavior tests."""

from __future__ import annotations

import datetime
import hashlib
import unittest

import _bootstrap  # noqa: F401

from review_agent.contracts.vendor import CaseLifecycle, SubmissionStatus
from review_agent.profiles.service import ProfileError, ReviewProfileService
from review_agent.vendor.repository import InMemoryVendorRepository
from review_agent.vendor.service import VendorBackend, VendorBackendError


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime.datetime(2026, 7, 14, 12, tzinfo=datetime.timezone.utc)

    def __call__(self) -> datetime.datetime:
        return self.value


CRITERIA = [
    {
        "requirement_id": "SEC.DATA.001",
        "question": "Describe encryption controls.",
        "source_citation": {"source_id": "policy:security", "cell": "A1"},
        "expected_evidence": ["SOC 2"],
        "output_fields": ["security_summary"],
        "remediation_guidance": "Provide encryption evidence.",
    },
    {
        "requirement_id": "A11Y.VPAT.001",
        "question": "Provide a current accessibility report.",
        "source_citation": {"source_id": "policy:accessibility", "cell": "B2"},
        "expected_evidence": ["VPAT"],
        "output_fields": ["accessibility_findings"],
        "remediation_guidance": "Provide a current VPAT.",
    },
]


class VendorBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        self.repository = InMemoryVendorRepository()
        self.profiles = ReviewProfileService(self.repository, clock=self.clock)
        profile = self.profiles.create_draft("combined", CRITERIA)
        self.profiles.fixture_test(profile.profile_version_id)
        self.profile = self.profiles.activate(profile.profile_version_id)
        tokens = iter([character * 43 for character in "ABCDEFGH"])
        self.backend = VendorBackend(
            self.repository,
            self.profiles,
            clock=self.clock,
            token_factory=lambda: next(tokens),
        )
        self.vendor = self.backend.create_vendor("Example Vendor", "vendor.example")
        self.product = self.backend.create_product(self.vendor.vendor_id, "Example Product")
        self.contact = self.backend.create_contact(
            self.vendor.vendor_id, "Vendor Contact", "contact@vendor.example"
        )
        self.backend.register_case(
            "CASE-1", self.product.product_id, "Course scheduling", "public web scope"
        )

    def issue(self, case_id: str = "CASE-1") -> dict:
        return self.backend.issue_invite(case_id, self.contact.contact_id)

    def test_token_is_opaque_hashed_at_rest_and_never_in_projection(self) -> None:
        issued = self.issue()
        token = issued["token"]
        self.assertEqual(token, "A" * 43)
        invite_id = issued["invite"]["invite_id"]
        stored = self.repository.get("invite", invite_id, workspace_id="csub-demo")
        self.assertEqual(stored.token_hash, hashlib.sha256(token.encode()).hexdigest())
        self.assertNotEqual(stored.token_hash, token)
        self.assertNotIn("token_hash", issued["invite"])
        self.assertNotIn("token_hash", self.backend.resolve_invite(token)["invite"])
        self.assertNotIn("reviewer_notes", self.backend.resolve_invite(token))
        self.assertNotIn("findings", self.backend.resolve_invite(token))
        self.assertNotIn("policy", self.backend.resolve_invite(token))

    def test_open_draft_recovery_and_only_unresolved_questions(self) -> None:
        token = self.issue()["token"]
        opened = self.backend.resolve_invite(token, mark_open=True)
        self.assertEqual(opened["invite"]["status"], "opened")
        # Staged intake: no questions are exposed until the deterministic
        # research/coverage/extraction step has run.
        self.assertEqual(opened["questions"], [])
        self.assertFalse(opened["submission"]["intake_analysis_complete"])
        self.assertEqual(self.backend.unresolved_questions(token), [])
        artifact = self.backend.add_evidence(
            token,
            {
                "filename": "certificate-of-insurance.pdf",
                "content_type": "application/pdf",
                "size_bytes": 100,
                "sha256": "a" * 64,
            },
        )
        self.backend.set_trust_center_url(token, "https://trust.vendor.example/security")
        # Analysis is required before questions/answers are available.
        with self.assertRaises(VendorBackendError) as pending:
            self.backend.save_answers(token, {"A11Y.VPAT.001": "early"})
        self.assertEqual(pending.exception.code, "intake_analysis_pending")
        analyzed = self.backend.run_intake_analysis(token)
        self.assertTrue(analyzed.intake_analysis_complete)
        # Metadata-only COI evidence (a validated type) is retained but fails
        # closed with a content_unavailable finding, so it cannot cover any
        # requirement; both active requirements remain open for explicit answers.
        questions = self.backend.unresolved_questions(token)
        self.assertEqual(
            [item["requirement_id"] for item in questions],
            ["A11Y.VPAT.001", "SEC.DATA.001"],
        )
        findings = self.backend.submission_findings(token)
        self.assertEqual(
            [(item["check"], item["disposition"]) for item in findings],
            [("evidence.content_unavailable", "manual_review")],
        )
        self.assertEqual(findings[0]["artifact_id"], artifact.artifact_id)
        self.assertEqual(findings[0]["source_citation"]["line"], 1)
        self.backend.save_answers(
            token,
            {
                "A11Y.VPAT.001": "VPAT is attached on request.",
                "SEC.DATA.001": "Security response requires reviewer confirmation.",
            },
        )
        recovered = self.backend.resolve_invite(token)
        self.assertEqual(
            recovered["submission"]["trust_center_url"], "https://trust.vendor.example/security"
        )
        self.assertEqual(recovered["questions"], [])

    def test_unknown_requirements_and_nonpublic_urls_are_rejected(self) -> None:
        token = self.issue()["token"]
        with self.assertRaises(VendorBackendError):
            self.backend.save_answers(token, {"MODEL.INVENTED.999": "invented"})
        for url in (
            "http://trust.vendor.example",
            "https://localhost/private",
            "https://127.0.0.1/private",
            "https://user:password@trust.vendor.example/private",
        ):
            with self.subTest(url=url), self.assertRaises(VendorBackendError):
                self.backend.set_trust_center_url(token, url)

    def test_expired_revoked_and_submitted_invites_rotate_with_stable_terminal_errors(self) -> None:
        issued = self.issue()
        self.clock.value += datetime.timedelta(days=7)
        with self.assertRaises(VendorBackendError) as expired:
            self.backend.resolve_invite(issued["token"])
        self.assertEqual(expired.exception.code, "invite_expired")

        after_expiry = self.backend.resend_invite(issued["invite"]["invite_id"])
        with self.assertRaises(VendorBackendError) as still_expired:
            self.backend.resolve_invite(issued["token"])
        self.assertEqual(still_expired.exception.code, "invite_expired")
        self.assertEqual(
            self.backend.resolve_invite(after_expiry["token"], mark_open=True)["invite"]["status"],
            "opened",
        )

        self.backend.revoke_invite(after_expiry["invite"]["invite_id"])
        with self.assertRaises(VendorBackendError) as revoked:
            self.backend.resolve_invite(after_expiry["token"])
        self.assertEqual(revoked.exception.code, "invite_revoked")
        after_revocation = self.backend.resend_invite(after_expiry["invite"]["invite_id"])
        self.assertEqual(self.backend.resolve_invite(after_revocation["token"])["invite"]["status"], "issued")

        finalized = self.backend.finalize_submission(after_revocation["token"])
        self.assertEqual(finalized.status.value, "finalized")
        with self.assertRaises(VendorBackendError) as submitted:
            self.backend.resolve_invite(after_revocation["token"])
        self.assertEqual(submitted.exception.code, "invite_submitted")
        after_submission = self.backend.resend_invite(after_revocation["invite"]["invite_id"])
        self.assertEqual(self.backend.resolve_invite(after_submission["token"])["invite"]["status"], "issued")
        with self.assertRaises(VendorBackendError) as duplicate_rotation:
            self.backend.resend_invite(after_revocation["invite"]["invite_id"])
        self.assertEqual(duplicate_rotation.exception.code, "invite_already_rotated")

    def test_duplicate_issue_is_rejected_and_revocation_is_idempotent(self) -> None:
        issued = self.issue()
        with self.assertRaises(VendorBackendError) as duplicate:
            self.issue()
        self.assertEqual(duplicate.exception.code, "active_invite_exists")
        first = self.backend.revoke_invite(issued["invite"]["invite_id"])
        second = self.backend.revoke_invite(issued["invite"]["invite_id"])
        self.assertEqual(second, first)

    def test_reopen_preserves_prior_work_and_allows_resubmit(self) -> None:
        token = self.issue()["token"]
        self.backend.add_evidence(
            token,
            {
                "filename": "soc2-report.pdf",
                "content_type": "application/pdf",
                "size_bytes": 100,
                "sha256": "a" * 64,
            },
        )
        self.backend.set_trust_center_url(token, "https://trust.vendor.example/security")
        self.backend.run_intake_analysis(token)
        self.backend.save_answers(token, {"A11Y.VPAT.001": "Initial VPAT note."})
        first = self.backend.finalize_submission(token)
        self.assertEqual(first.version, 1)
        self.assertEqual(first.status, SubmissionStatus.FINALIZED)

        self.backend.transition_case("CASE-1", CaseLifecycle.NEEDS_REVIEW)
        self.backend.transition_case(
            "CASE-1",
            CaseLifecycle.CHANGES_REQUESTED,
            vendor_visible_comment="Please attach the current VPAT.",
        )
        reopened = self.backend.reopen_submission("CASE-1")
        self.assertIsNotNone(reopened)
        assert reopened is not None
        self.assertEqual(reopened.status, SubmissionStatus.DRAFT)
        self.assertEqual(reopened.version, 2)
        self.assertTrue(reopened.intake_analysis_complete)
        self.assertEqual(reopened.answers["A11Y.VPAT.001"], "Initial VPAT note.")

        resolved = self.backend.resolve_invite(token)
        self.assertEqual(resolved["submission"]["status"], "draft")
        status = self.backend.review_status(token)
        self.assertEqual(status["review_stage"], "changes_requested")
        self.assertEqual(status["vendor_visible_comment"], "Please attach the current VPAT.")

        self.backend.add_evidence(
            token,
            {
                "filename": "vpat-report.pdf",
                "content_type": "application/pdf",
                "size_bytes": 120,
                "sha256": "b" * 64,
            },
        )
        second = self.backend.finalize_submission(token)
        self.assertEqual(second.version, 2)
        self.assertEqual(second.status, SubmissionStatus.FINALIZED)
        self.assertEqual(
            self.backend.get_case_lifecycle("CASE-1"),
            "submitted",
        )

    def test_cross_case_and_cross_workspace_isolation(self) -> None:
        self.backend.register_case(
            "CASE-2", self.product.product_id, "Different use", "internal desktop scope"
        )
        first = self.issue("CASE-1")
        second = self.issue("CASE-2")
        artifact = self.backend.add_evidence(
            first["token"],
            {
                "filename": "one.pdf",
                "content_type": "application/pdf",
                "size_bytes": 1,
                "sha256": "b" * 64,
            },
        )
        with self.assertRaises(VendorBackendError) as isolated:
            self.backend.add_coverage(second["token"], "SEC.DATA.001", [artifact.artifact_id])
        self.assertEqual(isolated.exception.code, "cross_case_evidence")

        other_profiles = ReviewProfileService(
            self.repository, workspace_id="other-workspace", clock=self.clock
        )
        other = VendorBackend(
            self.repository,
            other_profiles,
            workspace_id="other-workspace",
            clock=self.clock,
        )
        with self.assertRaises(VendorBackendError) as cross_workspace:
            other.resolve_invite(first["token"])
        self.assertEqual(cross_workspace.exception.code, "invalid_invite")

    def test_active_profile_and_historical_run_versions_are_immutable(self) -> None:
        token = self.issue()["token"]
        self.backend.finalize_submission(token)
        run_one = self.backend.create_review_run("CASE-1")
        self.assertEqual(run_one.approval_scope.product_id, self.product.product_id)
        self.assertEqual(run_one.approval_scope.use_case, "Course scheduling")
        self.assertEqual(run_one.approval_scope.scope, "public web scope")
        self.assertEqual(run_one.approval_scope.profile_version_ids, (self.profile.profile_version_id,))

        with self.assertRaises(ProfileError):
            self.profiles.update_draft(self.profile.profile_version_id, CRITERIA[:1])
        second = self.profiles.create_draft("combined", CRITERIA[:1])
        with self.assertRaises(ProfileError):
            self.profiles.rollback("combined", second.profile_version_id)
        self.profiles.fixture_test(second.profile_version_id)
        second = self.profiles.activate(second.profile_version_id)
        run_two = self.backend.create_review_run("CASE-1")
        self.assertEqual(run_two.run_version, 2)
        self.assertEqual(run_two.previous_run_id, run_one.run_id)
        self.assertFalse(run_two.decision_valid)
        self.assertFalse(run_two.write_preview_valid)
        historical = self.backend.list_review_runs("CASE-1")[0]
        self.assertEqual(
            historical.approval_scope.profile_version_ids,
            (self.profile.profile_version_id,),
        )
        rolled_back = self.profiles.rollback("combined", self.profile.profile_version_id)
        self.assertEqual(rolled_back.profile_version_id, self.profile.profile_version_id)
        self.assertEqual(self.profiles.active("combined").profile_version_id, self.profile.profile_version_id)


if __name__ == "__main__":
    unittest.main()
