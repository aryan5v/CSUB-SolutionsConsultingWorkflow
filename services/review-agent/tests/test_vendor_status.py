"""Vendor-facing review status and outcome-notification tests (issue #38)."""

from __future__ import annotations

import datetime
import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.email import SimulatedEmailSender
from review_agent.api import LocalReviewApi
from review_agent.profiles.service import ReviewProfileService
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


class VendorReviewStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        self.repository = InMemoryVendorRepository()
        self.profiles = ReviewProfileService(self.repository, clock=self.clock)
        profile = self.profiles.create_draft("combined", CRITERIA)
        self.profiles.fixture_test(profile.profile_version_id)
        self.profiles.activate(profile.profile_version_id)
        tokens = iter(["A" * 43, "B" * 43, "C" * 43])
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
            "CASE-1", self.product.product_id, "Course scheduling", "public web scope"
        )
        self.token = self.backend.issue_invite("CASE-1", self.contact.contact_id)["token"]

    def analyze_with_soc2(self) -> None:
        self.backend.add_evidence(
            self.token,
            {
                "filename": "soc2-report.pdf",
                "content_type": "application/pdf",
                "size_bytes": 100,
                "sha256": "a" * 64,
            },
        )
        self.backend.set_trust_center_url(self.token, "https://trust.vendor.example/security")
        self.backend.run_intake_analysis(self.token)

    def test_checklist_hidden_until_intake_analysis(self) -> None:
        status = self.backend.review_status(self.token)
        self.assertEqual(status["review_stage"], "collecting_evidence")
        self.assertIsNone(status["outcome"])
        self.assertFalse(status["intake_analysis_complete"])
        self.assertEqual(status["checklist"], [])

    def test_checklist_splits_received_and_outstanding(self) -> None:
        self.analyze_with_soc2()
        status = self.backend.review_status(self.token)
        by_id = {item["requirement_id"]: item for item in status["checklist"]}
        self.assertEqual(by_id["SEC.DATA.001"]["status"], "received")
        self.assertEqual(by_id["A11Y.VPAT.001"]["status"], "outstanding")
        self.assertEqual(by_id["A11Y.VPAT.001"]["expected_evidence"], ["VPAT"])
        # An answered requirement also counts as received.
        self.backend.save_answers(self.token, {"A11Y.VPAT.001": "VPAT attached on request."})
        answered = {
            item["requirement_id"]: item["status"]
            for item in self.backend.review_status(self.token)["checklist"]
        }
        self.assertEqual(answered["A11Y.VPAT.001"], "received")

    def test_status_stays_readable_after_finalize(self) -> None:
        self.analyze_with_soc2()
        self.backend.finalize_submission(self.token)
        with self.assertRaises(VendorBackendError):
            self.backend.resolve_invite(self.token)
        status = self.backend.review_status(self.token)
        self.assertEqual(status["invite"]["status"], "submitted")
        self.assertEqual(status["submission_status"], "finalized")
        self.assertEqual(status["review_stage"], "under_review")
        self.assertIsNone(status["outcome"])

    def test_status_never_exposes_reviewer_only_fields(self) -> None:
        status = self.backend.review_status(self.token)
        self.assertEqual(
            set(status),
            {
                "invite",
                "vendor",
                "product",
                "submission_status",
                "intake_analysis_complete",
                "review_stage",
                "outcome",
                "checklist",
            },
        )
        self.assertNotIn("token_hash", status["invite"])
        self.assertIn(
            status["review_stage"],
            {"collecting_evidence", "under_review", "changes_requested", "decided"},
        )

    def test_revoked_and_expired_invites_cannot_read_status(self) -> None:
        invite_id = self.backend.list_invites("CASE-1")[0].invite_id
        second = self.backend.issue_invite("CASE-1", self.contact.contact_id)
        self.backend.revoke_invite(invite_id)
        with self.assertRaises(VendorBackendError) as revoked:
            self.backend.review_status(self.token)
        self.assertEqual(revoked.exception.code, "invite_revoked")
        self.clock.value += datetime.timedelta(days=8)
        with self.assertRaises(VendorBackendError) as expired:
            self.backend.review_status(second["token"])
        self.assertEqual(expired.exception.code, "invite_expired")


