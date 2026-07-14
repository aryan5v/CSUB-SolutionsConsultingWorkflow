"""Live durable pause/resume smoke check (manual, not part of CI).

Runs a case to the awaiting-review human interrupt and checkpoints it to the
deployed DynamoDB CasesTable ("process A"), then loads it back with a *fresh*
checkpointer ("process B") to prove resume survives a process restart. Deletes
the test item afterward. Writes only synthetic, non-sensitive data.

    USE_LOCAL_FAKES=false AWS_REGION=us-west-2 CASES_TABLE=... \
        python services/review-agent/scripts/smoke_resume.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from review_agent.adapters.model import DeterministicModelClient  # noqa: E402
from review_agent.audit.log import AuditLog, InMemoryAuditSink  # noqa: E402
from review_agent.config import AppConfig  # noqa: E402
from review_agent.contracts.graph_state import ReviewGraphState, WorkflowStatus  # noqa: E402
from review_agent.lookup.approved_software import ApprovedSoftwareIndex  # noqa: E402
from review_agent.orchestration.graph import ReviewWorkflow  # noqa: E402
from review_agent.orchestration.state import build_checkpointer  # noqa: E402
from review_agent.policy.conflicts import default_conflict_registry  # noqa: E402
from review_agent.policy.rules import default_ruleset  # noqa: E402
from review_agent.samples import medium_risk_case, sample_records  # noqa: E402


def main() -> int:
    os.environ.setdefault("USE_LOCAL_FAKES", "false")
    config = AppConfig.from_env()
    if config.use_local_fakes or not config.aws.cases_table:
        print("Set USE_LOCAL_FAKES=false and CASES_TABLE to the foundation table.")
        return 1

    case_id = "SMOKE-RESUME-0001"

    # Process A: run to the human interrupt and checkpoint durably.
    workflow = ReviewWorkflow(
        model=DeterministicModelClient(),
        software_index=ApprovedSoftwareIndex(sample_records()),
        ruleset=default_ruleset(),
        registry=default_conflict_registry(),
        audit=AuditLog(sink=InMemoryAuditSink()),
        checkpointer=build_checkpointer(config),
        clock=lambda: "2026-07-14T12:00:00+00:00",
    )
    state = ReviewGraphState(case_id=case_id, case_input=medium_risk_case())
    workflow.run_until_review(state)
    print(f"process A: ran to {state.status.value} -> checkpointed to DynamoDB")

    # Process B: a fresh checkpointer resumes from the durable store.
    resumed = build_checkpointer(config).load(case_id)
    assert resumed is not None
    assert resumed["status"] == WorkflowStatus.AWAITING_REVIEW.value
    assert resumed["draft_packet"] is not None
    print(f"process B: resumed status={resumed['status']} | packet present")

    import boto3

    boto3.client("dynamodb", region_name=config.aws.region).delete_item(
        TableName=config.aws.cases_table, Key={"case_id": {"S": case_id}}
    )
    print("cleanup: deleted durable checkpoint item")
    print("\nLive durable pause/resume OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
