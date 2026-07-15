"""Evidence content-validation tests: COI, pen test age, PCI currency (issue #36)."""

from __future__ import annotations

import base64
import datetime
import hashlib
import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.extraction import DeterministicEvidenceExtractor
from review_agent.adapters.storage import InMemoryStorage
from review_agent.evidence.validation import (
    classify_evidence_type,
    validate_evidence,
    validate_identity,
)
from review_agent.profiles.service import ReviewProfileService
from review_agent.vendor.repository import InMemoryVendorRepository
from review_agent.vendor.service import VendorBackend, VendorBackendError

TODAY = datetime.date(2026, 7, 14)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime.datetime(2026, 7, 14, 12, tzinfo=datetime.timezone.utc)

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
    {
        "requirement_id": "SEC.PENTEST.001",
        "question": "Provide a penetration test report from the last year.",
        "source_citation": {"source_id": "policy:security", "cell": "B2"},
        "expected_evidence": ["penetration test"],
        "output_fields": ["pentest_summary"],
        "remediation_guidance": "Provide a penetration test report no older than one year.",
    },
    {
        "requirement_id": "SEC.PCI.001",
        "question": "Provide a current PCI attestation of compliance.",
        "source_citation": {"source_id": "policy:pci", "cell": "C3"},
        "expected_evidence": ["PCI AoC"],
        "output_fields": ["pci_summary"],
        "remediation_guidance": "Provide a current PCI AoC.",
    },
]

EXPIRED_COI = """CERTIFICATE OF INSURANCE
coverage: cyber liability, general liability
expires_date: 2026-06-30
"""

VALID_COI = """CERTIFICATE OF INSURANCE
coverage: cyber liability, general liability
expires_date: 2027-06-30
"""

STALE_PENTEST = """PENETRATION TEST REPORT
report_date: 2025-06-01
authority: Example Security Labs
"""

STALE_AOC = """PCI DSS ATTESTATION OF COMPLIANCE
assessment_date: 2025-05-01
"""


class ValidationRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = DeterministicEvidenceExtractor()

    def fields(self, text: str, evidence_type: str) -> dict:
        return self.extractor.extract_fields(
            filename="doc.txt", content_type="text/plain", evidence_type=evidence_type, text=text
        )

    def test_classification_is_deterministic_filename_matching(self) -> None:
        self.assertEqual(classify_evidence_type("coi-acme-2026.pdf"), "coi")
        self.assertEqual(classify_evidence_type("Certificate-of-Insurance.pdf"), "coi")
        self.assertEqual(classify_evidence_type("CertificateOfInsurance.pdf"), "coi")
        self.assertEqual(classify_evidence_type("penetration-test-report-2025.pdf"), "pentest")
        self.assertEqual(classify_evidence_type("pci-aoc-2026.pdf"), "pci")
        self.assertIsNone(classify_evidence_type("soc2-report.pdf"))
        self.assertIsNone(classify_evidence_type("vpat-report.pdf"))

    def test_classification_requires_whole_tokens_not_substrings(self) -> None:
        # Regression: "coinbase" contains "coi" but is not a certificate of
        # insurance; short markers must match whole tokens only.
        self.assertIsNone(classify_evidence_type("coinbase_soc2.pdf"))
        self.assertIsNone(classify_evidence_type("capcicum-datasheet.pdf"))
        self.assertIsNone(classify_evidence_type("aocean-whitepaper.pdf"))
        self.assertIsNone(classify_evidence_type("carpentester-notes.pdf"))

    def test_expired_coi_produces_cited_failure(self) -> None:
        failures = validate_evidence(
            evidence_type="coi", fields=self.fields(EXPIRED_COI, "coi"), today=TODAY
        )
        self.assertEqual([item["check"] for item in failures], ["coi.expired"])
        self.assertIn("2026-06-30", failures[0]["reason"])

    def test_coi_without_cyber_liability_fails_that_check(self) -> None:
        text = "CERTIFICATE OF INSURANCE\ncoverage: general liability\nexpires_date: 2027-06-30\n"
        failures = validate_evidence(
            evidence_type="coi", fields=self.fields(text, "coi"), today=TODAY
        )
        self.assertEqual([item["check"] for item in failures], ["coi.cyber_liability_missing"])

    def test_thirteen_month_old_pentest_is_stale(self) -> None:
        failures = validate_evidence(
            evidence_type="pentest", fields=self.fields(STALE_PENTEST, "pentest"), today=TODAY
        )
        self.assertEqual([item["check"] for item in failures], ["pentest.stale"])
        self.assertIn("2025-06-01", failures[0]["reason"])

    def test_pci_attestation_routes_to_manual_review_not_an_invented_threshold(self) -> None:
        # The authoritative PCI currency rule is TBD (issue #36 open question;
        # issue #52): no age threshold may pass or fail an AoC automatically.
        for text in (STALE_AOC, "PCI DSS ATTESTATION OF COMPLIANCE\nassessment_date: 2026-03-01\n"):
            with self.subTest(text=text.splitlines()[1]):
                failures = validate_evidence(
                    evidence_type="pci", fields=self.fields(text, "pci"), today=TODAY
                )
                self.assertEqual([item["check"] for item in failures], ["pci.currency_unverified"])
                self.assertEqual(failures[0]["disposition"], "manual_review")
                self.assertIn("TBD", failures[0]["reason"])
                self.assertIn("issue #52", failures[0]["reason"])

    def test_negated_cyber_liability_is_absence_of_coverage(self) -> None:
        # Regression: "NOT COVERED" / "EXCLUDED" phrasings must not count as
        # positive coverage.
        negated_documents = (
            "CERTIFICATE OF INSURANCE\nCyber liability: NOT COVERED\nexpires_date: 2027-06-30\n",
            "CERTIFICATE OF INSURANCE\nCyber liability: EXCLUDED\nexpires_date: 2027-06-30\n",
            "CERTIFICATE OF INSURANCE\ncoverage: general liability\n"
            "Cyber liability is excluded under this policy.\nexpires_date: 2027-06-30\n",
            "CERTIFICATE OF INSURANCE\ncoverage: cyber liability (excluded), general liability\n"
            "expires_date: 2027-06-30\n",
        )
        for text in negated_documents:
            with self.subTest(text=text.splitlines()[1]):
                failures = validate_evidence(
                    evidence_type="coi", fields=self.fields(text, "coi"), today=TODAY
                )
                self.assertEqual(
                    [item["check"] for item in failures], ["coi.cyber_liability_missing"]
                )

    def test_current_documents_pass_confirmed_checks(self) -> None:
        current_pentest = "PENETRATION TEST REPORT\nreport_date: 2026-05-01\n"
        for evidence_type, text in (("coi", VALID_COI), ("pentest", current_pentest)):
            with self.subTest(evidence_type=evidence_type):
                self.assertEqual(
                    validate_evidence(
                        evidence_type=evidence_type,
                        fields=self.fields(text, evidence_type),
                        today=TODAY,
                    ),
                    [],
                )

    def test_unreadable_dates_route_to_manual_review(self) -> None:
        failures = validate_evidence(evidence_type="pentest", fields={"coverages": []}, today=TODAY)
        self.assertEqual([item["check"] for item in failures], ["pentest.date_unknown"])
        self.assertEqual(failures[0]["disposition"], "manual_review")

    def test_document_for_another_vendor_or_product_is_flagged_for_review(self) -> None:
        mismatch = validate_identity(
            fields={"vendor": "Other Corp", "product": "Different Tool"},
            vendor_name="Example Vendor",
            product_name="Example Product",
        )
        self.assertEqual(
            [item["check"] for item in mismatch],
            ["evidence.vendor_mismatch", "evidence.product_mismatch"],
        )
        self.assertTrue(all(item["disposition"] == "manual_review" for item in mismatch))
        # Partial-name overlap and absent fields are not mismatches.
        self.assertEqual(
            validate_identity(
                fields={"vendor": "Example Vendor, Inc.", "coverages": []},
                vendor_name="Example Vendor",
                product_name="Example Product",
            ),
            [],
        )


