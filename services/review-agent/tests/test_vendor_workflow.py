"""Vendor-evidence wired into the review workflow.

With a portal, a case that requires vendor documents pauses at
AWAITING_VENDOR_EVIDENCE (link sent, research deployed), then resumes into gap
analysis and packet composition. Without a portal, behavior is unchanged (the
low-risk case, which requires no evidence, never pauses). Also verified through
the real LangGraph graph. Stdlib-only fakes; the langgraph path skips when the
aws extra is absent.
"""

from __future__ import annotations

import importlib.util
import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.model import DeterministicModelClient
from review_agent.adapters.storage import InMemoryStorage
from review_agent.audit.log import AuditLog, InMemoryAuditSink
from review_agent.contracts.evidence import EvidenceRecord, EvidenceType
from review_agent.contracts.graph_state import ReviewGraphState, WorkflowStatus
from review_agent.lookup.approved_software import ApprovedSoftwareIndex
from review_agent.orchestration.graph import ReviewWorkflow
from review_agent.orchestration.state import InMemoryCheckpointer
from review_agent.policy.conflicts import default_conflict_registry
from review_agent.policy.rules import default_ruleset
from review_agent.samples import low_risk_case, medium_risk_case, sample_records
from review_agent.vendor.link import LocalUploadLinkIssuer
from review_agent.vendor.notify import MockNotifier
from review_agent.vendor.portal import VendorEvidencePortal
from review_agent.vendor.research import DeterministicVendorResearch

_HAS_LANGGRAPH = importlib.util.find_spec("langgraph") is not None
_CLOCK = "2026-07-14T12:00:00+00:00"


def _workflow_with_portal(sink: InMemoryAuditSink, checkpointer: InMemoryCheckpointer):
    audit = AuditLog(sink=sink)
    portal = VendorEvidencePortal(
        issuer=LocalUploadLinkIssuer(),
        notifier=MockNotifier(),
        research=DeterministicVendorResearch(),
        storage=InMemoryStorage(),
        audit=audit,
        clock=lambda: _CLOCK,
    )
    return ReviewWorkflow(
        model=DeterministicModelClient(),
        software_index=ApprovedSoftwareIndex(sample_records()),
        ruleset=default_ruleset(),
        registry=default_conflict_registry(),
        audit=audit,
        checkpointer=checkpointer,
        portal=portal,
        clock=lambda: _CLOCK,
    )


class WiredVendorFlowTests(unittest.TestCase):
    def test_pauses_for_vendor_evidence_when_required(self) -> None:
        sink, cp = InMemoryAuditSink(), InMemoryCheckpointer()
        wf = _workflow_with_portal(sink, cp)
        state = ReviewGraphState(case_id="CASE-VEN", case_input=medium_risk_case())
        wf.run_until_review(state)

        self.assertIs(state.status, WorkflowStatus.AWAITING_VENDOR_EVIDENCE)
        self.assertIsNotNone(state.vendor_invite)
        self.assertIsNotNone(state.vendor_research)
        self.assertIsNone(state.draft_packet)  # not composed yet
        self.assertTrue(cp.has("CASE-VEN"))  # durable pause
        self.assertIn("vendor.evidence_requested", sink.event_types())

    def test_resume_runs_gap_analysis_then_composes(self) -> None:
        sink, cp = InMemoryAuditSink(), InMemoryCheckpointer()
        wf = _workflow_with_portal(sink, cp)
        state = ReviewGraphState(case_id="CASE-VEN", case_input=medium_risk_case())
        wf.run_until_review(state)
        required = list(state.policy_result.required_evidence)
        self.assertTrue(required)

        # Vendor drops one required document; the rest stay missing.
        provided = required[0]
        wf.submit_vendor_evidence(
            state,
            [
                EvidenceRecord(
                    evidence_id="ev:1",
                    case_id="CASE-VEN",
                    evidence_type=EvidenceType(provided),
                    source_sha256="abc",
                )
            ],
        )
        self.assertIs(state.status, WorkflowStatus.AWAITING_REVIEW)
        self.assertIsNotNone(state.gap_report)
        self.assertIn(provided, state.gap_report["satisfied"])
        self.assertEqual(set(state.evidence_gaps), set(required) - {provided})
        self.assertIsNotNone(state.draft_packet)
        self.assertIn("vendor.evidence_submitted", sink.event_types())

    def test_no_portal_means_no_pause(self) -> None:
        # Without a portal the medium case flows straight through (unchanged).
        wf = ReviewWorkflow(
            model=DeterministicModelClient(),
            software_index=ApprovedSoftwareIndex(sample_records()),
            ruleset=default_ruleset(),
            registry=default_conflict_registry(),
            audit=AuditLog(sink=InMemoryAuditSink()),
            checkpointer=InMemoryCheckpointer(),
            clock=lambda: _CLOCK,
        )
        state = ReviewGraphState(case_id="CASE-NP", case_input=medium_risk_case())
        wf.run_until_review(state)
        self.assertIs(state.status, WorkflowStatus.AWAITING_REVIEW)

    def test_low_risk_never_pauses_even_with_portal(self) -> None:
        wf = _workflow_with_portal(InMemoryAuditSink(), InMemoryCheckpointer())
        state = ReviewGraphState(case_id="CASE-LOW", case_input=low_risk_case())
        wf.run_until_review(state)
        self.assertIs(state.status, WorkflowStatus.AWAITING_REVIEW)
        self.assertIsNone(state.vendor_invite)


@unittest.skipUnless(_HAS_LANGGRAPH, "langgraph not installed (aws extra)")
class WiredVendorFlowGraphTests(unittest.TestCase):
    def test_graph_pauses_then_resumes_into_gaps(self) -> None:
        from review_agent.orchestration.langgraph_app import run_review_graph

        wf = _workflow_with_portal(InMemoryAuditSink(), InMemoryCheckpointer())
        state = ReviewGraphState(case_id="CASE-G", case_input=medium_risk_case())

        # Pass 1: the graph pauses at the vendor-evidence interrupt.
        run_review_graph(wf, state)
        self.assertIs(state.status, WorkflowStatus.AWAITING_VENDOR_EVIDENCE)
        self.assertIsNotNone(state.vendor_invite)

        # Vendor drops evidence; pass 2 routes past the interrupt into gaps.
        state.evidence_records = [
            {"evidence_id": "ev:1", "case_id": "CASE-G", "evidence_type": "hecvat",
             "source_sha256": "abc"}
        ]
        run_review_graph(wf, state)
        self.assertIs(state.status, WorkflowStatus.AWAITING_REVIEW)
        self.assertIsNotNone(state.gap_report)
        self.assertIn("hecvat", state.gap_report["satisfied"])
        self.assertIsNotNone(state.draft_packet)


if __name__ == "__main__":
    unittest.main()
