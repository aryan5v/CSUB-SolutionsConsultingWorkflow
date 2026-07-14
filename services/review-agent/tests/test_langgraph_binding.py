"""LangGraph binding parity tests.

These require the optional ``langgraph`` dependency (``aws`` extra) and are
skipped in the stdlib-only CI gate — the import is lazy and guarded so no
collection error occurs when langgraph is absent. They assert the real
StateGraph produces byte-for-byte the same ``ReviewGraphState`` as the
sequential ``run_until_review`` for every sample case, including the interrupt
boundaries.
"""

from __future__ import annotations

import importlib.util
import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.model import DeterministicModelClient
from review_agent.audit.log import AuditLog, InMemoryAuditSink
from review_agent.contracts.graph_state import ReviewGraphState, WorkflowStatus
from review_agent.lookup.approved_software import ApprovedSoftwareIndex
from review_agent.orchestration.graph import ReviewWorkflow
from review_agent.orchestration.state import InMemoryCheckpointer
from review_agent.policy.conflicts import default_conflict_registry
from review_agent.policy.rules import default_ruleset
from review_agent.samples import (
    escalation_case,
    low_risk_case,
    medium_risk_case,
    sample_records,
)

_HAS_LANGGRAPH = importlib.util.find_spec("langgraph") is not None
_CLOCK = "2026-07-14T12:00:00+00:00"


def _fresh_workflow() -> ReviewWorkflow:
    return ReviewWorkflow(
        model=DeterministicModelClient(),
        software_index=ApprovedSoftwareIndex(sample_records()),
        ruleset=default_ruleset(),
        registry=default_conflict_registry(),
        audit=AuditLog(sink=InMemoryAuditSink()),
        checkpointer=InMemoryCheckpointer(),
        clock=lambda: _CLOCK,
    )


@unittest.skipUnless(_HAS_LANGGRAPH, "langgraph not installed (aws extra)")
class LangGraphParityTests(unittest.TestCase):
    def _assert_parity(self, case_factory, case_id: str, expected_status: WorkflowStatus) -> None:
        from review_agent.orchestration.langgraph_app import run_review_graph

        # Sequential runner (reference).
        seq = _fresh_workflow()
        seq_state = ReviewGraphState(case_id=case_id, case_input=case_factory())
        seq.run_until_review(seq_state)

        # Real LangGraph graph over the same node functions.
        graph = _fresh_workflow()
        graph_state = ReviewGraphState(case_id=case_id, case_input=case_factory())
        result = run_review_graph(graph, graph_state)

        self.assertIs(result.status, expected_status)
        self.assertEqual(result.to_dict(), seq_state.to_dict())

    def test_low_risk_reaches_awaiting_review(self) -> None:
        self._assert_parity(low_risk_case, "CASE-LOW-001", WorkflowStatus.AWAITING_REVIEW)

    def test_medium_risk_reaches_awaiting_review(self) -> None:
        self._assert_parity(medium_risk_case, "CASE-MED-001", WorkflowStatus.AWAITING_REVIEW)

    def test_escalation_interrupts_before_specialists(self) -> None:
        self._assert_parity(escalation_case, "CASE-ESC-001", WorkflowStatus.ESCALATED)

    def test_escalated_case_has_no_packet(self) -> None:
        from review_agent.orchestration.langgraph_app import run_review_graph

        workflow = _fresh_workflow()
        state = ReviewGraphState(case_id="CASE-ESC-002", case_input=escalation_case())
        result = run_review_graph(workflow, state)
        self.assertIs(result.status, WorkflowStatus.ESCALATED)
        self.assertIsNone(result.draft_packet)


if __name__ == "__main__":
    unittest.main()