class IntakeValidationTests(unittest.TestCase):
    """Content validation gates auto-coverage during intake analysis."""

    def setUp(self) -> None:
        self.clock = MutableClock()
        self.repository = InMemoryVendorRepository()
        self.profiles = ReviewProfileService(self.repository, clock=self.clock)
        profile = self.profiles.create_draft("combined", CRITERIA)
        self.profiles.fixture_test(profile.profile_version_id)
        self.profiles.activate(profile.profile_version_id)
        self.storage = InMemoryStorage()
        tokens = iter([letter * 43 for letter in "ABCD"])
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
        self.backend.register_case(
            "CASE-1", self.product.product_id, "Course scheduling", "public web scope"
        )
        self.token = self.backend.issue_invite("CASE-1", self.contact.contact_id)["token"]
        self.backend.set_trust_center_url(self.token, "https://trust.vendor.example/security")

    def add_document(self, filename: str, text: str) -> None:
        body = text.encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        self.storage.put_object(key=f"evidence/{digest}", body=body)
        self.backend.add_evidence(
            self.token,
            {
                "filename": filename,
                "content_type": "text/plain",
                "size_bytes": len(body),
                "sha256": digest,
            },
        )

    def test_failing_documents_produce_findings_and_stay_unresolved(self) -> None:
        self.add_document("coi-acme.txt", EXPIRED_COI)
        self.add_document("penetration-test-report.txt", STALE_PENTEST)
        self.add_document("pci-aoc.txt", STALE_AOC)
        self.backend.run_intake_analysis(self.token)

        findings = self.backend.submission_findings(self.token)
        checks = sorted(item["check"] for item in findings)
        self.assertEqual(checks, ["coi.expired", "pci.currency_unverified", "pentest.stale"])
        for finding in findings:
            self.assertEqual(finding["source_citation"]["source_id"], "issue:36")
            self.assertTrue(finding["reason"])
            self.assertTrue(finding["filename"])
            self.assertIn(finding["disposition"], {"failed", "manual_review"})

        # None of the failing documents count as received: every requirement
        # stays unresolved, feeding the reminder flow and vendor checklist.
        unresolved = {
            item["requirement_id"] for item in self.backend.unresolved_questions(self.token)
        }
        self.assertEqual(unresolved, {"INS.COI.001", "SEC.PCI.001", "SEC.PENTEST.001"})

        reviewer_view = self.backend.case_evidence_findings("CASE-1")
        self.assertEqual(len(reviewer_view), 3)

    def test_valid_documents_cover_confirmed_requirements(self) -> None:
        self.add_document("coi-acme.txt", VALID_COI)
        self.add_document(
            "penetration-test-report.txt", "PENETRATION TEST REPORT\nreport_date: 2026-05-01\n"
        )
        self.add_document(
            "pci-aoc.txt", "PCI DSS ATTESTATION OF COMPLIANCE\nassessment_date: 2026-03-01\n"
        )
        self.backend.run_intake_analysis(self.token)
        # COI and pen-test rules are confirmed and pass; PCI currency has no
        # confirmed rule (issue #36/#52), so the AoC waits for a human instead
        # of auto-covering its requirement.
        findings = self.backend.submission_findings(self.token)
        self.assertEqual(
            [(item["check"], item["disposition"]) for item in findings],
            [("pci.currency_unverified", "manual_review")],
        )
        unresolved = {
            item["requirement_id"] for item in self.backend.unresolved_questions(self.token)
        }
        self.assertEqual(unresolved, {"SEC.PCI.001"})

    def test_rerunning_analysis_replaces_findings_instead_of_duplicating(self) -> None:
        self.add_document("coi-acme.txt", EXPIRED_COI)
        self.add_document("penetration-test-report.txt", STALE_PENTEST)
        self.backend.run_intake_analysis(self.token)
        first = self.backend.submission_findings(self.token)
        self.backend.run_intake_analysis(self.token)
        second = self.backend.submission_findings(self.token)
        self.assertEqual(len(first), 2)
        self.assertEqual(second, first)

    def test_document_for_another_vendor_is_rejected_from_auto_coverage(self) -> None:
        self.add_document(
            "coi-acme.txt",
            "CERTIFICATE OF INSURANCE\nvendor: Other Corp\n"
            "coverage: cyber liability\nexpires_date: 2027-06-30\n",
        )
        self.backend.run_intake_analysis(self.token)
        findings = self.backend.submission_findings(self.token)
        self.assertEqual(
            [(item["check"], item["disposition"]) for item in findings],
            [("evidence.vendor_mismatch", "manual_review")],
        )
        unresolved = {
            item["requirement_id"] for item in self.backend.unresolved_questions(self.token)
        }
        self.assertIn("INS.COI.001", unresolved)

    def test_inline_bytes_are_stored_and_validated_end_to_end(self) -> None:
        # The live upload path: bytes travel inline with the metadata, land
        # behind the storage seam, and content validation parses them.
        body = EXPIRED_COI.encode("utf-8")
        self.backend.add_evidence(
            self.token,
            {
                "filename": "coi-acme.txt",
                "content_type": "text/plain",
                "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "content_base64": base64.b64encode(body).decode("ascii"),
            },
        )
        self.assertTrue(
            self.storage.exists(key=f"evidence/{hashlib.sha256(body).hexdigest()}")
        )
        self.backend.run_intake_analysis(self.token)
        findings = self.backend.submission_findings(self.token)
        self.assertEqual([item["check"] for item in findings], ["coi.expired"])

    def test_inline_bytes_failing_verification_are_rejected(self) -> None:
        body = EXPIRED_COI.encode("utf-8")
        with self.assertRaises(VendorBackendError) as context:
            self.backend.add_evidence(
                self.token,
                {
                    "filename": "coi-acme.txt",
                    "content_type": "text/plain",
                    "size_bytes": len(body),
                    "sha256": "f" * 64,
                    "content_base64": base64.b64encode(body).decode("ascii"),
                },
            )
        self.assertEqual(context.exception.code, "content_mismatch")
        with self.assertRaises(VendorBackendError) as context:
            self.backend.add_evidence(
                self.token,
                {
                    "filename": "coi-acme.txt",
                    "content_type": "text/plain",
                    "size_bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "content_base64": "not-valid-base64!!",
                },
            )
        self.assertEqual(context.exception.code, "invalid_content")

    def test_document_without_stored_bytes_keeps_current_behavior(self) -> None:
        # Bytes never reached the evidence store (browser-only upload): there is
        # nothing to validate, so filename matching still covers the requirement.
        self.backend.add_evidence(
            self.token,
            {
                "filename": "coi-acme.txt",
                "content_type": "text/plain",
                "size_bytes": 10,
                "sha256": "f" * 64,
            },
        )
        self.backend.run_intake_analysis(self.token)
        self.assertEqual(self.backend.submission_findings(self.token), [])
        unresolved = {
            item["requirement_id"] for item in self.backend.unresolved_questions(self.token)
        }
        self.assertNotIn("INS.COI.001", unresolved)

    def test_intake_event_records_validation_findings(self) -> None:
        self.add_document("coi-acme.txt", EXPIRED_COI)
        self.backend.run_intake_analysis(self.token)
        events = [
            event
            for event in self.repository.list("event", workspace_id="csub-demo")
            if event.event_type == "intake.analyzed"
        ]
        self.assertEqual(len(events), 1)
        recorded = events[0].detail["validation_findings"]
        self.assertEqual([item["check"] for item in recorded], ["coi.expired"])


if __name__ == "__main__":
    unittest.main()
