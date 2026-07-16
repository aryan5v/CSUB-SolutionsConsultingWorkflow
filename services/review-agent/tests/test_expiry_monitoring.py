"""Post-approval expiry monitoring and scoped re-review tests (issue #53)."""

from __future__ import annotations

import datetime
import hashlib
import unittest
import zoneinfo

import _bootstrap  # noqa: F401

from review_agent.adapters.email import SimulatedEmailSender
from review_agent.adapters.storage import InMemoryStorage
from review_agent.api import LocalReviewApi
from review_agent.contracts.vendor import (
    CaseLifecycle,
    EvidenceExpiryRecord,
    EvidenceValidationFinding,
    RenewalRecord,
)
from review_agent.evidence.validation import compute_expires_on
from review_agent.profiles.service import ReviewProfileService
from review_agent.vendor.repository import InMemoryVendorRepository
from review_agent.vendor.service import VendorBackend


class MutableClock:
    def __init__(self, value: datetime.datetime | None = None) -> None:
        self.value = value or datetime.datetime(2026, 7, 14, 12, tzinfo=datetime.timezone.utc)

    def __call__(self) -> datetime.datetime:
        return self.value


CRITERIA = [
    {
        "requirement_id": "INS.COI.001",
        "question": "Provide a certificate of insurance listing cyber-liability coverage.",
        "source_citation": {"source_id": "policy:insurance", "cell": "A1"},
        "expected_evidence": ["COI"],
        "output_fields": ["insurance_summary"],
        "remediation_guidance": "Provide a current COI with cyber-liability coverage.",
    },
]

# 2026-07-14 clock + 60-day window: expires 2026-09-12 is exactly 60 days out.
COI_EXPIRING = """CERTIFICATE OF INSURANCE
coverage: cyber liability
expires_date: 2026-09-12
"""

COI_REFRESHED = """CERTIFICATE OF INSURANCE
coverage: cyber liability
expires_date: 2027-09-12
"""


class ExpiryComputationTests(unittest.TestCase):
    def test_next_check_dates_derive_only_from_validated_fields(self) -> None:
        self.assertEqual(
            compute_expires_on("coi", {"expires_date": "2026-09-12"}),
            datetime.date(2026, 9, 12),
        )
        self.assertEqual(
            compute_expires_on("pentest", {"report_date": "2026-05-01"}),
            datetime.date(2026, 5, 1) + datetime.timedelta(days=365),
        )
        # PCI has NO authoritative currency rule (issue #36 open question;
        # issue #52): no expiry date may be computed — PCI AoCs route to the
        # explicit pci.currency_unverified manual-review state at intake.
        self.assertIsNone(compute_expires_on("pci", {"assessment_date": "2026-03-01"}))
        self.assertIsNone(compute_expires_on("coi", {"coverages": ["cyber liability"]}))
        self.assertIsNone(compute_expires_on("pentest", {"report_date": "not a date"}))
        self.assertIsNone(compute_expires_on("soc2", {"issued_date": "2026-01-01"}))


class ExpiryMonitoringBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        self.repository = InMemoryVendorRepository()
        self.profiles = ReviewProfileService(self.repository, clock=self.clock)
        profile = self.profiles.create_draft("insurance", CRITERIA)
        self.profiles.fixture_test(profile.profile_version_id)
        self.profiles.activate(profile.profile_version_id)
        self.storage = InMemoryStorage()
        tokens = iter([letter * 43 for letter in "ABCDEFGH"])
        self.backend = VendorBackend(
            self.repository,
            self.profiles,
            clock=self.clock,
            token_factory=lambda: next(tokens),
            evidence_storage=self.storage,
        )
        vendor = self.backend.create_vendor("Example Vendor", "vendor.example")
        self.product = self.backend.create_product(vendor.vendor_id, "Example Product")
        self.contact = self.backend.create_contact(
            vendor.vendor_id, "Vendor Contact", "contact@vendor.example"
        )
        self.case_id = "CASE-1"
        self.backend.register_case(
            self.case_id, self.product.product_id, "Course scheduling", "public web scope"
        )
        self.token = self.approve_with_coi(self.case_id, COI_EXPIRING)

    def upload(self, token: str, filename: str, text: str) -> None:
        body = text.encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        self.storage.put_object(key=f"evidence/{digest}", body=body)
        self.backend.add_evidence(
            token,
            {
                "filename": filename,
                "content_type": "text/plain",
                "size_bytes": len(body),
                "sha256": digest,
            },
        )

    def approve_with_coi(self, case_id: str, coi_text: str) -> str:
        token = self.backend.issue_invite(case_id, self.contact.contact_id)["token"]
        self.upload(token, "coi-acme.txt", coi_text)
        self.backend.set_trust_center_url(token, "https://trust.vendor.example/security")
        self.backend.run_intake_analysis(token)
        self.backend.finalize_submission(token)
        self.backend.transition_case(case_id, CaseLifecycle.NEEDS_REVIEW)
        self.backend.transition_case(case_id, CaseLifecycle.APPROVED)
        return token

    def notice_and_record(
        self, delivery: str = "simulated"
    ) -> list[dict]:
        """Run one sweep tick the way the API layer does: claim before each side
        effect, then record every action (issue #37 claim pattern)."""
        actions = self.backend.expiry_actions()
        for action in actions:
            if action["kind"] == "notice":
                if not self.backend.claim_expiry_notice(
                    dedupe_key=action["dedupe_key"],
                    case_id=action["case_id"],
                    expiry_id=action["expiry_id"],
                ):
                    continue
                self.backend.record_expiry_notice(
                    expiry_id=action["expiry_id"],
                    case_id=action["case_id"],
                    threshold=str(action["threshold"]),
                    summary="notice",
                    delivery={"delivery": delivery, "simulated": True, "channel": "email"},
                    dedupe_key=action["dedupe_key"],
                )
            else:
                if not self.backend.claim_renewal(
                    dedupe_key=action["renewal_dedupe_key"], case_id=action["case_id"]
                ):
                    continue
                self.backend.register_case(
                    action["renewal_case_id"],
                    self.product.product_id,
                    "Scoped re-review",
                    "renewal scope",
                )
                self.backend.record_renewal(
                    source_case_id=action["case_id"],
                    renewal_case_id=action["renewal_case_id"],
                    expired_evidence_types=action["expired_evidence_types"],
                    sequence=action.get("renewal_sequence"),
                )
        return actions

    def test_lead_time_notices_fire_once_each_at_60_30_7(self) -> None:
        [item] = self.backend.expiry_status()
        self.assertEqual(item["state"], "expiring")
        self.assertEqual(item["days_until_expiry"], 60)

        actions = self.notice_and_record()
        self.assertEqual([a["threshold"] for a in actions], [60])
        self.assertEqual(actions[0]["contact_email"], "contact@vendor.example")
        # Retry the same day: deduplicated, nothing new fires.
        self.assertEqual(self.backend.expiry_actions(), [])

        self.clock.value += datetime.timedelta(days=31)  # 29 days out
        self.assertEqual([a["threshold"] for a in self.notice_and_record()], [30])
        self.clock.value += datetime.timedelta(days=23)  # 6 days out
        self.assertEqual([a["threshold"] for a in self.notice_and_record()], [7])
        self.assertEqual(self.backend.expiry_actions(), [])

    def test_first_sweep_close_to_expiry_sends_only_the_tightest_notice(self) -> None:
        self.clock.value += datetime.timedelta(days=55)  # 5 days out, nothing sent yet
        actions = self.backend.expiry_actions()
        self.assertEqual([a["threshold"] for a in actions], [7])

    def test_expiration_opens_one_scoped_renewal_and_never_touches_the_approval(self) -> None:
        self.clock.value += datetime.timedelta(days=61)  # expired yesterday
        actions = self.notice_and_record()
        kinds = sorted(a["kind"] for a in actions)
        self.assertEqual(kinds, ["notice", "open_renewal"])
        renewal = next(a for a in actions if a["kind"] == "open_renewal")
        self.assertEqual(renewal["renewal_case_id"], "CASE-1-R01")
        self.assertEqual(renewal["expired_evidence_types"], ["coi"])
        # The historical approval is projected as expired, not revoked.
        self.assertEqual(self.backend.get_case_lifecycle(self.case_id), "approved")
        [item] = self.backend.expiry_status()
        self.assertEqual(item["state"], "expired")
        self.assertEqual(item["renewal_case_id"], "CASE-1-R01")
        # Retry: no duplicate renewal, no duplicate expired notice.
        self.assertEqual(self.backend.expiry_actions(), [])

    def test_replacement_evidence_recomputes_and_stops_notices(self) -> None:
        self.clock.value += datetime.timedelta(days=61)
        self.notice_and_record()  # opens CASE-1-R01
        # Vendor refreshes the COI on the renewal case.
        renewal_token = self.backend.issue_invite("CASE-1-R01", self.contact.contact_id)["token"]
        self.upload(renewal_token, "coi-acme-renewed.txt", COI_REFRESHED)
        self.backend.set_trust_center_url(
            renewal_token, "https://trust.vendor.example/security"
        )
        self.backend.run_intake_analysis(renewal_token)
        [item] = self.backend.expiry_status()
        self.assertEqual(item["state"], "current")
        self.assertEqual(item["expires_on"], "2027-09-12")
        self.assertTrue(item["superseded_expiry_ids"])
        self.assertEqual(self.backend.expiry_actions(), [])

    def test_unmonitored_cases_and_missing_dates_produce_nothing(self) -> None:
        # A draft case with a dateless document is never monitored: the document
        # fails validation, so no expiry record exists and the sweep is empty.
        self.backend.register_case(
            "CASE-2", self.product.product_id, "Second use", "internal scope"
        )
        token = self.backend.issue_invite("CASE-2", self.contact.contact_id)["token"]
        self.upload(token, "penetration-test-report.txt", "PENETRATION TEST REPORT\nno dates\n")
        self.backend.set_trust_center_url(token, "https://trust.vendor.example/security")
        self.backend.run_intake_analysis(token)
        case_ids = {item["case_id"] for item in self.backend.expiry_status()}
        self.assertEqual(case_ids, {self.case_id})

    def test_timezone_aware_clock_is_normalized_to_utc_dates(self) -> None:
        pacific = zoneinfo.ZoneInfo("America/Los_Angeles")
        self.clock.value = datetime.datetime(2026, 7, 14, 18, 30, tzinfo=pacific)
        [item] = self.backend.expiry_status()
        # 18:30 Pacific is already 2026-07-15 UTC, so one day closer to expiry.
        self.assertEqual(item["days_until_expiry"], 59)

    def refresh_coi_on(self, case_id: str, text: str) -> None:
        token = self.backend.issue_invite(case_id, self.contact.contact_id)["token"]
        self.upload(token, "coi-acme-renewed.txt", text)
        self.backend.set_trust_center_url(token, "https://trust.vendor.example/security")
        self.backend.run_intake_analysis(token)

    # Finding 2: failed sends are retried; only successful sends dedup.
    def test_failed_notice_is_retried_next_sweep_then_success_dedups(self) -> None:
        # First sweep delivers nothing (failed) — the cadence is NOT satisfied.
        [action] = self.notice_and_record(delivery="failed")
        self.assertEqual(action["threshold"], 60)
        # Same-day retry re-issues the 60-day notice because the prior claim is
        # failed with attempts remaining.
        retried = self.backend.expiry_actions()
        self.assertEqual([a["threshold"] for a in retried], [60])
        # This time it succeeds and settles the claim as sent.
        self.notice_and_record(delivery="simulated")
        # Now it is deduplicated: nothing further fires.
        self.assertEqual(self.backend.expiry_actions(), [])

    # Finding 3: only OPEN renewals block; a completed R01 lets R02 open later.
    def test_completed_renewal_allows_a_second_renewal_when_evidence_expires_again(
        self,
    ) -> None:
        self.clock.value += datetime.timedelta(days=61)  # COI expired
        self.notice_and_record()  # opens CASE-1-R01 (sequence 1)
        r01 = next(
            r for r in self.backend._list("renewal", RenewalRecord) if r.sequence == 1
        )
        self.assertEqual(r01.state, "open")
        # Vendor refreshes on the renewal case → R01 completes.
        self.refresh_coi_on("CASE-1-R01", COI_REFRESHED)
        r01 = next(
            r for r in self.backend._list("renewal", RenewalRecord) if r.sequence == 1
        )
        self.assertEqual(r01.state, "completed")
        [item] = self.backend.expiry_status()
        self.assertEqual(item["state"], "current")
        # Advance past the refreshed COI's own expiry (2027-09-12).
        self.clock.value = datetime.datetime(2027, 9, 13, 12, tzinfo=datetime.timezone.utc)
        [item] = self.backend.expiry_status()
        self.assertEqual(item["state"], "expired")
        self.assertIsNone(item["renewal_case_id"])  # no OPEN renewal blocks it
        self.notice_and_record()  # opens CASE-1-R02
        sequences = sorted(r.sequence for r in self.backend._list("renewal", RenewalRecord))
        self.assertEqual(sequences, [1, 2])
        r02 = next(
            r for r in self.backend._list("renewal", RenewalRecord) if r.sequence == 2
        )
        self.assertEqual(r02.renewal_case_id, "CASE-1-R02")
        self.assertEqual(r02.state, "open")

    # Finding 4: interleaved/repeated sweeps commit exactly one notice + case.
    def test_interleaved_sweeps_send_one_notice_and_open_one_renewal(self) -> None:
        self.clock.value += datetime.timedelta(days=61)  # expired
        # Two concurrent sweeps each compute their work from the same snapshot,
        # before either performs a side effect.
        batch_a = self.backend.expiry_actions()
        batch_b = self.backend.expiry_actions()
        committed_notices = 0
        committed_renewals = 0
        for batch in (batch_a, batch_b):
            for action in batch:
                if action["kind"] == "notice":
                    if self.backend.claim_expiry_notice(
                        dedupe_key=action["dedupe_key"],
                        case_id=action["case_id"],
                        expiry_id=action["expiry_id"],
                    ):
                        self.backend.record_expiry_notice(
                            expiry_id=action["expiry_id"],
                            case_id=action["case_id"],
                            threshold=str(action["threshold"]),
                            summary="notice",
                            delivery={"delivery": "simulated", "simulated": True},
                            dedupe_key=action["dedupe_key"],
                        )
                        committed_notices += 1
                else:
                    if self.backend.claim_renewal(
                        dedupe_key=action["renewal_dedupe_key"], case_id=action["case_id"]
                    ):
                        self.backend.register_case(
                            action["renewal_case_id"],
                            self.product.product_id,
                            "Scoped re-review",
                            "renewal scope",
                        )
                        self.backend.record_renewal(
                            source_case_id=action["case_id"],
                            renewal_case_id=action["renewal_case_id"],
                            expired_evidence_types=action["expired_evidence_types"],
                            sequence=action.get("renewal_sequence"),
                        )
                        committed_renewals += 1
        self.assertEqual(committed_notices, 1)
        self.assertEqual(committed_renewals, 1)
        renewals = self.backend._list("renewal", RenewalRecord)
        self.assertEqual(len(renewals), 1)

    # Finding 5: renewal IDs never collide even after a chain record is removed.
    def test_next_renewal_sequence_never_reuses_a_deleted_index(self) -> None:
        for case_id, seq in (("CASE-1-R01", 1), ("CASE-1-R02", 2)):
            self.backend.register_case(
                case_id, self.product.product_id, "Scoped re-review", "renewal scope"
            )
            self.backend.record_renewal(
                source_case_id=self.case_id,
                renewal_case_id=case_id,
                expired_evidence_types=["coi"],
                sequence=seq,
            )
        r01 = next(
            r for r in self.backend._list("renewal", RenewalRecord) if r.sequence == 1
        )
        self.backend.repository.delete(
            "renewal", r01.renewal_id, workspace_id=self.backend.workspace_id
        )
        # len(existing)+1 would collide with the surviving R02; max+1 does not.
        self.assertEqual(self.backend._next_renewal_sequence(self.case_id), 3)

    # Finding 5: monitoring contact follows the active renewal chain's contact.
    def test_monitoring_contact_follows_the_active_renewal_chain(self) -> None:
        self.clock.value += datetime.timedelta(days=61)  # expired
        self.notice_and_record()  # opens CASE-1-R01
        renewal_contact = self.backend.create_contact(
            self.product.vendor_id, "Renewal Contact", "renewal@vendor.example"
        )
        self.backend.issue_invite("CASE-1-R01", renewal_contact.contact_id)
        contact = self.backend._monitoring_contact(self.case_id)
        self.assertEqual(contact["contact_email"], "renewal@vendor.example")
        self.assertEqual(contact["contact_id"], renewal_contact.contact_id)

    # Finding 6: expiry records carry approval scope, contact, versions, state.
    def test_expiry_record_carries_full_approval_context(self) -> None:
        [record] = self.backend._list("expiry", EvidenceExpiryRecord)
        self.assertEqual(record.approval_scope["product_id"], self.product.product_id)
        self.assertTrue(record.profile_version_ids)
        self.assertEqual(record.approval_scope["profile_version_ids"], list(record.profile_version_ids))
        self.assertEqual(record.contact_id, self.contact.contact_id)
        self.assertTrue(record.evidence_version)  # document SHA-256
        self.assertEqual(record.state, "active")
        [item] = self.backend.expiry_status()
        self.assertEqual(item["contact_id"], self.contact.contact_id)
        self.assertEqual(item["record_state"], "active")
        self.assertTrue(item["profile_version_ids"])

    # Finding 6: refreshed evidence marks the superseded record explicitly.
    def test_superseded_record_state_is_persisted(self) -> None:
        self.clock.value += datetime.timedelta(days=61)
        self.notice_and_record()
        self.refresh_coi_on("CASE-1-R01", COI_REFRESHED)
        states = sorted(
            r.state for r in self.backend._list("expiry", EvidenceExpiryRecord)
        )
        self.assertEqual(states, ["active", "superseded"])

    # Finding 7: PCI evidence never yields a scheduled expiry; it routes to
    # explicit manual review (issue #52 — no authoritative currency rule).
    def test_pci_evidence_never_schedules_an_expiry(self) -> None:
        self.backend.register_case(
            "CASE-PCI", self.product.product_id, "PCI use", "scope"
        )
        token = self.backend.issue_invite("CASE-PCI", self.contact.contact_id)["token"]
        self.upload(
            token,
            "pci-aoc.txt",
            "ATTESTATION OF COMPLIANCE\nassessment_date: 2026-03-01\n",
        )
        self.backend.set_trust_center_url(token, "https://trust.vendor.example/security")
        self.backend.run_intake_analysis(token)
        pci_expiry = [
            r
            for r in self.backend._list("expiry", EvidenceExpiryRecord)
            if r.case_id == "CASE-PCI"
        ]
        self.assertEqual(pci_expiry, [])
        checks = {
            f.check
            for f in self.backend._list("finding", EvidenceValidationFinding)
            if f.evidence_type == "pci"
        }
        self.assertIn("pci.currency_unverified", checks)


