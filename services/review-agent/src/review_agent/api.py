"""Dependency-free local application API over the existing review workflow.

This module is the local adapter for the public REST contract. It composes
``ReviewWorkflow`` and ``MockServiceNowConnector``; it does not reimplement
lookup, policy, specialist, packet, or write-back behavior. The production
TypeScript Lambda adapter remains a Wednesday deployment concern.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from typing import Any

from .adapters.model import DeterministicModelClient
from .adapters.servicenow import (
    ConnectorError,
    MockServiceNowConnector,
    StaleRecordError,
    UnapprovedWriteError,
    UnknownRecordError,
)
from .audit.log import AuditLog, InMemoryAuditSink
from .contracts.case import CaseIntake, DataClassification, Requester
from .contracts.common import SourceCoordinates
from .contracts.graph_state import ReviewGraphState, WorkflowStatus
from .contracts.packet import PacketSection
from .contracts.schema import ContractValidationError, validate, validate_definition
from .contracts.servicenow import HumanDecision, ReviewAction
from .contracts.software import ApprovedSoftwareRecord
from .lookup.approved_software import ApprovedSoftwareIndex
from .orchestration.graph import ReviewWorkflow
from .orchestration.state import InMemoryCheckpointer
from .policy.conflicts import default_conflict_registry
from .policy.rules import default_ruleset
from .samples import escalation_case, low_risk_case, sample_records

_FIXED_CLOCK = "2026-07-14T20:00:00+00:00"


class LocalApiError(RuntimeError):
    """Expected application error with an HTTP-compatible status and code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(slots=True)
class _CaseRecord:
    state: ReviewGraphState
    workflow: ReviewWorkflow
    audit: AuditLog
    audit_sink: InMemoryAuditSink
    documents: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class LocalWritebackConfig:
    table: str = "sc_req_item"
    state_field: str = "state"
    outcome_field: str = "u_review_outcome"
    route_field: str = "u_risk_route"
    notes_field: str = "work_notes"
    approved_state: str = "ready_for_committee"
    approved_outcome: str = "Human-reviewed technology review packet"

    def fields_for(self, *, route: str, decision_version: int) -> dict[str, str]:
        return {
            self.state_field: self.approved_state,
            self.outcome_field: self.approved_outcome,
            self.route_field: route,
            self.notes_field: f"Decision v{decision_version} recorded by configured reviewer",
        }


