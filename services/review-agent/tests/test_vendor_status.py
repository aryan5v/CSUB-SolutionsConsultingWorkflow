"""Vendor-facing review status and outcome-notification tests (issue #38)."""

from __future__ import annotations

import datetime
import hashlib
import json
import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.email import SimulatedEmailSender
from review_agent.api import LocalReviewApi
from review_agent.contracts.vendor import CaseLifecycle, InviteStatus
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

    def test_checklist_splits_received_processing_and_outstanding(self) -> None:
        self.analyze_with_soc2()
        status = self.backend.review_status(self.token)
        by_id = {item["requirement_id"]: item for item in status["checklist"]}
        self.assertEqual(by_id["SEC.DATA.001"]["status"], "received")
        self.assertEqual(by_id["A11Y.VPAT.001"]["status"], "outstanding")
        self.assertEqual(by_id["A11Y.VPAT.001"]["expected_evidence"], ["VPAT"])
        # Regression: an unvalidated free-text answer is never presented as
        # received evidence; it is "processing" until validation (issue #36).
        self.backend.save_answers(self.token, {"A11Y.VPAT.001": "VPAT attached on request."})
        answered = {
            item["requirement_id"]: item["status"]
            for item in self.backend.review_status(self.token)["checklist"]
        }
        self.assertEqual(answered["A11Y.VPAT.001"], "processing")
        self.assertEqual(answered["SEC.DATA.001"], "received")

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
                "vendor_visible_comment",
                "next_actions",
                "checklist",
            },
        )
        self.assertIsNone(status["vendor_visible_comment"])
        self.assertEqual(status["next_actions"], [])
        self.assertNotIn("comments", status)
        self.assertNotIn("token_hash", status["invite"])
        self.assertIn(
            status["review_stage"],
            {"collecting_evidence", "under_review", "changes_requested", "decided"},
        )

    def test_changes_requested_derives_safe_actions_and_stays_case_scoped(self) -> None:
        self.analyze_with_soc2()
        self.backend.finalize_submission(self.token)
        self.backend.transition_case("CASE-1", CaseLifecycle.NEEDS_REVIEW)
        self.backend.transition_case(
            "CASE-1",
            CaseLifecycle.CHANGES_REQUESTED,
            vendor_visible_comment="Please update the requested accessibility evidence.",
            vendor_next_actions=(),
        )

        status = self.backend.review_status(self.token)
        self.assertEqual(status["review_stage"], "changes_requested")
        self.assertIsNone(status["outcome"])
        self.assertEqual(
            status["vendor_visible_comment"],
            "Please update the requested accessibility evidence.",
        )
        self.assertEqual(
            status["next_actions"],
            ["Provide information or evidence for requirement A11Y.VPAT.001."],
        )
        serialized = json.dumps(status)
        self.assertNotIn("comments", serialized)
        self.assertNotIn("policy", serialized)
        self.assertNotIn("risk", serialized)

        other_product = self.backend.create_product(
            self.product.vendor_id, "Other Product"
        )
        self.backend.register_case(
            "CASE-2", other_product.product_id, "Other use", "other scope"
        )
        other_token = self.backend.issue_invite(
            "CASE-2", self.contact.contact_id
        )["token"]
        other_status = self.backend.review_status(other_token)
        self.assertIsNone(other_status["vendor_visible_comment"])
        self.assertEqual(other_status["next_actions"], [])
        self.assertNotIn("CASE-1", json.dumps(other_status))

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

    def test_submitted_invite_cannot_read_status_after_expiry(self) -> None:
        # Regression: a submitted token honors the same expiry as every other
        # token operation instead of staying usable forever.
        self.analyze_with_soc2()
        self.backend.finalize_submission(self.token)
        self.clock.value += datetime.timedelta(days=8)
        with self.assertRaises(VendorBackendError) as expired:
            self.backend.review_status(self.token)
        self.assertEqual(expired.exception.code, "invite_expired")
        # The submitted audit marker is preserved; only the read is rejected.
        invite = self.backend.list_invites("CASE-1")[0]
        self.assertIs(invite.status, InviteStatus.SUBMITTED)


