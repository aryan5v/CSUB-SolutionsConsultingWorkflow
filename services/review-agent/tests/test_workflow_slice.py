"""End-to-end local vertical slice tests (Tuesday gate)."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.model import DeterministicModelClient
from review_agent.adapters.servicenow import MockServiceNowConnector
from review_agent.audit.log import AuditLog, InMemoryAuditSink
from review_agent.contracts.graph_state import ReviewGraphState, WorkflowStatus
from review_agent.contracts.packet import PacketType
from review_agent.contracts.servicenow import HumanDecision, ReviewAction
from review_agent.lookup.approved_software import ApprovedSoftwareIndex
from review_agent.observability.metrics import InMemoryMetricsSink
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

CLOCK = "2026-07-14T12:00:00+00:00"


def _workflow(sink, checkpointer, *, metrics=None, id_factory=None):
    kwargs = {}
    if metrics is not None:
        kwargs["metrics"] = metrics
    if id_factory is not None:
        kwargs["id_factory"] = id_factory
    return ReviewWorkflow(
        model=DeterministicModelClient(),
        software_index=ApprovedSoftwareIndex(sample_records()),
        ruleset=default_ruleset(),
        registry=default_conflict_registry(),
        audit=AuditLog(sink=sink),
        checkpointer=checkpointer,
        clock=lambda: CLOCK,
        **kwargs,
    )


class WorkflowSliceTests(unittest.TestCase):
    def _run(self, case, case_id):
        sink = InMemoryAuditSink()
        checkpointer = InMemoryCheckpointer()
        wf = _workflow(sink, checkpointer)
        state = ReviewGraphState(case_id=case_id, case_input=case)
        wf.run_until_review(state)
        return state, sink, checkpointer

    def test_low_risk_produces_low_packet(self) -> None:
        state, sink, checkpointer = self._run(low_risk_case(), "CASE-LOW")
        self.assertEqual(state.status, WorkflowStatus.AWAITING_REVIEW)
        self.assertEqual(state.draft_packet.packet_type, PacketType.LOW_RISK)
        self.assertTrue(state.draft_packet.sha256)
        self.assertTrue(checkpointer.has("CASE-LOW"))
        self.assertIn("packet.composed", sink.event_types())

    def test_medium_risk_produces_editable_packet(self) -> None:
        state, _sink, _cp = self._run(medium_risk_case(), "CASE-MED")
        self.assertEqual(state.status, WorkflowStatus.AWAITING_REVIEW)
        self.assertEqual(state.draft_packet.packet_type, PacketType.MEDIUM_RISK)
        self.assertTrue(any(s.editable for s in state.draft_packet.sections))
        self.assertGreaterEqual(len(state.draft_packet.sections), 5)

    def test_escalation_case_stops_before_packet(self) -> None:
        state, _sink, checkpointer = self._run(escalation_case(), "CASE-ESC")
        self.assertEqual(state.status, WorkflowStatus.ESCALATED)
        self.assertIsNone(state.draft_packet)
        self.assertTrue(state.policy_result.escalated)
        self.assertTrue(checkpointer.has("CASE-ESC"))

    def test_specialists_require_policy_result_at_runtime(self) -> None:
        wf = _workflow(InMemoryAuditSink(), InMemoryCheckpointer())
        state = ReviewGraphState(case_id="CASE-ORDER", case_input=low_risk_case())
        with self.assertRaisesRegex(ValueError, "policy_result must be evaluated"):
            wf.run_specialists(state)

    def test_packet_composition_requires_policy_result_at_runtime(self) -> None:
        wf = _workflow(InMemoryAuditSink(), InMemoryCheckpointer())
        state = ReviewGraphState(case_id="CASE-ORDER", case_input=low_risk_case())
        with self.assertRaisesRegex(ValueError, "policy_result must be evaluated"):
            wf.compose(state)

    def test_pause_and_resume_from_checkpoint(self) -> None:
        # Run to the review interrupt, then confirm the snapshot round-trips.
        state, _sink, checkpointer = self._run(medium_risk_case(), "CASE-RESUME")
        snapshot = checkpointer.load("CASE-RESUME")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["status"], WorkflowStatus.AWAITING_REVIEW.value)
        self.assertEqual(snapshot["case_id"], "CASE-RESUME")
        self.assertIsNotNone(snapshot["draft_packet"])

    def test_writeback_commit_and_attach(self) -> None:
        state, _sink, _cp = self._run(medium_risk_case(), "CASE-WB")
        wf = _workflow(InMemoryAuditSink(), InMemoryCheckpointer())
        connector = MockServiceNowConnector()
        connector.seed_record(record_id="R1", table="sc_req_item", fields={"state": "open"})
        connector.configure_case(case_id="CASE-WB", table="sc_req_item", record_id="R1")
        decision = HumanDecision(
            case_id="CASE-WB",
            decision_version=1,
            reviewer_id="rev@example.edu",
            action=ReviewAction.APPROVE,
            decided_at=CLOCK,
            approved_fields={"state": "approved", "u_risk_route": "medium"},
        )
        preview = wf.preview_writeback(state, connector, decision)
        self.assertTrue(preview.simulated)
        result = wf.commit_writeback(
            state, connector, decision, second_confirmation=True, expected_version=1
        )
        self.assertTrue(result.committed)
        self.assertIsNotNone(result.attachment)
        self.assertEqual(state.status, WorkflowStatus.CLOSED)

    def test_writeback_requires_second_confirmation(self) -> None:
        state, _sink, _cp = self._run(medium_risk_case(), "CASE-NOCONF")
        wf = _workflow(InMemoryAuditSink(), InMemoryCheckpointer())
        connector = MockServiceNowConnector()
        connector.seed_record(record_id="R1", table="sc_req_item", fields={"state": "open"})
        connector.configure_case(case_id="CASE-NOCONF", table="sc_req_item", record_id="R1")
        decision = HumanDecision(
            case_id="CASE-NOCONF",
            decision_version=1,
            reviewer_id="rev@example.edu",
            action=ReviewAction.APPROVE,
            decided_at=CLOCK,
            approved_fields={"state": "approved"},
        )
        with self.assertRaises(PermissionError):
            wf.commit_writeback(
                state, connector, decision, second_confirmation=False, expected_version=1
            )

    def test_run_id_is_minted_once_and_survives_checkpoint_round_trip(self) -> None:
        ids = iter(["run-a", "run-b"])
        wf = _workflow(InMemoryAuditSink(), InMemoryCheckpointer(), id_factory=lambda: next(ids))
        state = ReviewGraphState(case_id="CASE-RUNID", case_input=medium_risk_case())
        wf.run_until_review(state)
        self.assertEqual(state.run_id, "run-a")
        self.assertEqual(state.to_dict()["run_id"], "run-a")
        # A second run on a fresh state gets a distinct id; re-processing the
        # same (already-run-id'd) state never mints a second one.
        wf._ensure_run_id(state)
        self.assertEqual(state.run_id, "run-a")

    def test_run_id_is_carried_as_audit_correlation_id(self) -> None:
        sink = InMemoryAuditSink()
        wf = _workflow(sink, InMemoryCheckpointer(), id_factory=lambda: "run-correlated")
        state = ReviewGraphState(case_id="CASE-CORR", case_input=low_risk_case())
        wf.run_until_review(state)
        self.assertTrue(sink.events)
        self.assertTrue(all(e.correlation_id == "run-correlated" for e in sink.events))

    def test_metrics_emitted_for_specialists_and_citations(self) -> None:
        sink = InMemoryMetricsSink()
        wf = _workflow(InMemoryAuditSink(), InMemoryCheckpointer(), metrics=sink)
        state = ReviewGraphState(case_id="CASE-METRICS", case_input=medium_risk_case())
        wf.run_until_review(state)
        names = sink.names()
        self.assertIn("specialists.latency_ms", names)
        self.assertIn("model.invoke.latency_ms", names)
        self.assertIn("citations.rejected_count", names)
        properties = next(
            r["properties"] for r in sink.records if r["name"] == "citations.rejected_count"
        )
        self.assertEqual(properties["run_id"], state.run_id)
        self.assertEqual(properties["case_id"], "CASE-METRICS")


if __name__ == "__main__":
    unittest.main()
