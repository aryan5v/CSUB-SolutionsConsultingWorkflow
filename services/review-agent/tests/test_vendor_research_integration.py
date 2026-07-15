"""Integration seam: official-domain research inside vendor intake analysis (#44).

Confirms the narrowest deterministic seam required by issue #44 acceptance:
same-domain trust-center evidence enters intake analysis with resolvable
provenance, and research failures surface as gaps for manual review. Research
only annotates: it does not change coverage, unresolved questions, policy, or
approval. All hosts/IPs are synthetic; no network I/O occurs.
"""

from __future__ import annotations

import datetime
import unittest

import _bootstrap  # noqa: F401

from review_agent.profiles.service import ReviewProfileService
from review_agent.research import RawResponse, ResearchPolicy, VendorResearchService
from review_agent.vendor.repository import InMemoryVendorRepository
from review_agent.vendor.service import VendorBackend

PUBLIC_IP = "93.184.216.34"

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

TRUST_URL = "https://trust.acme.example/security"


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime.datetime(2026, 7, 15, 12, tzinfo=datetime.timezone.utc)

    def __call__(self) -> datetime.datetime:
        return self.value


class FakeResolver:
    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self._mapping = mapping

    def resolve(self, host: str) -> list[str]:
        return self._mapping.get(host, [PUBLIC_IP])


class FakeTransport:
    def __init__(self, mapping: dict[str, dict]) -> None:
        self._mapping = mapping

    def fetch(self, *, ip: str, host: str, url: str, timeout: float, max_bytes: int) -> RawResponse:
        spec = self._mapping[url]
        return RawResponse(
            status=spec.get("status", 200),
            headers=spec.get("headers", {"content-type": "application/pdf"}),
            body=spec.get("body", b"%PDF-1.4 acme trust center evidence"),
            connected_ip=ip,
            oversized=spec.get("oversized", False),
        )


class VendorResearchIntegrationTests(unittest.TestCase):
    def _backend(self, provider) -> VendorBackend:
        clock = MutableClock()
        repository = InMemoryVendorRepository()
        profiles = ReviewProfileService(repository, clock=clock)
        profile = profiles.create_draft("combined", CRITERIA)
        profiles.fixture_test(profile.profile_version_id)
        profiles.activate(profile.profile_version_id)
        tokens = iter([f"{c}" * 43 for c in "ABCDEFGH"])
        backend = VendorBackend(
            repository,
            profiles,
            clock=clock,
            token_factory=lambda: next(tokens),
            research_provider=provider,
        )
        vendor = backend.create_vendor("Acme Inc", "acme.example")
        product = backend.create_product(vendor.vendor_id, "Widget")
        contact = backend.create_contact(vendor.vendor_id, "Vendor Contact", "c@acme.example")
        backend.register_case("CASE-1", product.product_id, "Course scheduling", "public web scope")
        self._contact = contact
        return backend

    def _drive_to_analysis(self, backend: VendorBackend) -> str:
        token = backend.issue_invite("CASE-1", self._contact.contact_id)["token"]
        backend.resolve_invite(token, mark_open=True)
        backend.add_evidence(
            token,
            {
                "filename": "soc2-report.pdf",
                "content_type": "application/pdf",
                "size_bytes": 100,
                "sha256": "a" * 64,
            },
        )
        backend.set_trust_center_url(token, TRUST_URL)
        return token

    def _provider(self, transport_mapping, resolver_mapping=None):
        return VendorResearchService(
            transport=FakeTransport(transport_mapping),
            resolver=FakeResolver(resolver_mapping or {}),
            policy=ResearchPolicy(),
            clock=lambda: "2026-07-15T12:00:00+00:00",
            monotonic=lambda: 0.0,
        )

    def test_same_domain_evidence_enters_analysis_with_provenance(self) -> None:
        provider = self._provider({TRUST_URL: {"headers": {"content-type": "application/pdf"}}})
        backend = self._backend(provider)
        token = self._drive_to_analysis(backend)

        analyzed = backend.run_intake_analysis(token)
        self.assertTrue(analyzed.intake_analysis_complete)

        research = backend.intake_research(token)
        self.assertIsNotNone(research)
        self.assertEqual(research["confirmed_host"], "trust.acme.example")
        self.assertEqual(len(research["findings"]), 1)
        prov = research["findings"][0]["provenance"]
        self.assertEqual(prov["final_url"], TRUST_URL)
        self.assertEqual(prov["scope"], "official_vendor")
        self.assertEqual(prov["vendor"], "Acme Inc")
        self.assertEqual(prov["product"], "Widget")
        self.assertEqual(len(prov["content_sha256"]), 64)
        self.assertEqual(research["gaps"], [])
        self.assertIn("provenance-backed", analyzed.research_summary)

    def test_research_failure_surfaces_as_gap_and_does_not_block_analysis(self) -> None:
        # Trust-center host resolves to a private IP -> research gap, but the
        # deterministic intake analysis still completes.
        provider = self._provider(
            {TRUST_URL: {"status": 200}},
            resolver_mapping={"trust.acme.example": ["10.0.0.5"]},
        )
        backend = self._backend(provider)
        token = self._drive_to_analysis(backend)

        analyzed = backend.run_intake_analysis(token)
        self.assertTrue(analyzed.intake_analysis_complete)

        research = backend.intake_research(token)
        self.assertEqual(research["findings"], [])
        self.assertEqual(len(research["gaps"]), 1)
        self.assertEqual(research["gaps"][0]["code"], "private_ip")

    def test_http_500_trust_center_is_a_gap_not_evidence(self) -> None:
        provider = self._provider({TRUST_URL: {"status": 500}})
        backend = self._backend(provider)
        token = self._drive_to_analysis(backend)

        backend.run_intake_analysis(token)
        research = backend.intake_research(token)
        self.assertEqual(research["findings"], [])
        self.assertEqual(research["gaps"][0]["code"], "http_error")

    def test_research_does_not_change_coverage_or_questions(self) -> None:
        # Deterministic coverage/questions must be identical with and without a
        # research provider: research annotates provenance only.
        with_provider = self._backend(
            self._provider({TRUST_URL: {"headers": {"content-type": "application/pdf"}}})
        )
        token_a = self._drive_to_analysis(with_provider)
        with_provider.run_intake_analysis(token_a)
        questions_with = [q["requirement_id"] for q in with_provider.unresolved_questions(token_a)]

        without_provider = self._backend(None)
        token_b = self._drive_to_analysis(without_provider)
        analyzed_b = without_provider.run_intake_analysis(token_b)
        questions_without = [
            q["requirement_id"] for q in without_provider.unresolved_questions(token_b)
        ]

        # SOC 2 filename deterministically covers SEC.DATA.001; A11Y stays open.
        self.assertEqual(questions_with, ["A11Y.VPAT.001"])
        self.assertEqual(questions_with, questions_without)
        # No provider -> research honestly reported as not performed, no findings.
        self.assertIsNone(without_provider.intake_research(token_b))
        self.assertIn("not performed", analyzed_b.research_summary)


if __name__ == "__main__":
    unittest.main()
