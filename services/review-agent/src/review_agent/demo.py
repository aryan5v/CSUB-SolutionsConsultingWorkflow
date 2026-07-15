"""Runnable local vertical slice (PLAN Tuesday gate).

Runs a low-risk, a medium-risk, and a safe-escalation case end to end with
deterministic fakes and prints a compact, non-sensitive summary. Also exercises
the mock ServiceNow before/after preview and an idempotent commit for the
medium case. No live AWS, no institutional data.

    python -m review_agent.demo
"""

from __future__ import annotations

import sys

from .adapters.model import DeterministicModelClient
from .adapters.servicenow import MockServiceNowConnector
from .audit.log import AuditLog, InMemoryAuditSink
from .contracts.case import CaseIntake
from .contracts.graph_state import ReviewGraphState
from .contracts.servicenow import HumanDecision, ReviewAction
from .lookup.approved_software import ApprovedSoftwareIndex
from .orchestration.graph import ReviewWorkflow
from .orchestration.state import InMemoryCheckpointer
from .policy.conflicts import default_conflict_registry
from .policy.rules import default_ruleset
from .samples import escalation_case, low_risk_case, medium_risk_case, sample_records

_FIXED_CLOCK = "2026-07-14T12:00:00+00:00"


def _build_workflow(sink: InMemoryAuditSink, checkpointer: InMemoryCheckpointer) -> ReviewWorkflow:
    return ReviewWorkflow(
        model=DeterministicModelClient(),
        software_index=ApprovedSoftwareIndex(sample_records()),
        ruleset=default_ruleset(),
        registry=default_conflict_registry(),
        audit=AuditLog(sink=sink),
        checkpointer=checkpointer,
        clock=lambda: _FIXED_CLOCK,
    )


def _run_case(name: str, case: CaseIntake, case_id: str) -> ReviewGraphState:
    sink = InMemoryAuditSink()
    checkpointer = InMemoryCheckpointer()
    workflow = _build_workflow(sink, checkpointer)
    state = ReviewGraphState(case_id=case_id, case_input=case)
    workflow.run_until_review(state)

    result = state.policy_result
    print(f"== {name} ({case_id}) ==")
    print(f"  status:      {state.status.value}")
    print(f"  risk route:  {result.risk_route.value if result else 'n/a'}")
    print(f"  escalated:   {result.escalated if result else 'n/a'}")
    if result and result.escalation_reasons:
        print(f"  reasons:     {'; '.join(result.escalation_reasons)}")
    if state.draft_packet:
        print(f"  packet:      {state.draft_packet.packet_type.value} "
              f"({len(state.draft_packet.sections)} sections, sha={state.draft_packet.sha256[:12]})")
    print(f"  audit events:{len(sink.events)} -> {', '.join(sink.event_types())}")
    print(f"  checkpoint:  {'saved' if checkpointer.has(case_id) else 'none'}")
    print()
    return state


def _demo_writeback(state: ReviewGraphState) -> None:
    """Simulated ServiceNow before/after preview and idempotent commit."""
    connector = MockServiceNowConnector()
    connector.seed_record(
        record_id="RITM0001",
        table="sc_req_item",
        fields={"state": "open", "u_risk_route": "unassigned"},
    )
    connector.configure_case(case_id=state.case_id, table="sc_req_item", record_id="RITM0001")

    workflow = _build_workflow(InMemoryAuditSink(), InMemoryCheckpointer())
    decision = HumanDecision(
        case_id=state.case_id,
        decision_version=1,
        reviewer_id="reviewer@example.edu",
        action=ReviewAction.APPROVE,
        decided_at=_FIXED_CLOCK,
        approved_fields={"state": "approved", "u_risk_route": "medium"},
    )
    preview = workflow.preview_writeback(state, connector, decision)
    print("== Simulated ServiceNow (write-back preview) ==")
    print(f"  table:       {preview.table} record {preview.record_id}")
    for change in preview.field_changes:
        print(f"  change:      {change.field}: {change.from_value!r} -> {change.to_value!r}")

    result = workflow.commit_writeback(
        state, connector, decision, second_confirmation=True, expected_version=1
    )
    replay = workflow.commit_writeback(
        state, connector, decision, second_confirmation=True, expected_version=1
    )
    print(f"  committed:   {result.committed} (record v{result.record_version}, simulated={result.simulated})")
    print(f"  attachment:  {result.attachment.attachment_id if result.attachment else 'none'}")
    print(f"  idempotency: replay duplicate_suppressed={replay.duplicate_suppressed}")
    print("  label:       Simulated ServiceNow")
    print()


def main() -> int:
    _run_case("Low-risk", low_risk_case(), "CASE-LOW-001")
    medium_state = _run_case("Medium-risk", medium_risk_case(), "CASE-MED-001")
    _run_case("Escalation", escalation_case(), "CASE-ESC-001")
    _demo_writeback(medium_state)
    print("Local vertical slice complete (deterministic fakes, no live AWS).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