class VendorOutcomeEmailTests(unittest.TestCase):
    """Decision outcomes reach the invited contact via the email adapter."""

    def setUp(self) -> None:
        self.email = SimulatedEmailSender()
        self.api = LocalReviewApi(email_sender=self.email)

    def invite_for(self, case_id: str, email: str) -> str:
        state = self.api._cases[case_id].state
        vendors = self.api.list_vendors()["items"]
        vendor = next(
            item
            for item in vendors
            if item["name"].casefold() == state.case_input.vendor_name.casefold()
        )
        contact = self.api.create_vendor_contact(
            {"vendor_id": vendor["vendor_id"], "name": "Outcome Contact", "email": email}
        )
        issued = self.api.issue_vendor_invite(case_id, {"contact_id": contact["contact_id"]})
        return issued["token"]

    def approve_payload(self, case_id: str, action: str = "approve", version: int = 1) -> dict:
        return {
            "case_id": case_id,
            "decision_version": version,
            "reviewer_id": "alex.reviewer@example.edu",
            "action": action,
            "decided_at": "2026-07-15T20:30:00+00:00",
        }

    def test_approval_emails_invited_contact_and_updates_vendor_status(self) -> None:
        token = self.invite_for("TR-260714-018", "approve@vendor.example")
        self.api.analyze_case("TR-260714-018")
        self.api.review_case("TR-260714-018", self.approve_payload("TR-260714-018"))
        self.assertEqual(len(self.email.sent), 1)
        message = self.email.sent[0]
        self.assertEqual(message["to"], "approve@vendor.example")
        self.assertIn("passed", message["subject"])
        self.assertEqual(message["delivery"], "simulated")
        events = self.api.integration_events()["items"]
        email_events = [item for item in events if item["event_type"] == "email.notification"]
        self.assertEqual(len(email_events), 1)
        self.assertEqual(email_events[0]["detail"]["delivery"], "simulated")
        self.assertEqual(email_events[0]["detail"]["recipient"], "approve@vendor.example")
        status = self.api.vendor_review_status(token)
        self.assertEqual(status["review_stage"], "decided")
        self.assertEqual(status["outcome"], "approved")

    def test_reject_and_request_info_send_distinct_outcomes(self) -> None:
        self.invite_for("TR-260714-011", "reject@vendor.example")
        self.api.analyze_case("TR-260714-011")
        self.api.review_case("TR-260714-011", self.approve_payload("TR-260714-011", "reject"))
        self.assertIn("did not pass", self.email.sent[-1]["subject"])

        email_two = SimulatedEmailSender()
        api_two = LocalReviewApi(email_sender=email_two)
        state = api_two._cases["TR-260714-018"].state
        vendor = next(
            item
            for item in api_two.list_vendors()["items"]
            if item["name"].casefold() == state.case_input.vendor_name.casefold()
        )
        contact = api_two.create_vendor_contact(
            {"vendor_id": vendor["vendor_id"], "name": "Contact", "email": "info@vendor.example"}
        )
        issued = api_two.issue_vendor_invite(
            "TR-260714-018", {"contact_id": contact["contact_id"]}
        )
        api_two.analyze_case("TR-260714-018")
        api_two.review_case(
            "TR-260714-018", self.approve_payload("TR-260714-018", "request_info")
        )
        self.assertIn("needs changes", email_two.sent[-1]["subject"])
        status = api_two.vendor_review_status(issued["token"])
        self.assertEqual(status["review_stage"], "changes_requested")
        self.assertIsNone(status["outcome"])

    def test_decision_without_invite_sends_nothing_and_never_blocks(self) -> None:
        self.api.analyze_case("TR-260714-018")
        reviewed = self.api.review_case(
            "TR-260714-018", self.approve_payload("TR-260714-018")
        )
        self.assertEqual(reviewed["state"]["human_decision"]["action"], "approve")
        self.assertEqual(self.email.sent, [])


if __name__ == "__main__":
    unittest.main()
