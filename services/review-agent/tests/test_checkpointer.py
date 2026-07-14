"""Durable checkpointer tests (pause/resume).

The DynamoDb checkpointer is exercised over an in-memory cases repository (its
delegate) so these run in the stdlib-only CI gate with no boto3 or network. A
full workflow is run to a human-interrupt boundary, the snapshot is persisted,
and a *fresh* checkpointer instance loads it back — the process-restart resume
contract. The AgentCore seam and the config factory are covered too.
"""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.cases_repository import InMemoryCasesRepository
from review_agent.audit.log import AuditLog, InMemoryAuditSink
from review_agent.config import AppConfig, AwsConfig
from review_agent.contracts.graph_state import ReviewGraphState, WorkflowStatus
from review_agent.lookup.approved_software import ApprovedSoftwareIndex
from review_agent.orchestration.graph import ReviewWorkflow
from review_agent.orchestration.state import (
    AgentCoreMemoryCheckpointer,
    DynamoDbCheckpointer,
    InMemoryCheckpointer,
    build_checkpointer,
)
from review_agent.adapters.model import DeterministicModelClient
from review_agent.policy.conflicts import default_conflict_registry
from review_agent.policy.rules import default_ruleset
from review_agent.samples import medium_risk_case, sample_records


class DynamoDbCheckpointerTests(unittest.TestCase):
    def test_delegates_to_repository(self) -> None:
        repo = InMemoryCasesRepository()
        cp = DynamoDbCheckpointer(repo)
        cp.save("CASE-1", {"case_id": "CASE-1", "status": "awaiting_review"})
        self.assertTrue(cp.has("CASE-1"))
        self.assertEqual(cp.load("CASE-1")["status"], "awaiting_review")
        self.assertIsNone(cp.load("missing"))
        self.assertFalse(cp.has("missing"))

    def test_pause_then_resume_in_a_fresh_process(self) -> None:
        # Shared durable store stands in for DynamoDB across two "processes".
        repo = InMemoryCasesRepository()

        # Process A: run to the awaiting_review interrupt and checkpoint.
        workflow = ReviewWorkflow(
            model=DeterministicModelClient(),
            software_index=ApprovedSoftwareIndex(sample_records()),
            ruleset=default_ruleset(),
            registry=default_conflict_registry(),
            audit=AuditLog(sink=InMemoryAuditSink()),
            checkpointer=DynamoDbCheckpointer(repo),
            clock=lambda: "2026-07-14T12:00:00+00:00",
        )
        state = ReviewGraphState(case_id="CASE-MED-001", case_input=medium_risk_case())
        workflow.run_until_review(state)
        self.assertIs(state.status, WorkflowStatus.AWAITING_REVIEW)

        # Process B: a brand-new checkpointer over the same store resumes.
        resumed = DynamoDbCheckpointer(repo).load("CASE-MED-001")
        self.assertIsNotNone(resumed)
        self.assertEqual(resumed["status"], WorkflowStatus.AWAITING_REVIEW.value)
        self.assertEqual(resumed["case_id"], "CASE-MED-001")
        self.assertIsNotNone(resumed["draft_packet"])  # packet survived the pause


class AgentCoreSeamTests(unittest.TestCase):
    def test_seam_raises_with_actionable_message(self) -> None:
        cp = AgentCoreMemoryCheckpointer(memory_id="mem-1", region="us-west-2")
        with self.assertRaises(NotImplementedError):
            cp.save("c", {})
        with self.assertRaises(NotImplementedError):
            cp.load("c")


class FactoryTests(unittest.TestCase):
    def test_local_returns_in_memory(self) -> None:
        checkpointer = build_checkpointer(AppConfig(use_local_fakes=True))
        self.assertIsInstance(checkpointer, InMemoryCheckpointer)

    def test_aws_returns_dynamodb(self) -> None:
        config = AppConfig(use_local_fakes=False, aws=AwsConfig(cases_table="CasesTable"))
        self.assertIsInstance(build_checkpointer(config), DynamoDbCheckpointer)

    def test_aws_requires_table(self) -> None:
        with self.assertRaises(ValueError):
            build_checkpointer(AppConfig(use_local_fakes=False, aws=AwsConfig(cases_table=None)))


if __name__ == "__main__":
    unittest.main()
