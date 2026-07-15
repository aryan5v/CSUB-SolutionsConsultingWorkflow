"""Weekly vendor reminder tests: cadence, specificity, and stop conditions (issue #37)."""

from __future__ import annotations

import datetime
import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.email import SimulatedEmailSender
from review_agent.api import LocalReviewApi
from review_agent.contracts.vendor import CaseLifecycle
from review_agent.profiles.service import ReviewProfileService
from review_agent.vendor.repository import InMemoryVendorRepository
from review_agent.vendor.service import VendorBackend


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


class ReminderCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        self.repository = InMemoryVendorRepository()
        self.profiles = ReviewProfileService(self.repository, clock=self.clock)
        profile = self.profiles.create_draft("combined", CRITERIA)
        self.profiles.fixture_test(profile.profile_version_id)
        self.profiles.activate(profile.profile_version_id)
        tokens = iter([letter * 43 for letter in "ABCDEFGH"])
        self.backend = VendorBackend(
            self.repository,
            self.profiles,
            clock=self.clock,
            token_factory=lambda: next(tokens),
            # Invites must outlive several weekly reminders in these tests.
            invite_ttl=datetime.timedelta(days=60),
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

    def send_due_reminders(self) -> list[dict]:
        due = self.backend.reminder_candidates()
        for candidate in due:
            self.backend.record_reminder(
                invite_id=candidate["invite_id"],
                case_id=candidate["case_id"],
                summary="reminder",
                delivery={"delivery": "simulated", "simulated": True, "channel": "email"},
            )
        return due

    def test_nothing_submitted_names_submission_gaps(self) -> None:
        [candidate] = self.backend.reminder_candidates()
        self.assertEqual(candidate["contact_email"], "contact@vendor.example")
        self.assertEqual(candidate["stage"], "awaiting_submission")
        labels = [item["label"] for item in candidate["missing"]]
        self.assertEqual(labels, ["Evidence files", "Trust-center URL"])

    def test_open_questions_name_the_exact_missing_documents(self) -> None:
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
        [candidate] = self.backend.reminder_candidates()
        self.assertEqual(candidate["stage"], "questions_open")
        self.assertEqual(
            [(item["requirement_id"], item["label"]) for item in candidate["missing"]],
            [("A11Y.VPAT.001", "VPAT")],
        )
        self.assertEqual(candidate["missing"][0]["detail"], "Provide a current VPAT.")

    def test_weekly_cadence_is_enforced(self) -> None:
        self.assertEqual(len(self.send_due_reminders()), 1)
        self.assertEqual(self.backend.reminder_candidates(), [])
        self.clock.value += datetime.timedelta(days=3)
        self.assertEqual(self.backend.reminder_candidates(), [])
        self.clock.value += datetime.timedelta(days=4, seconds=1)
        self.assertEqual(len(self.send_due_reminders()), 1)

    def test_reminders_stop_on_completion_finalize_revoke_and_decision(self) -> None:
        # Completion: everything covered/answered means nothing to nag about.
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
        self.backend.save_answers(self.token, {"A11Y.VPAT.001": "VPAT attached on request."})
        self.assertEqual(self.backend.reminder_candidates(), [])

        # Finalized submission: the invite moves to submitted and drops out.
        self.backend.finalize_submission(self.token)
        self.assertEqual(self.backend.reminder_candidates(), [])

        # Revoked invite on a second case never reminds.
        self.backend.register_case(
            "CASE-2", self.product.product_id, "Second use", "internal scope"
        )
        second = self.backend.issue_invite("CASE-2", self.contact.contact_id)
        self.backend.revoke_invite(second["invite"]["invite_id"])
        self.assertEqual(self.backend.reminder_candidates(), [])

        # A case the reviewer has taken over (needs_review onward) stops reminders
        # even if the invite itself was never finalized.
        self.backend.register_case(
            "CASE-3", self.product.product_id, "Third use", "internal scope"
        )
        self.backend.issue_invite("CASE-3", self.contact.contact_id)
        self.assertEqual(len(self.backend.reminder_candidates()), 1)
        self.backend.transition_case("CASE-3", CaseLifecycle.NEEDS_REVIEW)
        self.assertEqual(self.backend.reminder_candidates(), [])

    def test_expired_invites_are_not_reminded(self) -> None:
        self.clock.value += datetime.timedelta(days=61)
        self.assertEqual(self.backend.reminder_candidates(), [])


class ReminderSweepApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.email = SimulatedEmailSender()
        self.api = LocalReviewApi(email_sender=self.email)
        state = self.api._cases["TR-260714-018"].state
        vendor = next(
            item
            for item in self.api.list_vendors()["items"]
            if item["name"].casefold() == state.case_input.vendor_name.casefold()
        )
        contact = self.api.create_vendor_contact(
            {"vendor_id": vendor["vendor_id"], "name": "Reminder Contact", "email": "remind@vendor.example"}
        )
        self.api.issue_vendor_invite("TR-260714-018", {"contact_id": contact["contact_id"]})

    def test_sweep_emails_specific_missing_items_once_per_interval(self) -> None:
        result = self.api.run_reminder_sweep()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["sent"][0]["case_id"], "TR-260714-018")
        self.assertEqual(result["sent"][0]["delivery"], "simulated")
        message = self.email.sent[0]
        self.assertEqual(message["to"], "remind@vendor.example")
        self.assertIn("Reminder: evidence still needed", message["subject"])
        self.assertIn("Evidence files", message["body"])
        self.assertIn("reply", message["body"].lower())
        events = self.api.integration_events()["items"]
        reminders = [item for item in events if item["event_type"] == "email.reminder"]
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0]["detail"]["recipient"], "remind@vendor.example")

        # Within the weekly interval the sweep is a no-op.
        second = self.api.run_reminder_sweep()
        self.assertEqual(second["count"], 0)
        self.assertEqual(len(self.email.sent), 1)


if __name__ == "__main__":
    unittest.main()
