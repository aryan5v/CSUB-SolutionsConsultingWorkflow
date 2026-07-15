"""Contract validation, packet hashing, and audit-safety tests."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from review_agent.audit.log import AuditLog, InMemoryAuditSink
from review_agent.contracts.audit import ActorType, AuditEvent
from review_agent.contracts.case import CaseIntake, DataClassification, Requester
from review_agent.contracts.schema import ContractValidationError, validate
from review_agent.samples import low_risk_case, medium_risk_case, sample_records
from review_agent.lookup.approved_software import ApprovedSoftwareIndex
from review_agent.orchestration.graph import ReviewWorkflow
from review_agent.orchestration.state import InMemoryCheckpointer
from review_agent.policy.conflicts import default_conflict_registry
from review_agent.policy.rules import default_ruleset
from review_agent.adapters.model import DeterministicModelClient
from review_agent.contracts.common import SourceCoordinates
from review_agent.contracts.graph_state import ReviewGraphState


class ContractValidationTests(unittest.TestCase):
    def test_valid_case_intake_passes(self) -> None:
        payload = low_risk_case().to_dict()
        self.assertIs(validate(payload, "case-intake"), payload)

    def test_missing_required_field_raises(self) -> None:
        payload = low_risk_case().to_dict()
        del payload["product_name"]
        with self.assertRaises(ContractValidationError):
            validate(payload, "case-intake")

    def test_enum_violation_raises(self) -> None:
        payload = low_risk_case().to_dict()
        payload["data_classification"] = "top-secret"
        with self.assertRaises(ContractValidationError):
            validate(payload, "case-intake")

    def test_min_items_violation_raises(self) -> None:
        payload = low_risk_case().to_dict()
        payload["platform"] = []
        with self.assertRaises(ContractValidationError):
            validate(payload, "case-intake")

    def test_additional_property_violation_raises(self) -> None:
        payload = low_risk_case().to_dict()
        payload["model_selected_route"] = "low"
        with self.assertRaises(ContractValidationError):
            validate(payload, "case-intake")

    def test_packet_sha256_is_deterministic(self) -> None:
        packet = _compose_medium_packet()
        self.assertEqual(packet.sha256, packet.compute_sha256())
        again = _compose_medium_packet()
        self.assertEqual(packet.sha256, again.sha256)

    def test_policy_result_validates_against_schema(self) -> None:
        packet_state = _run_medium()
        payload = packet_state.policy_result.to_dict()
        self.assertIs(validate(payload, "policy-result"), payload)

    def test_source_coordinates_support_one_based_text_lines(self) -> None:
        payload = SourceCoordinates(
            source_id="evidence-0001",
            filename="coi.txt",
            sha256="a" * 64,
            line=4,
        ).to_dict()
        self.assertIs(validate(payload, "source-coordinates"), payload)
        invalid = {**payload, "line": 0}
        with self.assertRaises(ContractValidationError):
            validate(invalid, "source-coordinates")

    def test_email_validation_rejects_whitespace_controls_and_extra_at_signs(self) -> None:
        for email in (
            "requester @example.edu",
            "requester@example.edu\nBcc:attacker@example.com",
            "requester@@example.edu",
            ".requester@example.edu",
            "requester@-example.edu",
        ):
            with self.subTest(email=email):
                payload = low_risk_case().to_dict()
                payload["requester"]["email"] = email
                with self.assertRaises(ContractValidationError):
                    validate(payload, "case-intake")


class AuditTests(unittest.TestCase):
    def test_forbidden_detail_key_rejected(self) -> None:
        log = AuditLog(sink=InMemoryAuditSink())
        event = AuditEvent(
            event_id="e1",
            event_type="test",
            case_id="c1",
            occurred_at="2026-07-14T12:00:00+00:00",
            actor_type=ActorType.SYSTEM,
            detail={"document_body": "sensitive text"},
        )
        with self.assertRaises(ValueError):
            log.emit(event)

    def test_safe_detail_is_emitted(self) -> None:
        sink = InMemoryAuditSink()
        log = AuditLog(sink=sink)
        log.record(
            event_id="e1",
            event_type="policy.evaluated",
            case_id="c1",
            occurred_at="2026-07-14T12:00:00+00:00",
            actor_type=ActorType.SYSTEM,
            detail={"risk_route": "medium"},
        )
        self.assertEqual(len(sink.events), 1)


def _run_medium() -> ReviewGraphState:
    wf = ReviewWorkflow(
        model=DeterministicModelClient(),
        software_index=ApprovedSoftwareIndex(sample_records()),
        ruleset=default_ruleset(),
        registry=default_conflict_registry(),
        audit=AuditLog(sink=InMemoryAuditSink()),
        checkpointer=InMemoryCheckpointer(),
        clock=lambda: "2026-07-14T12:00:00+00:00",
    )
    state = ReviewGraphState(case_id="CASE-M", case_input=medium_risk_case())
    wf.run_until_review(state)
    return state


def _compose_medium_packet():
    return _run_medium().draft_packet


if __name__ == "__main__":
    unittest.main()