class ExpirySweepApiTests(unittest.TestCase):
    def test_sweep_emails_notifies_and_opens_renewal_in_the_queue(self) -> None:
        email = SimulatedEmailSender()
        api = LocalReviewApi(email_sender=email)
        backend = api._vendor
        case_id = "TR-260714-018"
        state = api._cases[case_id].state
        vendor = next(
            item
            for item in api.list_vendors()["items"]
            if item["name"].casefold() == state.case_input.vendor_name.casefold()
        )
        contact = api.create_vendor_contact(
            {"vendor_id": vendor["vendor_id"], "name": "Expiry Contact", "email": "expiry@vendor.example"}
        )
        api.issue_vendor_invite(case_id, {"contact_id": contact["contact_id"]})
        backend.transition_case(case_id, CaseLifecycle.NEEDS_REVIEW)
        backend.transition_case(case_id, CaseLifecycle.APPROVED)
        submission = next(
            item
            for item in api._vendor_repository.list("submission", workspace_id=backend.workspace_id)
            if item.case_id == case_id
        )
        # Seed an already-expired validated record directly; the intake path is
        # covered by the backend tests above.
        from review_agent.contracts.vendor import EvidenceExpiryRecord

        record = EvidenceExpiryRecord(
            expiry_id="expiry-0001",
            case_id=case_id,
            submission_id=submission.submission_id,
            artifact_id="evidence-0001",
            filename="coi-expired.txt",
            evidence_type="coi",
            expires_on="2026-06-30",
            source_citation={"source_id": "issue:53"},
        )
        api._vendor_repository.put(
            "expiry", record.expiry_id, record, workspace_id=backend.workspace_id
        )

        result = api.run_expiry_sweep()
        self.assertEqual(len(result["notices"]), 1)
        self.assertEqual(result["notices"][0]["threshold"], "expired")
        self.assertEqual(result["renewals_opened"][0]["renewal_case_id"], f"{case_id}-R01")
        self.assertEqual(email.sent[0]["to"], "expiry@vendor.example")
        self.assertIn("expired", email.sent[0]["subject"])
        events = {item["event_type"] for item in api.integration_events()["items"]}
        self.assertIn("evidence.expiry_notice", events)
        self.assertIn("renewal.case_opened", events)
        # The renewal case is a full case: it appears in the review queue and
        # the reviewer can issue an invite for refreshed evidence.
        queue_ids = {item["case_id"] for item in api.list_review_queue()["items"]}
        self.assertIn(f"{case_id}-R01", queue_ids)
        issued = api.issue_vendor_invite(
            f"{case_id}-R01", {"contact_id": contact["contact_id"]}
        )
        self.assertIn("token", issued)
        # Idempotent retry: nothing further happens.
        second = api.run_expiry_sweep()
        self.assertEqual(second["count"], 0)
        self.assertEqual(len(email.sent), 1)


if __name__ == "__main__":
    unittest.main()
