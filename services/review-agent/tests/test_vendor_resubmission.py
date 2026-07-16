"""Vendor revise-and-resubmit loop after a reviewer requests changes (issue #64)."""

from __future__ import annotations

import datetime
import unittest

import _bootstrap  # noqa: F401

from review_agent.contracts.vendor import CaseLifecycle, InviteStatus, SubmissionStatus
from review_agent.profiles.service import ReviewProfileService
from review_agent.vendor.repository import InMemoryVendorRepository
from review_agent.vendor.service import VendorBackend, VendorBackendError


CRITERIA = [
    {
        "requirement_id": "SEC.DATA.001",
        "question": "Describe encryption controls.",
        "source_citation": {"source_id": "policy:security", "cell": "A1"},
        "expected_evidence": ["SOC 2"],
        "output_fields": ["security_summary"],
        "remediation_guidance": "Provide encryption evidence.",
    }
]


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime.datetime(2026, 7, 16, 9, tzinfo=datetime.timezone.utc)

    def __call__(self) -> datetime.datetime:
        return self.value


class VendorResubmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        self.repository = InMemoryVendorRepository()
        self.profiles = ReviewProfileService(self.repository, clock=self.clock)
        profile = self.profiles.create_draft("security", CRITERIA)
        self.profiles.fixture_test(profile.profile_version_id)
        self.profiles.activate(profile.profile_version_id)
        tokens = iter([character * 43 for character in "ABCDEFGH"])
        self.backend = VendorBackend(
            self.repository,
            self.profiles,
            clock=self.clock,
            token_factory=lambda: next(tokens),
        )
        vendor = self.backend.create_vendor("Example Vendor", "vendor.example")
        self.product = self.backend.create_product(vendor.vendor_id, "Example Product")
        self.contact = self.backend.create_contact(
            vendor.vendor_id, "Vendor Contact", "contact@vendor.example"
        )
        self.backend.register_case(
            "CASE-1", self.product.product_id, "Scheduling", "public scope"
        )
        self.token = self.backend.issue_invite("CASE-1", self.contact.contact_id)["token"]
        self.backend.resolve_invite(self.token, mark_open=True)
        self.backend.add_evidence(
            self.token,
            {
                "filename": "soc2-report.pdf",
                "content_type": "application/pdf",
                "size_bytes": 100,
                "sha256": "a" * 64,
            },
        )
        self.backend.set_trust_center_url(self.token, "https://trust.vendor.example/x")
        self.backend.run_intake_analysis(self.token)
        self.backend.finalize_submission(self.token)

    def test_reopen_returns_submission_to_editable_draft_with_version_bump(self) -> None:
        with self.assertRaises(VendorBackendError):
            self.backend.resolve_invite(self.token)  # frozen after finalize
        reopened = self.backend.reopen_submission("CASE-1")
        self.assertIsNotNone(reopened)
        self.assertIs(reopened.status, SubmissionStatus.DRAFT)
        self.assertEqual(reopened.version, 2)
        self.assertIsNone(reopened.finalized_at)
        self.assertTrue(reopened.intake_analysis_complete)
        # The same link works again with prior work intact.
        view = self.backend.resolve_invite(self.token)
        self.assertEqual(view["invite"]["status"], InviteStatus.IN_PROGRESS.value)
        self.assertEqual(
            view["submission"]["trust_center_url"], "https://trust.vendor.example/x"
        )
        self.assertEqual(len(view["submission"]["evidence_artifact_ids"]), 1)

    def test_reopen_extends_an_expiring_invitation(self) -> None:
        self.clock.value += datetime.timedelta(days=6, hours=23)
        reopened = self.backend.reopen_submission("CASE-1")
        self.assertIsNotNone(reopened)
        invites = self.backend.list_invites("CASE-1")
        expires = datetime.datetime.fromisoformat(invites[0].expires_at)
        self.assertGreater(expires - self.clock.value, datetime.timedelta(days=6))

    def test_changes_requested_stage_survives_draft_edits_until_refinalize(self) -> None:
        self.backend.transition_case(
            "CASE-1",
            CaseLifecycle.NEEDS_REVIEW,
        )
        self.backend.transition_case(
            "CASE-1",
            CaseLifecycle.CHANGES_REQUESTED,
            vendor_visible_comment="Provide a current report.",
            vendor_next_actions=("Upload the current SOC 2 report.",),
        )
        self.backend.reopen_submission("CASE-1")
        # Draft edits keep the changes-requested stage and its messaging.
        self.backend.set_trust_center_url(self.token, "https://trust.vendor.example/y")
        status = self.backend.review_status(self.token)
        self.assertEqual(status["review_stage"], "changes_requested")
        self.assertEqual(status["vendor_visible_comment"], "Provide a current report.")
        self.assertEqual(status["next_actions"], ["Upload the current SOC 2 report."])
        # Re-finalizing moves the case back under review.
        finalized = self.backend.finalize_submission(self.token)
        self.assertIs(finalized.status, SubmissionStatus.FINALIZED)
        self.assertEqual(finalized.version, 2)
        self.assertEqual(
            self.backend.review_status(self.token)["review_stage"], "under_review"
        )

    def test_resubmission_supports_a_new_review_run_version(self) -> None:
        run_one = self.backend.create_review_run("CASE-1")
        self.assertEqual(run_one.run_version, 1)
        self.backend.reopen_submission("CASE-1")
        self.backend.finalize_submission(self.token)
        run_two = self.backend.create_review_run("CASE-1", "recheck the new evidence")
        self.assertEqual(run_two.run_version, 2)
        self.assertEqual(run_two.approval_scope.submission_version, 2)
        self.assertEqual(run_two.previous_run_id, run_one.run_id)

    def test_reopen_without_submitted_invite_is_a_noop(self) -> None:
        self.backend.register_case(
            "CASE-2", self.product.product_id, "Other", "internal scope"
        )
        self.assertIsNone(self.backend.reopen_submission("CASE-2"))


if __name__ == "__main__":
    unittest.main()