class LocalReviewApi:
    """In-memory local API used by the browser workspace and deterministic tests."""

    def __init__(
        self,
        *,
        seed_demo: bool = True,
        writeback_config: LocalWritebackConfig | None = None,
    ) -> None:
        records = sample_records() + [
            ApprovedSoftwareRecord(
                record_id="approved-row-172",
                canonical_name="LabArchives ELN",
                vendor="LabArchives, Inc.",
                source_row={"Product Name": "LabArchives ELN", "Vendor": "LabArchives, Inc."},
                source_coordinates=SourceCoordinates(
                    source_id="src:approved-software-export",
                    filename="SNOW Export_approved_software_database.xlsx",
                    sheet="approved_software",
                    row=172,
                ),
            )
        ]
        self._software_index = ApprovedSoftwareIndex(records)
        self._writeback_config = writeback_config or LocalWritebackConfig()
        self._connector = MockServiceNowConnector()
        self._cases: dict[str, _CaseRecord] = {}
        self._case_sequence = 0
        if seed_demo:
            self._seed_demo_cases()

    def list_review_queue(self) -> dict[str, Any]:
        items = [self._queue_item(record.state) for record in self._cases.values()]
        order = {
            "awaiting_match_confirmation": 0,
            "awaiting_review": 1,
            "escalated": 2,
            "analysis": 3,
            "closed": 4,
        }
        items.sort(key=lambda item: (order.get(item["state"]["status"], 9), item["case_id"]))
        response = {"items": items, "simulated": True}
        return validate(response, "review-queue")

    def create_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        intake = self._parse_intake(payload)
        self._case_sequence += 1
        case_id = f"CASE-LOCAL-{self._case_sequence:03d}"
        record = self._add_case(case_id, intake)
        return {"case_id": case_id, "state": record.state.to_dict()}

    def add_document(self, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self._require_case(case_id)
        filename = self._required_text(payload, "filename")
        document_id = str(payload.get("document_id") or f"DOC-{len(record.documents) + 1:03d}")
        metadata = {
            "document_id": document_id,
            "filename": filename,
            "content_type": str(payload.get("content_type") or "application/octet-stream"),
            "scope": str(payload.get("scope") or "case"),
            "untrusted": True,
        }
        record.documents.append(metadata)
        record.state.document_ids.append(document_id)
        record.audit.record(
            event_id=f"{case_id}-document-{len(record.documents):03d}",
            event_type="document.registered",
            case_id=case_id,
            occurred_at=self._now(),
            actor_type=self._requester_actor(),
            workflow_version=record.state.workflow_version,
            detail={"document_id": document_id, "content_type": metadata["content_type"]},
        )
        return metadata

    def analyze_case(
        self,
        case_id: str,
        *,
        confirmed_match_id: str | None = None,
        reviewer_id: str | None = None,
    ) -> dict[str, Any]:
        record = self._require_case(case_id)
        state = record.state
        if state.status is WorkflowStatus.INTAKE:
            record.workflow.run_until_review(state)
        if state.status is WorkflowStatus.AWAITING_MATCH_CONFIRMATION:
            if confirmed_match_id is None:
                return self._case_payload(record)
            allowed = {match.record_id for match in state.software_candidates if match.requires_confirmation}
            if confirmed_match_id not in allowed:
                raise LocalApiError(400, "invalid_match", "match confirmation is not a current candidate")
            if reviewer_id is None or not reviewer_id.strip():
                raise LocalApiError(400, "reviewer_required", "match confirmation requires reviewer_id")
            record.workflow.confirm_match(
                state,
                confirmed_match_id,
                reviewer_id=reviewer_id.strip(),
            )
        return self._case_payload(record)

    def review_case(self, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self._require_case(case_id)
        state = record.state
        try:
            validate_definition(payload, "servicenow-operations", "HumanDecision")
        except ContractValidationError as error:
            raise LocalApiError(400, "invalid_decision", str(error)) from error
        payload_case_id = payload.get("case_id")
        if payload_case_id != case_id:
            raise LocalApiError(400, "case_mismatch", "decision case_id must match the path")
        if payload.get("approved_fields"):
            raise LocalApiError(
                400,
                "configured_fields_only",
                "approved_fields are supplied by deterministic backend configuration",
            )
        reviewer_id = self._required_text(payload, "reviewer_id")
        decided_at = self._required_text(payload, "decided_at")
        if state.status not in {
            WorkflowStatus.AWAITING_REVIEW,
            WorkflowStatus.ESCALATED,
            WorkflowStatus.WRITEBACK,
        }:
            raise LocalApiError(409, "not_reviewable", "case is not at a human review boundary")

        try:
            action = ReviewAction(str(payload["action"]))
        except (KeyError, ValueError) as error:
            raise LocalApiError(400, "invalid_action", "action must be approve, reject, or request_info") from error

        if state.status is WorkflowStatus.ESCALATED and action is ReviewAction.APPROVE:
            raise LocalApiError(403, "escalation_locked", "an escalated case cannot be approved")
        if action is ReviewAction.APPROVE and state.draft_packet is None:
            raise LocalApiError(409, "packet_required", "approval requires a generated packet")

        raw_edits = payload.get("edits", [])
        if raw_edits is None:
            raw_edits = []
        if not isinstance(raw_edits, list):
            raise LocalApiError(400, "invalid_edits", "edits must be an array")
        current_version = state.draft_packet.packet_version if state.draft_packet else 1
        version_increment = 1 if state.human_decision is not None or raw_edits else 0
        expected_decision_version = current_version + version_increment
        decision_version = self._required_positive_int(payload, "decision_version")
        if decision_version != expected_decision_version:
            raise LocalApiError(
                409,
                "stale_decision_version",
                f"expected decision version {expected_decision_version}",
            )

        edits = self._apply_packet_edits(
            record,
            raw_edits,
            decision_version,
            reviewer_id=reviewer_id,
        )
        route = state.policy_result.risk_route.value if state.policy_result else "escalate"
        approved_fields = self._writeback_config.fields_for(
            route=route,
            decision_version=decision_version,
        )
        decision = HumanDecision(
            case_id=case_id,
            decision_version=decision_version,
            reviewer_id=reviewer_id,
            action=action,
            decided_at=decided_at,
            approved_fields=approved_fields if action is ReviewAction.APPROVE else {},
            comments=str(payload["comments"]) if payload.get("comments") else None,
            edits=tuple(edits),
        )
        state.write_preview = None
        state.write_result = None
        state.idempotency_key = None
        state.human_decision = decision
        if action is ReviewAction.REJECT:
            state.status = WorkflowStatus.CLOSED
        elif action is ReviewAction.REQUEST_INFO:
            state.status = (
                WorkflowStatus.ESCALATED
                if state.policy_result is not None and state.policy_result.escalated
                else WorkflowStatus.AWAITING_REVIEW
            )
        else:
            state.status = WorkflowStatus.AWAITING_REVIEW

        record.audit.record(
            event_id=f"{case_id}-decision-{decision_version:03d}",
            event_type="review.decision_recorded",
            case_id=case_id,
            occurred_at=decision.decided_at,
            actor_type=self._reviewer_actor(),
            actor_id=decision.reviewer_id,
            workflow_version=state.workflow_version,
            policy_version=state.policy_result.policy_version if state.policy_result else None,
            decision_version=decision_version,
            detail={"action": action.value, "packet_edit_count": len(edits)},
        )
        return self._case_payload(record)

    def preview_servicenow(self, case_id: str) -> dict[str, Any]:
        record = self._require_case(case_id)
        decision = record.state.human_decision
        if decision is None or decision.action is not ReviewAction.APPROVE:
            raise LocalApiError(403, "approval_required", "preview requires an approved decision")
        try:
            record.workflow.preview_writeback(record.state, self._connector, decision)
        except (ConnectorError, PermissionError) as error:
            raise self._connector_error(error) from error
        return self._case_payload(record)

    def commit_servicenow(self, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self._require_case(case_id)
        decision = record.state.human_decision
        if decision is None:
            raise LocalApiError(403, "approval_required", "commit requires an approved decision")
        second_confirmation = payload.get("second_confirmation") is True
        expected_version = self._required_positive_int(payload, "expected_version")
        preview = record.state.write_preview
        if preview is None:
            raise LocalApiError(409, "preview_required", "commit requires a current write preview")
        if preview.decision_version != decision.decision_version:
            raise LocalApiError(409, "preview_mismatch", "preview does not match the current decision")
        if expected_version != preview.expected_record_version:
            raise LocalApiError(
                409,
                "preview_mismatch",
                f"expected version must match displayed preview version {preview.expected_record_version}",
            )
        packet = record.state.draft_packet
        if (
            packet is None
            or packet.sha256 is None
            or packet.packet_version != preview.packet_version
            or packet.sha256 != preview.packet_sha256
        ):
            raise LocalApiError(409, "preview_mismatch", "packet changed after the displayed preview")
        try:
            record.workflow.commit_writeback(
                record.state,
                self._connector,
                decision,
                second_confirmation=second_confirmation,
                expected_version=expected_version,
            )
        except (ConnectorError, PermissionError) as error:
            raise self._connector_error(error) from error
        return self._case_payload(record)

    def get_packet(self, case_id: str) -> dict[str, Any]:
        record = self._require_case(case_id)
        packet = record.state.draft_packet
        if packet is None:
            raise LocalApiError(404, "packet_not_found", "case has no generated packet")
        return packet.to_dict()

    def get_state(self, case_id: str) -> dict[str, Any]:
        return self._require_case(case_id).state.to_dict()

    def get_audit_events(self, case_id: str) -> list[dict[str, Any]]:
        record = self._require_case(case_id)
        return [event.to_dict() for event in record.audit_sink.events]

    def _seed_demo_cases(self) -> None:
        labarchives = CaseIntake(
            product_name="LabArchives",
            vendor_name="LabArchives, LLC",
            requester=Requester(
                name="Sample Requester", email="requester@example.edu", department="College of Science"
            ),
            use_case="Electronic research notebooks for a sanitized classroom pilot.",
            expected_users=120,
            platform=["web"],
            data_classification=DataClassification.INTERNAL,
            estimated_cost_usd=8_000.0,
            integrations=["Canvas"],
            uses_sso=True,
            uses_ai=True,
            accessibility_context="Faculty and student classroom use.",
            official_domain="labarchives.example",
            classroom_or_public_use=True,
        )
        seeded = (
            ("TR-260714-014", labarchives, "RITM0012846"),
            ("TR-260714-018", low_risk_case(), "RITM0012847"),
            ("TR-260714-011", escalation_case(), "RITM0012848"),
        )
        for case_id, intake, record_id in seeded:
            record = self._add_case(case_id, intake, record_id=record_id)
            record.workflow.run_until_review(record.state)

    def _add_case(
        self, case_id: str, intake: CaseIntake, *, record_id: str | None = None
    ) -> _CaseRecord:
        if case_id in self._cases:
            raise LocalApiError(409, "duplicate_case", f"case {case_id} already exists")
        sink = InMemoryAuditSink()
        audit = AuditLog(sink=sink)
        workflow = ReviewWorkflow(
            model=DeterministicModelClient(),
            software_index=self._software_index,
            ruleset=default_ruleset(),
            registry=default_conflict_registry(),
            audit=audit,
            checkpointer=InMemoryCheckpointer(),
            clock=lambda: _FIXED_CLOCK,
        )
        state = ReviewGraphState(case_id=case_id, case_input=intake)
        record = _CaseRecord(state=state, workflow=workflow, audit=audit, audit_sink=sink)
        self._cases[case_id] = record
        target_id = record_id or f"RITMLOCAL{len(self._cases):04d}"
        config = self._writeback_config
        self._connector.seed_record(
            record_id=target_id,
            table=config.table,
            fields={
                config.state_field: "under_review",
                config.outcome_field: "",
                config.route_field: "unassigned",
                config.notes_field: "Review in progress",
            },
        )
        self._connector.configure_case(
            case_id=case_id,
            table=config.table,
            record_id=target_id,
        )
        return record

    def _case_payload(self, record: _CaseRecord) -> dict[str, Any]:
        response = {
            "state": record.state.to_dict(),
            "queue_item": self._queue_item(record.state),
            "audit_events": [event.to_dict() for event in record.audit_sink.events],
            "simulated": True,
        }
        return validate(response, "case-action-response")

    @staticmethod
    def _queue_item(state: ReviewGraphState) -> dict[str, Any]:
        status_labels = {
            WorkflowStatus.AWAITING_MATCH_CONFIRMATION: "Ready for review",
            WorkflowStatus.AWAITING_REVIEW: "Ready for review",
            WorkflowStatus.ESCALATED: "Needs evidence",
            WorkflowStatus.WRITEBACK: "Ready for review",
            WorkflowStatus.CLOSED: "Completed",
        }
        stage_labels = {
            WorkflowStatus.AWAITING_MATCH_CONFIRMATION: "Match confirmation",
            WorkflowStatus.AWAITING_REVIEW: "Packet ready",
            WorkflowStatus.ESCALATED: "Safe escalation",
            WorkflowStatus.WRITEBACK: "Write-back preview",
            WorkflowStatus.CLOSED: "Review closed",
        }
        candidate = state.software_candidates[0] if state.software_candidates else None
        route = state.policy_result.risk_route.value if state.policy_result else "pending"
        route_labels = {
            "approved": "Low risk",
            "low": "Low risk",
            "medium": "Medium risk",
            "high": "Safe escalation",
            "escalate": "Safe escalation",
            "unknown": "Safe escalation",
            "pending": "Pending route",
        }
        match_method = candidate.match_method.value if candidate else "none"
        match_labels = {
            "exact": "Exact match",
            "alias": "Alias match",
            "vendor_product": "Vendor + product",
            "fuzzy": "Fuzzy candidate",
            "semantic": "Semantic candidate",
            "none": "No approved match",
        }
        source = candidate.source_row_ref if candidate else None
        match_detail = (
            f"{source.filename or source.source_id} · Row {source.row}"
            if source and source.row is not None
            else "No approved-software candidate"
        )
        return {
            "case_id": state.case_id,
            "product": state.case_input.product_name,
            "vendor": state.case_input.vendor_name,
            "requester": state.case_input.requester.department or state.case_input.requester.name,
            "status": status_labels.get(state.status, "Analyzing"),
            "route": route_labels[route],
            "match": match_labels[match_method],
            "match_detail": match_detail,
            "stage": stage_labels.get(state.status, state.status.value.replace("_", " ").title()),
            "updated": "Local API",
            "owner": "Alex Reviewer",
            "state": state.to_dict(),
        }

    def _apply_packet_edits(
        self,
        record: _CaseRecord,
        raw_edits: list[object],
        decision_version: int,
        *,
        reviewer_id: str,
    ) -> list[dict[str, str]]:
        packet = record.state.draft_packet
        if raw_edits and packet is None:
            raise LocalApiError(409, "packet_required", "packet edits require a packet")
        if packet is None:
            return []

        sections = {section.key: section for section in packet.sections}
        validated: list[tuple[PacketSection, str, str]] = []
        for raw in raw_edits:
            if not isinstance(raw, dict):
                raise LocalApiError(400, "invalid_edit", "each edit must be an object")
            if set(raw) - {"section_key", "body"}:
                raise LocalApiError(400, "invalid_edit", "packet edits contain unsupported fields")
            key = self._required_text(raw, "section_key")
            body = self._required_text(raw, "body")
            section = sections.get(key)
            if section is None or not section.editable:
                raise LocalApiError(400, "invalid_edit", f"section {key!r} is not editable")
            validated.append((section, key, body))

        if raw_edits or record.state.human_decision is not None:
            packet.packet_version = decision_version
        edits: list[dict[str, str]] = []
        for section, key, body in validated:
            section.body = body
            edit = {"section_key": key, "body": body}
            edits.append(edit)
            record.state.human_edits.append(
                {
                    "packet_version": packet.packet_version,
                    "reviewer_id": reviewer_id,
                    **edit,
                }
            )
        packet.sha256 = packet.compute_sha256()
        return edits

    def _parse_intake(self, payload: dict[str, Any]) -> CaseIntake:
        try:
            classification = DataClassification(str(payload["data_classification"]).lower())
        except (KeyError, ValueError) as error:
            raise LocalApiError(400, "invalid_classification", "invalid data classification") from error
        requester_raw = payload.get("requester")
        if not isinstance(requester_raw, dict):
            raise LocalApiError(400, "invalid_requester", "requester must be an object")
        requester = Requester(
            name=self._required_text(requester_raw, "name"),
            email=self._required_text(requester_raw, "email"),
            department=str(requester_raw["department"]) if requester_raw.get("department") else None,
        )
        platform = payload.get("platform")
        if not isinstance(platform, list) or not platform or not all(isinstance(value, str) and value.strip() for value in platform):
            raise LocalApiError(400, "invalid_platform", "platform must contain at least one value")
        integrations = payload.get("integrations", [])
        if not isinstance(integrations, list) or not all(isinstance(value, str) for value in integrations):
            raise LocalApiError(400, "invalid_integrations", "integrations must be an array of strings")
        return CaseIntake(
            product_name=self._required_text(payload, "product_name"),
            vendor_name=self._required_text(payload, "vendor_name"),
            requester=requester,
            use_case=self._required_text(payload, "use_case"),
            expected_users=self._required_nonnegative_int(payload, "expected_users"),
            platform=[value.strip() for value in platform],
            data_classification=classification,
            estimated_cost_usd=self._required_nonnegative_float(payload, "estimated_cost_usd"),
            integrations=list(integrations),
            uses_sso=payload.get("uses_sso") is True,
            uses_ai=payload.get("uses_ai") is True,
            accessibility_context=str(payload["accessibility_context"]) if payload.get("accessibility_context") else None,
            official_domain=str(payload["official_domain"]) if payload.get("official_domain") else None,
            classroom_or_public_use=payload.get("classroom_or_public_use") is True,
        )

    def _require_case(self, case_id: str) -> _CaseRecord:
        record = self._cases.get(case_id)
        if record is None:
            raise LocalApiError(404, "case_not_found", f"case {case_id} not found")
        return record

    @staticmethod
    def _required_text(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise LocalApiError(400, "validation_error", f"{key} is required")
        return value.strip()

    @staticmethod
    def _required_positive_int(payload: dict[str, Any], key: str) -> int:
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise LocalApiError(400, "validation_error", f"{key} must be a positive integer")
        return value

    @staticmethod
    def _required_nonnegative_int(payload: dict[str, Any], key: str) -> int:
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LocalApiError(400, "validation_error", f"{key} must be a nonnegative integer")
        return value

    @staticmethod
    def _required_nonnegative_float(payload: dict[str, Any], key: str) -> float:
        value = payload.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise LocalApiError(400, "validation_error", f"{key} must be a finite nonnegative number")
        return float(value)

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    @staticmethod
    def _reviewer_actor():
        from .contracts.audit import ActorType

        return ActorType.REVIEWER

    @staticmethod
    def _requester_actor():
        from .contracts.audit import ActorType

        return ActorType.REQUESTER

    @staticmethod
    def _connector_error(error: Exception) -> LocalApiError:
        if isinstance(error, StaleRecordError):
            return LocalApiError(409, "stale_record", str(error))
        if isinstance(error, UnknownRecordError):
            return LocalApiError(404, "record_not_found", str(error))
        if isinstance(error, (UnapprovedWriteError, PermissionError)):
            return LocalApiError(403, "write_forbidden", str(error))
        return LocalApiError(400, "connector_error", str(error))