class _ThrowingEmailSender:
    def send(self, *, to: str, subject: str, body: str) -> dict:
        del to, subject, body
        raise RuntimeError("email transport unavailable")


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
        self.api.review_case(
            "TR-260714-018",
            {
                **self.approve_payload("TR-260714-018"),
                "comments": "Internal approval note; never vendor visible.",
                "vendor_visible_comment": "Thank you. The review is complete.",
            },
        )
        self.assertEqual(len(self.email.sent), 1)
        message = self.email.sent[0]
        self.assertEqual(message["to"], "approve@vendor.example")
        self.assertIn("passed", message["subject"])
        self.assertEqual(message["delivery"], "simulated")
        events = self.api.integration_events()["items"]
        email_events = [item for item in events if item["event_type"] == "email.notification"]
        self.assertEqual(len(email_events), 1)
        self.assertEqual(email_events[0]["detail"]["delivery"], "simulated")
        # Regression: the persisted event carries only a recipient digest; the
        # raw address never enters the integration-event log.
        expected_digest = hashlib.sha256(b"approve@vendor.example").hexdigest()
        self.assertEqual(email_events[0]["detail"]["recipient_sha256"], expected_digest)
        self.assertNotIn("recipient", email_events[0]["detail"])
        self.assertNotIn("approve@vendor.example", json.dumps(events))
        status = self.api.vendor_review_status(token)
        self.assertEqual(status["review_stage"], "decided")
        self.assertEqual(status["outcome"], "approved")
        self.assertEqual(
            status["vendor_visible_comment"], "Thank you. The review is complete."
        )
        self.assertEqual(status["next_actions"], [])
        self.assertNotIn("Internal approval note", json.dumps(status))

    def test_reject_and_request_info_send_distinct_outcomes(self) -> None:
        reject_token = self.invite_for("TR-260714-011", "reject@vendor.example")
        self.api.analyze_case("TR-260714-011")
        self.api.review_case(
            "TR-260714-011",
            {
                **self.approve_payload("TR-260714-011", "reject"),
                "comments": "Internal rejection rationale.",
                "vendor_visible_comment": "The campus review is complete.",
            },
        )
        self.assertIn("did not pass", self.email.sent[-1]["subject"])
        rejected_status = self.api.vendor_review_status(reject_token)
        self.assertEqual(rejected_status["outcome"], "declined")
        self.assertEqual(
            rejected_status["vendor_visible_comment"],
            "The campus review is complete.",
        )
        self.assertEqual(rejected_status["next_actions"], [])
        self.assertNotIn("Internal rejection rationale", json.dumps(rejected_status))

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
            "TR-260714-018",
            {
                **self.approve_payload("TR-260714-018", "request_info"),
                "comments": "Internal finding: do not disclose.",
                "vendor_visible_comment": "Please provide the two requested updates.",
                "vendor_next_actions": [
                    "Upload the current product-specific ACR.",
                    "Confirm the encryption documentation version.",
                ],
            },
        )
        self.assertIn("needs changes", email_two.sent[-1]["subject"])
        status = api_two.vendor_review_status(issued["token"])
        self.assertEqual(status["review_stage"], "changes_requested")
        self.assertIsNone(status["outcome"])
        self.assertEqual(
            status["vendor_visible_comment"],
            "Please provide the two requested updates.",
        )
        self.assertEqual(
            status["next_actions"],
            [
                "Upload the current product-specific ACR.",
                "Confirm the encryption documentation version.",
            ],
        )
        self.assertNotIn("Internal finding", json.dumps(status))

    def test_outcome_email_targets_submitted_contact_not_newest_invite(self) -> None:
        # Regression: the notification goes to the contact whose invitation
        # carries the submitted evidence, even when a newer invitation was
        # issued to a different contact afterwards.
        submitted_token = self.invite_for("TR-260714-018", "submitted@vendor.example")
        self.api.vendor_finalize(submitted_token)
        self.invite_for("TR-260714-018", "newer-contact@vendor.example")
        self.api.analyze_case("TR-260714-018")
        self.api.review_case("TR-260714-018", self.approve_payload("TR-260714-018"))
        self.assertEqual(len(self.email.sent), 1)
        self.assertEqual(self.email.sent[0]["to"], "submitted@vendor.example")

    def test_duplicate_decision_recording_sends_single_email(self) -> None:
        # Regression: re-recording the same outcome (e.g. a retried invocation)
        # must not send or persist a duplicate notification (issue #38).
        self.invite_for("TR-260714-018", "once@vendor.example")
        self.api.analyze_case("TR-260714-018")
        self.api.review_case("TR-260714-018", self.approve_payload("TR-260714-018"))
        self.api.review_case(
            "TR-260714-018", self.approve_payload("TR-260714-018", version=2)
        )
        self.assertEqual(len(self.email.sent), 1)
        events = self.api.integration_events()["items"]
        email_events = [item for item in events if item["event_type"] == "email.notification"]
        self.assertEqual(len(email_events), 1)
        self.assertEqual(email_events[0]["detail"]["dedupe_key"], "TR-260714-018:approved")

    def test_email_exception_records_hashed_intended_recipient(self) -> None:
        api = LocalReviewApi(email_sender=_ThrowingEmailSender())
        state = api._cases["TR-260714-018"].state
        vendor = next(
            item
            for item in api.list_vendors()["items"]
            if item["name"].casefold() == state.case_input.vendor_name.casefold()
        )
        contact = api.create_vendor_contact(
            {
                "vendor_id": vendor["vendor_id"],
                "name": "Failure Contact",
                "email": "failure@vendor.example",
            }
        )
        api.issue_vendor_invite(
            "TR-260714-018", {"contact_id": contact["contact_id"]}
        )
        api.analyze_case("TR-260714-018")
        api.review_case("TR-260714-018", self.approve_payload("TR-260714-018"))

        events = api.integration_events()["items"]
        email_event = next(
            item for item in events if item["event_type"] == "email.notification"
        )
        self.assertEqual(email_event["detail"]["delivery"], "failed")
        self.assertEqual(
            email_event["detail"]["recipient_sha256"],
            hashlib.sha256(b"failure@vendor.example").hexdigest(),
        )
        self.assertNotIn("failure@vendor.example", json.dumps(events))

    def test_decision_without_invite_sends_nothing_and_never_blocks(self) -> None:
        self.api.analyze_case("TR-260714-018")
        reviewed = self.api.review_case(
            "TR-260714-018", self.approve_payload("TR-260714-018")
        )
        self.assertEqual(reviewed["state"]["human_decision"]["action"], "approve")
        self.assertEqual(self.email.sent, [])


if __name__ == "__main__":
    unittest.main()
