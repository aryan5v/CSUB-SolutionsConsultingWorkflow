"""Vendor evidence-portal tests (link, notify, research, ingest, gaps).

Deterministic and stdlib-only: local fakes throughout, no boto3 or network. The
gap analysis is exercised as a pure function; the orchestrator is checked for
the notify-both, deploy-research, land-in-bucket, and find-gaps behavior plus its
audit trail.
"""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.storage import InMemoryStorage
from review_agent.audit.log import AuditLog, InMemoryAuditSink
from review_agent.config import AppConfig
from review_agent.contracts.evidence import EvidenceRecord, EvidenceType
from review_agent.contracts.policy import PolicyResult, RiskRoute
from review_agent.vendor.gaps import analyze_gaps
from review_agent.vendor.link import (
    LocalUploadLinkIssuer,
    mint_invite,
    vendor_upload_key,
)
from review_agent.vendor.notify import MockNotifier
from review_agent.vendor.portal import VendorEvidencePortal, build_vendor_portal
from review_agent.vendor.research import DeterministicVendorResearch

_CLOCK = "2026-07-14T12:00:00+00:00"


def _evidence(case_id: str, etype: EvidenceType, eid: str = "ev:1") -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=eid, case_id=case_id, evidence_type=etype, source_sha256="deadbeef"
    )


def _policy(required: list[str]) -> PolicyResult:
    return PolicyResult(
        policy_version="2026.07.14-draft",
        risk_route=RiskRoute.MEDIUM,
        required_evidence=list(required),
    )


class LinkTests(unittest.TestCase):
    def test_token_is_deterministic_per_case_and_nonce(self) -> None:
        a = mint_invite(
            case_id="C1", vendor="V", product="P", vendor_recipient="v@x.com",
            committee_recipients=["c@x.edu"], nonce="n1",
            created_at=_CLOCK, expires_at=_CLOCK,
        )
        b = mint_invite(
            case_id="C1", vendor="V", product="P", vendor_recipient="v@x.com",
            committee_recipients=["c@x.edu"], nonce="n1",
            created_at=_CLOCK, expires_at=_CLOCK,
        )
        c = mint_invite(
            case_id="C1", vendor="V", product="P", vendor_recipient="v@x.com",
            committee_recipients=["c@x.edu"], nonce="n2",
            created_at=_CLOCK, expires_at=_CLOCK,
        )
        self.assertEqual(a.token, b.token)
        self.assertNotEqual(a.token, c.token)
        self.assertEqual(a.upload_prefix, "raw/C1/vendor-upload/")

    def test_upload_key_is_case_scoped_and_sanitized(self) -> None:
        self.assertEqual(
            vendor_upload_key("C1", "../../etc/passwd"), "raw/C1/vendor-upload/passwd"
        )
        self.assertEqual(
            vendor_upload_key("C1", "HECVAT v3.xlsx"), "raw/C1/vendor-upload/HECVAT v3.xlsx"
        )

    def test_local_issuer_builds_token_url(self) -> None:
        invite = mint_invite(
            case_id="C1", vendor="V", product="P", vendor_recipient="v@x.com",
            committee_recipients=[], nonce="n", created_at=_CLOCK, expires_at=_CLOCK,
        )
        link = LocalUploadLinkIssuer(portal_base_url="https://portal.test").portal_link(invite)
        self.assertEqual(link.url, f"https://portal.test/vendor/upload?token={invite.token}")


class NotifierTests(unittest.TestCase):
    def test_notifies_vendor_and_every_committee_member(self) -> None:
        invite = mint_invite(
            case_id="C1", vendor="Acme", product="Analytics", vendor_recipient="v@acme.com",
            committee_recipients=["a@csub.edu", "b@csub.edu"], nonce="n",
            created_at=_CLOCK, expires_at=_CLOCK,
        )
        link = LocalUploadLinkIssuer().portal_link(invite)
        notifier = MockNotifier()
        v = notifier.notify_vendor(invite, link)
        c = notifier.notify_committee(invite, link)
        self.assertEqual(v.audience, "vendor")
        self.assertTrue(v.simulated)
        self.assertEqual([r.recipient for r in c], ["a@csub.edu", "b@csub.edu"])
        self.assertEqual(len(notifier.sent), 3)


