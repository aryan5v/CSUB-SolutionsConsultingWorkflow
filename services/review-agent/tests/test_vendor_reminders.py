"""Weekly vendor reminder tests: cadence, idempotency, and stop conditions (issue #37)."""

from __future__ import annotations

import datetime
import hashlib
import json
import unittest
from dataclasses import replace

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


class FlakyEmailSender:
    """Fails the first ``failures`` sends, then delegates to a simulated sender."""

    def __init__(self, failures: int = 1) -> None:
        self._failures = failures
        self._delegate = SimulatedEmailSender()
        self.sent = self._delegate.sent

    def send(self, *, to: str, subject: str, body: str) -> dict:
        if self._failures > 0:
            self._failures -= 1
            raise ConnectionError("smtp unavailable")
        return self._delegate.send(to=to, subject=subject, body=body)


class MalformedEmailSender:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    def send(self, *, to: str, subject: str, body: str) -> object:
        del to, subject, body
        self.calls += 1
        return self.result


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

WEEK = datetime.timedelta(days=7)


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

    def send_due_reminders(self, *, delivery: str = "simulated") -> list[dict]:
        due = self.backend.reminder_candidates()
        sent = []
        for candidate in due:
            if not self.backend.claim_reminder(
                dedupe_key=candidate["dedupe_key"],
                case_id=candidate["case_id"],
                invite_id=candidate["invite_id"],
            ):
                continue
            self.backend.record_reminder(
                invite_id=candidate["invite_id"],
                case_id=candidate["case_id"],
                dedupe_key=candidate["dedupe_key"],
                summary="reminder",
                delivery={
                    "delivery": delivery,
                    "simulated": delivery == "simulated",
                    "channel": "email",
                    "to": candidate["contact_email"],
                },
            )
            sent.append(candidate)
        return sent

    def test_naive_invite_timestamps_are_interpreted_as_utc(self) -> None:
        invite = self.backend.list_invites("CASE-1")[0]
        issued = datetime.datetime.fromisoformat(invite.issued_at).replace(tzinfo=None)
        expires = datetime.datetime.fromisoformat(invite.expires_at).replace(tzinfo=None)
        self.repository.put(
            "invite",
            invite.invite_id,
            replace(
                invite,
                issued_at=issued.isoformat(),
                expires_at=expires.isoformat(),
            ),
            workspace_id=invite.workspace_id,
        )
        self.clock.value += WEEK + datetime.timedelta(seconds=1)
        [candidate] = self.backend.reminder_candidates()
        self.assertEqual(candidate["dedupe_key"], "reminder:CASE-1:1")

    def test_skipped_and_unknown_modes_do_not_satisfy_cadence(self) -> None:
        self.clock.value += WEEK + datetime.timedelta(seconds=1)
        self.assertEqual(len(self.send_due_reminders(delivery="skipped")), 1)
        self.assertEqual(len(self.backend.reminder_candidates()), 1)
        self.assertEqual(len(self.send_due_reminders(delivery="mystery")), 1)
        self.assertEqual(len(self.backend.reminder_candidates()), 1)
        self.assertEqual(len(self.send_due_reminders()), 1)
        self.assertEqual(self.backend.reminder_candidates(), [])

    def test_new_invitation_is_due_only_after_the_configured_interval(self) -> None:
        # Finding 3: never immediately eligible.
        self.assertEqual(self.backend.reminder_candidates(), [])
        self.clock.value += datetime.timedelta(days=6)
        self.assertEqual(self.backend.reminder_candidates(), [])
        self.clock.value += datetime.timedelta(days=1, seconds=1)
        [candidate] = self.backend.reminder_candidates()
        self.assertEqual(candidate["case_id"], "CASE-1")

    def test_nothing_submitted_names_submission_gaps(self) -> None:
        self.clock.value += WEEK + datetime.timedelta(seconds=1)
        [candidate] = self.backend.reminder_candidates()
        self.assertEqual(candidate["contact_email"], "contact@vendor.example")
        self.assertEqual(candidate["stage"], "awaiting_submission")
        self.assertEqual(candidate["dedupe_key"], "reminder:CASE-1:1")
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
        self.clock.value += WEEK + datetime.timedelta(seconds=1)
        [candidate] = self.backend.reminder_candidates()
        self.assertEqual(candidate["stage"], "questions_open")
        self.assertEqual(
            [(item["requirement_id"], item["label"]) for item in candidate["missing"]],
            [("A11Y.VPAT.001", "VPAT")],
        )
        self.assertEqual(candidate["missing"][0]["detail"], "Provide a current VPAT.")

    def test_weekly_cadence_is_enforced(self) -> None:
        self.clock.value += WEEK + datetime.timedelta(seconds=1)
        self.assertEqual(len(self.send_due_reminders()), 1)
        self.assertEqual(self.backend.reminder_candidates(), [])
        self.clock.value += datetime.timedelta(days=3)
        self.assertEqual(self.backend.reminder_candidates(), [])
        self.clock.value += datetime.timedelta(days=4, seconds=1)
        self.assertEqual(len(self.send_due_reminders()), 1)

    def test_interleaved_sweeps_send_exactly_once(self) -> None:
        # Finding 1: two sweeps select the same candidate; only the first
        # claim wins, so the second sweep sends nothing.
        self.clock.value += WEEK + datetime.timedelta(seconds=1)
        [first] = self.backend.reminder_candidates()
        [second] = self.backend.reminder_candidates()
        self.assertEqual(first["dedupe_key"], second["dedupe_key"])
        self.assertTrue(
            self.backend.claim_reminder(
                dedupe_key=first["dedupe_key"],
                case_id=first["case_id"],
                invite_id=first["invite_id"],
            )
        )
        self.assertFalse(
            self.backend.claim_reminder(
                dedupe_key=second["dedupe_key"],
                case_id=second["case_id"],
                invite_id=second["invite_id"],
            )
        )
        # A pending claim also hides the case from later candidate selection.
        self.assertEqual(self.backend.reminder_candidates(), [])

    def test_failed_delivery_is_retried_and_never_satisfies_the_cadence(self) -> None:
        # Finding 2: a failed attempt is recorded but the next sweep retries.
        self.clock.value += WEEK + datetime.timedelta(seconds=1)
        self.assertEqual(len(self.send_due_reminders(delivery="failed")), 1)
        [retry] = self.backend.reminder_candidates()
        self.assertEqual(retry["dedupe_key"], "reminder:CASE-1:1")
        # A delivered retry satisfies the period.
        self.assertEqual(len(self.send_due_reminders()), 1)
        self.assertEqual(self.backend.reminder_candidates(), [])
        # Both attempts stay queryable, with truthful delivery results.
        history = self.backend.reminder_history("CASE-1")
        self.assertEqual(
            [item["delivery"] for item in history["items"]], ["failed", "simulated"]
        )

    def test_failed_deliveries_are_bounded_per_period(self) -> None:
        self.clock.value += WEEK + datetime.timedelta(seconds=1)
        for _ in range(VendorBackend.MAX_REMINDER_ATTEMPTS):
            self.assertEqual(len(self.send_due_reminders(delivery="failed")), 1)
        self.assertEqual(self.backend.reminder_candidates(), [])

    def test_one_reminder_per_case_with_multiple_active_invites(self) -> None:
        # Finding 4: the most recently issued invitation is authoritative.
        vendor_id = self.contact.vendor_id
        newer_contact = self.backend.create_contact(
            vendor_id, "Newer Contact", "newer@vendor.example"
        )
        self.clock.value += datetime.timedelta(hours=1)
        self.backend.issue_invite("CASE-1", newer_contact.contact_id)
        self.clock.value += WEEK + datetime.timedelta(seconds=1)
        [candidate] = self.backend.reminder_candidates()
        self.assertEqual(candidate["contact_email"], "newer@vendor.example")

    def test_pause_and_resume_control_reminders(self) -> None:
        self.clock.value += WEEK + datetime.timedelta(seconds=1)
        self.backend.set_reminders_paused("CASE-1", True)
        self.assertEqual(self.backend.reminder_candidates(), [])
        self.assertTrue(self.backend.reminder_history("CASE-1")["paused"])
        self.backend.set_reminders_paused("CASE-1", False)
        self.assertEqual(len(self.backend.reminder_candidates()), 1)

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
        self.clock.value += WEEK + datetime.timedelta(seconds=1)
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
        self.clock.value += WEEK + datetime.timedelta(seconds=1)
        self.assertEqual(self.backend.reminder_candidates(), [])

        # A case the reviewer has taken over (needs_review onward) stops reminders
        # even if the invite itself was never finalized.
        self.backend.register_case(
            "CASE-3", self.product.product_id, "Third use", "internal scope"
        )
        self.backend.issue_invite("CASE-3", self.contact.contact_id)
        self.clock.value += WEEK + datetime.timedelta(seconds=1)
        self.assertEqual(len(self.backend.reminder_candidates()), 1)
        self.backend.transition_case("CASE-3", CaseLifecycle.NEEDS_REVIEW)
        self.assertEqual(self.backend.reminder_candidates(), [])

    def test_expired_invites_are_not_reminded(self) -> None:
        self.clock.value += datetime.timedelta(days=61)
        self.assertEqual(self.backend.reminder_candidates(), [])


class ReminderSweepApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        self.email = SimulatedEmailSender()
        self.api = self._build_api(self.email)

    def _build_api(self, email_sender) -> LocalReviewApi:
        api = LocalReviewApi(email_sender=email_sender, clock=self.clock)
        # The default one-week invite TTL would expire the invite at the very
        # moment the first weekly reminder comes due; give it room to be nagged.
        api._vendor.invite_ttl = datetime.timedelta(days=60)
        state = api._cases["TR-260714-018"].state
        vendor = next(
            item
            for item in api.list_vendors()["items"]
            if item["name"].casefold() == state.case_input.vendor_name.casefold()
        )
        contact = api.create_vendor_contact(
            {"vendor_id": vendor["vendor_id"], "name": "Reminder Contact", "email": "remind@vendor.example"}
        )
        self.invite_token = api.issue_vendor_invite(
            "TR-260714-018", {"contact_id": contact["contact_id"]}
        )["token"]
        return api

    def test_sweep_emails_specific_missing_items_once_per_interval(self) -> None:
        # A brand-new invitation is not yet due (finding 3).
        self.assertEqual(self.api.run_reminder_sweep()["count"], 0)
        self.clock.value += datetime.timedelta(days=7, seconds=1)
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
        detail = reminders[0]["detail"]
        self.assertEqual(detail["dedupe_key"], "reminder:TR-260714-018:1")
        self.assertNotIn("recipient", detail)
        self.assertEqual(len(detail["recipient_sha256"]), 64)

        # Within the weekly interval a repeated sweep is a no-op (finding 1).
        second = self.api.run_reminder_sweep()
        self.assertEqual(second["count"], 0)
        self.assertEqual(len(self.email.sent), 1)

    def test_reminder_email_contains_the_scoped_invitation_link(self) -> None:
        # Finding 5: the body carries the token-scoped intake URL and nothing
        # more sensitive than that single capability link.
        self.clock.value += datetime.timedelta(days=7, seconds=1)
        self.assertEqual(self.api.run_reminder_sweep()["count"], 1)
        body = self.email.sent[0]["body"]
        self.assertIn(f"https://vetted.invalid/intake#token={self.invite_token}", body)
        invite = self.api.list_case_invites("TR-260714-018")["items"][0]
        for leak in (invite["invite_id"], "token_hash"):
            self.assertNotIn(leak, body)

    def test_failed_send_is_recorded_and_retried_next_sweep(self) -> None:
        # Finding 2 at the API level: the flaky first send fails, is recorded
        # truthfully, and the very next sweep retries and succeeds.
        flaky = FlakyEmailSender(failures=1)
        api = self._build_api(flaky)
        self.clock.value += datetime.timedelta(days=7, seconds=1)
        first = api.run_reminder_sweep()
        self.assertEqual(first["sent"][0]["delivery"], "failed")
        self.assertEqual(flaky.sent, [])
        retry = api.run_reminder_sweep()
        self.assertEqual(retry["sent"][0]["delivery"], "simulated")
        self.assertEqual(len(flaky.sent), 1)
        # Once delivered, the cadence is satisfied.
        self.assertEqual(api.run_reminder_sweep()["count"], 0)
        history = api.reminder_history("TR-260714-018")
        self.assertEqual([item["delivery"] for item in history["items"]], ["failed", "simulated"])

    def test_malformed_sender_results_fail_safely_and_are_bounded(self) -> None:
        for raw_result in (None, "unexpected"):
            with self.subTest(raw_result=raw_result):
                self.clock = MutableClock()
                sender = MalformedEmailSender(raw_result)
                api = self._build_api(sender)
                self.clock.value += datetime.timedelta(days=7, seconds=1)
                for _ in range(VendorBackend.MAX_REMINDER_ATTEMPTS):
                    attempt = api.run_reminder_sweep()
                    self.assertEqual(attempt["count"], 1)
                    self.assertEqual(attempt["sent"][0]["delivery"], "failed")
                self.assertEqual(api.run_reminder_sweep()["count"], 0)
                self.assertEqual(sender.calls, VendorBackend.MAX_REMINDER_ATTEMPTS)
                reminder_events = [
                    item
                    for item in api.integration_events()["items"]
                    if item["event_type"] == "email.reminder"
                ]
                expected = hashlib.sha256(b"remind@vendor.example").hexdigest()
                self.assertTrue(
                    all(item["detail"]["recipient_sha256"] == expected for item in reminder_events)
                )
                self.assertNotIn("remind@vendor.example", json.dumps(reminder_events))

    def test_reviewer_can_pause_resume_and_inspect_history(self) -> None:
        self.clock.value += datetime.timedelta(days=7, seconds=1)
        self.assertEqual(self.api.set_reminders_paused("TR-260714-018", True)["paused"], True)
        self.assertEqual(self.api.run_reminder_sweep()["count"], 0)
        self.assertTrue(self.api.reminder_history("TR-260714-018")["paused"])
        self.api.set_reminders_paused("TR-260714-018", False)
        self.assertEqual(self.api.run_reminder_sweep()["count"], 1)
        history = self.api.reminder_history("TR-260714-018")
        self.assertFalse(history["paused"])
        self.assertEqual(len(history["items"]), 1)
        self.assertEqual(history["items"][0]["delivery"], "simulated")


if __name__ == "__main__":
    unittest.main()
