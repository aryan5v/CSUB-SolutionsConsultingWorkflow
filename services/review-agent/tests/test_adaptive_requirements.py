"""Per-case adaptive vendor requirements (issue #63).

The vendor-facing checklist and unresolved questions must reflect the
deterministic policy result stored on the case at registration: a
classroom/public case surfaces only accessibility requirements, a protected-data
case surfaces both tracks, and a case without a stored policy result keeps the
full active-profile behavior.
"""

from __future__ import annotations

import datetime
import unittest

import _bootstrap  # noqa: F401

from review_agent.profiles.service import ReviewProfileService
from review_agent.vendor.repository import InMemoryVendorRepository
from review_agent.vendor.service import VendorBackend


SECURITY_CRITERIA = [
    {
        "requirement_id": "SEC.DATA.001",
        "question": "Describe encryption controls.",
        "source_citation": {"source_id": "policy:security", "cell": "A1"},
        "expected_evidence": ["SOC 2"],
        "output_fields": ["security_summary"],
        "remediation_guidance": "Provide encryption evidence.",
    }
]

ACCESSIBILITY_CRITERIA = [
    {
        "requirement_id": "A11Y.VPAT.001",
        "question": "Provide a current accessibility report.",
        "source_citation": {"source_id": "policy:accessibility", "cell": "B2"},
        "expected_evidence": ["VPAT"],
        "output_fields": ["accessibility_findings"],
        "remediation_guidance": "Provide a current VPAT.",
    }
]


class AdaptiveRequirementsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = lambda: datetime.datetime(2026, 7, 16, 12, tzinfo=datetime.timezone.utc)
        self.repository = InMemoryVendorRepository()
        self.profiles = ReviewProfileService(self.repository, clock=self.clock)
        for key, criteria in (
            ("security", SECURITY_CRITERIA),
            ("accessibility", ACCESSIBILITY_CRITERIA),
        ):
            profile = self.profiles.create_draft(key, criteria)
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

    def _open_analyzed_submission(self, case_id: str) -> str:
        token = self.backend.issue_invite(case_id, self.contact.contact_id)["token"]
        self.backend.resolve_invite(token, mark_open=True)
        self.backend.add_evidence(
            token,
            {
                "filename": "product-overview.pdf",
                "content_type": "application/pdf",
                "size_bytes": 100,
                "sha256": "a" * 64,
            },
        )
        self.backend.set_trust_center_url(token, "https://trust.vendor.example/security")
        self.backend.run_intake_analysis(token)
        return token

    def test_classroom_case_shows_only_accessibility_requirements(self) -> None:
        self.backend.register_case(
            "CASE-A11Y",
            self.product.product_id,
            "Classroom polling",
            "public scope",
            required_evidence=("vpat_acr",),
            policy_route="medium",
        )
        token = self._open_analyzed_submission("CASE-A11Y")
        questions = self.backend.unresolved_questions(token)
        self.assertEqual(
            [item["requirement_id"] for item in questions], ["A11Y.VPAT.001"]
        )
        status = self.backend.review_status(token)
        self.assertEqual(
            [item["requirement_id"] for item in status["checklist"]], ["A11Y.VPAT.001"]
        )
        self.assertTrue(status["adapted_to_intake"])
        self.assertEqual(status["required_evidence"], ["vpat_acr"])

    def test_protected_data_case_shows_both_tracks(self) -> None:
        self.backend.register_case(
            "CASE-BOTH",
            self.product.product_id,
            "Student records processing",
            "level1 scope",
            required_evidence=("hecvat", "soc2", "vpat_acr"),
            policy_route="high",
        )
        token = self._open_analyzed_submission("CASE-BOTH")
        questions = self.backend.unresolved_questions(token)
        self.assertEqual(
            sorted(item["requirement_id"] for item in questions),
            ["A11Y.VPAT.001", "SEC.DATA.001"],
        )

    def test_case_without_policy_result_keeps_full_profiles(self) -> None:
        self.backend.register_case(
            "CASE-LEGACY", self.product.product_id, "Legacy case", "unknown scope"
        )
        token = self._open_analyzed_submission("CASE-LEGACY")
        questions = self.backend.unresolved_questions(token)
        self.assertEqual(
            sorted(item["requirement_id"] for item in questions),
            ["A11Y.VPAT.001", "SEC.DATA.001"],
        )
        status = self.backend.review_status(token)
        self.assertFalse(status["adapted_to_intake"])
        self.assertEqual(status["required_evidence"], [])

    def test_unmapped_evidence_keys_fail_open_to_full_profiles(self) -> None:
        self.backend.register_case(
            "CASE-UNMAPPED",
            self.product.product_id,
            "Unmapped evidence",
            "scope",
            required_evidence=("insurance_coi",),
            policy_route="medium",
        )
        token = self._open_analyzed_submission("CASE-UNMAPPED")
        questions = self.backend.unresolved_questions(token)
        self.assertEqual(
            sorted(item["requirement_id"] for item in questions),
            ["A11Y.VPAT.001", "SEC.DATA.001"],
        )


if __name__ == "__main__":
    unittest.main()