class GapAnalysisTests(unittest.TestCase):
    def test_missing_and_satisfied_are_partitioned(self) -> None:
        report = analyze_gaps(
            case_id="C1",
            policy_result=_policy(["hecvat", "soc2"]),
            provided=[_evidence("C1", EvidenceType.HECVAT, "ev:h")],
            clock=lambda: _CLOCK,
        )
        self.assertEqual(report.satisfied, ["hecvat"])
        self.assertEqual(report.missing, ["soc2"])
        self.assertTrue(report.requires_human_confirmation)
        self.assertEqual(report.risk_route, "medium")

    def test_ignores_evidence_from_other_cases(self) -> None:
        report = analyze_gaps(
            case_id="C1",
            policy_result=_policy(["hecvat"]),
            provided=[_evidence("OTHER", EvidenceType.HECVAT, "ev:x")],
            clock=lambda: _CLOCK,
        )
        self.assertEqual(report.missing, ["hecvat"])
        self.assertEqual(report.satisfied, [])

    def test_dedupes_required_evidence(self) -> None:
        report = analyze_gaps(
            case_id="C1",
            policy_result=_policy(["soc2", "soc2", "hecvat"]),
            provided=[],
            clock=lambda: _CLOCK,
        )
        self.assertEqual(report.required, ["soc2", "hecvat"])


class PortalOrchestratorTests(unittest.TestCase):
    def _portal(self, sink: InMemoryAuditSink) -> VendorEvidencePortal:
        return VendorEvidencePortal(
            issuer=LocalUploadLinkIssuer(portal_base_url="https://portal.test"),
            notifier=MockNotifier(),
            research=DeterministicVendorResearch(),
            storage=InMemoryStorage(),
            audit=AuditLog(sink=sink),
            clock=lambda: _CLOCK,
        )

    def test_send_invite_notifies_both_and_deploys_research(self) -> None:
        sink = InMemoryAuditSink()
        result = self._portal(sink).send_invite(
            case_id="C1", vendor="Acme", product="Analytics",
            vendor_recipient="v@acme.com", committee_recipients=["chair@csub.edu"],
            official_domain="acme.com", nonce="n1",
        )
        self.assertEqual(result["link"].token, result["invite"].token)
        self.assertEqual(result["vendor_receipt"].audience, "vendor")
        self.assertEqual(len(result["committee_receipts"]), 1)
        self.assertEqual(result["research"].vendor, "Acme")
        types = sink.event_types()
        self.assertIn("vendor.invite_created", types)
        self.assertIn("vendor.link_sent", types)
        self.assertIn("vendor.research_completed", types)

    def test_ingest_upload_lands_in_bucket_then_gaps(self) -> None:
        sink = InMemoryAuditSink()
        storage = InMemoryStorage()
        portal = VendorEvidencePortal(
            issuer=LocalUploadLinkIssuer(),
            notifier=MockNotifier(),
            research=DeterministicVendorResearch(),
            storage=storage,
            audit=AuditLog(sink=sink),
            clock=lambda: _CLOCK,
        )
        record = portal.ingest_upload(
            case_id="C1", filename="hecvat.pdf", body=b"%PDF- evidence",
            evidence_type=EvidenceType.HECVAT, vendor="Acme",
        )
        self.assertEqual(record.case_id, "C1")
        self.assertTrue(storage.exists(key=vendor_upload_key("C1", "hecvat.pdf")))
        self.assertIn("vendor.evidence_received", sink.event_types())

        report = portal.evaluate_gaps(
            case_id="C1", policy_result=_policy(["hecvat", "soc2"]), evidence=[record]
        )
        self.assertEqual(report.satisfied, ["hecvat"])
        self.assertEqual(report.missing, ["soc2"])
        self.assertIn("vendor.gaps_evaluated", sink.event_types())


class FactoryTests(unittest.TestCase):
    def test_local_factory_wires_fakes(self) -> None:
        portal = build_vendor_portal(AppConfig(use_local_fakes=True), AuditLog())
        self.assertIsInstance(portal, VendorEvidencePortal)
        # Deterministic research in local mode returns the synthetic marker.
        out = portal.send_invite(
            case_id="C1", vendor="Acme", product="P", vendor_recipient="v@a.com",
            committee_recipients=[], nonce="n",
        )
        self.assertIn("deterministic-fake", out["research"].summary)


if __name__ == "__main__":
    unittest.main()
