"""Dependency-free local application API over the existing review workflow.

This module is the local adapter for the public REST contract. It composes
``ReviewWorkflow`` and ``MockServiceNowConnector``; it does not reimplement
lookup, policy, specialist, packet, or write-back behavior. The production
TypeScript Lambda adapter remains a Wednesday deployment concern.
"""

from __future__ import annotations

import datetime
import hashlib
import math
import os
from dataclasses import dataclass, field
from typing import Any

from .adapters.email import EmailSender, build_email_sender
from .adapters.model import DeterministicModelClient, ModelClient, build_model_client
from .adapters.notifications import Notifier, build_notifier
from .adapters.servicenow import (
    ConnectorError,
    MockServiceNowConnector,
    StaleRecordError,
    UnapprovedWriteError,
    UnknownRecordError,
)
from .adapters.storage import InMemoryStorage, StorageClient
from .audit.log import AuditLog, InMemoryAuditSink
from .config import AppConfig
from .contracts.case import CaseIntake, DataClassification, Requester
from .contracts.common import SourceCoordinates
from .contracts.graph_state import ReviewGraphState, WorkflowStatus
from .contracts.packet import PacketSection
from .contracts.schema import ContractValidationError, validate, validate_definition
from .contracts.servicenow import HumanDecision, ReviewAction
from .contracts.software import ApprovedSoftwareRecord
from .contracts.vendor import CaseLifecycle, InviteStatus, SoftwareCatalogEntry
from .ingestion.software_workbook import normalized_identity
from .lookup.approved_software import ApprovedSoftwareIndex
from .orchestration.graph import ReviewWorkflow
from .orchestration.state import InMemoryCheckpointer
from .packet import render_packet_pdf
from .policy.conflicts import default_conflict_registry
from .policy.rules import default_ruleset
from .profiles.service import ProfileError, ReviewProfileService
from .samples import escalation_case, low_risk_case, sample_records
from .vendor.repository import InMemoryVendorRepository
from .vendor.service import VendorBackend, VendorBackendError

_FIXED_CLOCK = "2026-07-14T20:00:00+00:00"
_UNSET = object()


def _default_packet_storage(config: AppConfig) -> StorageClient:
    """Generated-packet artifact store: S3 on AWS, in-memory locally.

    On AWS (``USE_LOCAL_FAKES=false``) with a configured normalized/generated
    bucket, packets are written to S3 with SSE-KMS and served via a
    CloudFront-safe or presigned link. Locally, an in-memory store returns a
    CloudFront-safe relative path so the browser flow works without AWS.
    """
    bucket = config.aws.generated_bucket
    if not config.use_local_fakes and bucket:
        from .adapters.storage import S3Storage

        return S3Storage(
            bucket=bucket,
            region=config.aws.region,
            kms_key_id=os.environ.get("GENERATED_BUCKET_KMS_KEY_ID") or None,
            cloudfront_base_url=os.environ.get("PACKET_CLOUDFRONT_BASE_URL") or None,
        )
    return InMemoryStorage(
        cloudfront_base_url=os.environ.get("PACKET_CLOUDFRONT_BASE_URL") or None
    )


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
        model_client: ModelClient | None = None,
        packet_storage: StorageClient | None = None,
        notifier: Notifier | None = None,
        email_sender: EmailSender | None = None,
        config: AppConfig | None = None,
    ) -> None:
        # Live-AI wiring: the model client is constructed from configuration so
        # that USE_LOCAL_FAKES=false injects a live Bedrock client into the
        # research/security/accessibility path. It defaults to the deterministic
        # fixture only when local fakes are enabled (issue #27).
        self._config = config or AppConfig.from_env()
        self._model_client = model_client or build_model_client(self._config)
        self._packet_storage: StorageClient = packet_storage or _default_packet_storage(self._config)
        self._notifier: Notifier = notifier or build_notifier(self._config)
        self._email_sender: EmailSender = email_sender or build_email_sender(self._config)
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
        self._vendor_repository = InMemoryVendorRepository()
        local_clock = lambda: datetime.datetime.now(datetime.timezone.utc)
        self._profiles = ReviewProfileService(self._vendor_repository, clock=local_clock)
        self._seed_review_profiles()
        self._vendor = VendorBackend(
            self._vendor_repository,
            self._profiles,
            clock=local_clock,
        )
        catalog_entries = []
        for record in records:
            row_number = record.source_coordinates.row if record.source_coordinates else 2
            catalog_entries.append(
                SoftwareCatalogEntry(
                    record_id=record.record_id,
                    canonical_name=record.canonical_name,
                    vendor=record.vendor,
                    normalized_identity=normalized_identity(
                        record.canonical_name,
                        record.short_name,
                        record.audience,
                        tuple(record.platform),
                    ),
                    source_row=row_number or 2,
                    source_hash=hashlib.sha256(
                        (
                            record.source_coordinates.source_id
                            if record.source_coordinates
                            else record.record_id
                        ).encode("utf-8")
                    ).hexdigest(),
                    raw_values=dict(record.source_row),
                    supported_software=record.support,
                    campus_license=record.licensing,
                    aliases=tuple(record.aliases),
                    short_name=record.short_name,
                    platform=tuple(record.platform),
                    audience=record.audience,
                )
            )
        self._vendor.put_catalog_entries(catalog_entries)
        self._seed_servicenow_import()
        self._cases: dict[str, _CaseRecord] = {}
        self._case_sequence = 0
        if seed_demo:
            self._seed_demo_cases()

    def _seed_review_profiles(self) -> None:
        fixtures = {
            "security": [
                {
                    "requirement_id": "SEC.DATA.001",
                    "question": "Describe encryption for institutional data in transit and at rest.",
                    "source_citation": {"source_id": "fixture:security-profile", "section": "data-protection"},
                    "expected_evidence": ["security whitepaper", "SOC 2 excerpt"],
                    "output_fields": ["security_summary"],
                    "remediation_guidance": "Provide current encryption documentation.",
                }
            ],
            "accessibility": [
                {
                    "requirement_id": "A11Y.VPAT.001",
                    "question": "Provide the current VPAT or Accessibility Conformance Report.",
                    "source_citation": {"source_id": "fixture:accessibility-profile", "section": "vpat"},
                    "expected_evidence": ["VPAT", "ACR"],
                    "output_fields": ["accessibility_findings"],
                    "remediation_guidance": "Provide a current product-specific accessibility report.",
                }
            ],
        }
        for profile_key, criteria in fixtures.items():
            profile = self._profiles.create_draft(profile_key, criteria)
            self._profiles.fixture_test(profile.profile_version_id)
            self._profiles.activate(profile.profile_version_id)

    def _seed_servicenow_import(self) -> None:
        self._connector.seed_record(
            record_id="RITM0098200",
            table=self._writeback_config.table,
            fields={
                "number": "RITM0098200",
                "short_description": "Synthetic Scheduling Tool",
                "u_vendor": "Example Vendor",
                "description": "Sanitized scheduling use case for a public event.",
                "u_expected_users": 25,
                "u_platform": ["web"],
                "u_data_classification": "public",
                "u_estimated_cost_usd": 0,
                "u_integrations": [],
                "u_uses_sso": False,
                "u_uses_ai": False,
                "u_classroom_or_public_use": True,
                "requested_for_name": "Sample Requester",
                "requested_for_email": "requester@example.edu",
                "requested_for_department": "Library",
            },
        )

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
        if state.status in {WorkflowStatus.AWAITING_REVIEW, WorkflowStatus.ESCALATED}:
            self._transition_vendor_case(case_id, CaseLifecycle.NEEDS_REVIEW)
            self._notify(
                case_id,
                "case.needs_review",
                f"Case {case_id} completed analysis and is ready for human review.",
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

        raw_vendor_comment = payload.get("vendor_visible_comment")
        vendor_visible_comment = (
            raw_vendor_comment.strip() if isinstance(raw_vendor_comment, str) else None
        )
        if raw_vendor_comment is not None and not vendor_visible_comment:
            raise LocalApiError(
                400,
                "invalid_vendor_visible_comment",
                "vendor_visible_comment must contain visible text",
            )
        raw_vendor_actions = payload.get("vendor_next_actions", [])
        vendor_next_actions = tuple(item.strip() for item in raw_vendor_actions)
        if any(not item for item in vendor_next_actions):
            raise LocalApiError(
                400,
                "invalid_vendor_next_actions",
                "vendor_next_actions must contain visible text",
            )
        if action is not ReviewAction.REQUEST_INFO and vendor_next_actions:
            raise LocalApiError(
                400,
                "invalid_vendor_next_actions",
                "vendor_next_actions are only allowed when requesting information",
            )

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
        lifecycle_target = {
            ReviewAction.APPROVE: CaseLifecycle.APPROVED,
            ReviewAction.REJECT: CaseLifecycle.DECLINED,
            ReviewAction.REQUEST_INFO: CaseLifecycle.CHANGES_REQUESTED,
        }.get(action)
        if lifecycle_target is not None:
            self._transition_vendor_case(
                case_id,
                lifecycle_target,
                vendor_visible_comment=vendor_visible_comment,
                vendor_next_actions=vendor_next_actions,
            )
            self._notify(
                case_id,
                f"review.{lifecycle_target.value}",
                f"Case {case_id} decision recorded: {action.value} (v{decision_version}).",
            )
            self._email_vendor_outcome(
                case_id,
                lifecycle_target,
                product_name=record.state.case_input.product_name,
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
        self._transition_vendor_case(case_id, CaseLifecycle.WRITEBACK_COMPLETE)
        return self._case_payload(record)

    def get_packet(self, case_id: str) -> dict[str, Any]:
        record = self._require_case(case_id)
        packet = record.state.draft_packet
        if packet is None:
            raise LocalApiError(404, "packet_not_found", "case has no generated packet")
        return packet.to_dict()

    def get_packet_pdf(self, case_id: str) -> dict[str, Any]:
        """Render the packet to a real PDF, store it, and return a view link.

        The bytes are stored through the artifact store (S3 with SSE-KMS on AWS,
        in-memory locally) under a deterministic, version- and hash-qualified key.
        Regenerating is idempotent because the packet content hash is stable.
        Material citations travel with the response so no claim is unsupported.
        """
        record = self._require_case(case_id)
        packet = record.state.draft_packet
        if packet is None:
            raise LocalApiError(404, "packet_not_found", "case has no generated packet")
        if packet.sha256 is None:
            packet.sha256 = packet.compute_sha256()
        title = (
            f"VETTED Evidence Packet — {record.state.case_input.product_name} "
            f"({record.state.case_input.vendor_name})"
        )
        pdf_bytes = render_packet_pdf(packet, title=title)
        key = (
            f"generated/{self._config.app_env}/{case_id}/"
            f"packet-v{packet.packet_version}-{packet.sha256[:16]}.pdf"
        )
        stored_sha = self._packet_storage.put_object(key=key, body=pdf_bytes)
        view_url = self._packet_storage.view_url(key=key, content_type="application/pdf")
        simulated = isinstance(self._packet_storage, InMemoryStorage)
        return {
            "case_id": case_id,
            "packet_id": packet.packet_id,
            "packet_version": packet.packet_version,
            "packet_type": packet.packet_type.value,
            "key": key,
            "view_url": view_url,
            "content_type": "application/pdf",
            "size_bytes": len(pdf_bytes),
            "pdf_sha256": stored_sha,
            "packet_sha256": packet.sha256,
            "citations": [citation.to_dict() for citation in packet.citations],
            "simulated_storage": simulated,
        }

    def get_state(self, case_id: str) -> dict[str, Any]:
        return self._require_case(case_id).state.to_dict()

    def get_audit_events(self, case_id: str) -> list[dict[str, Any]]:
        record = self._require_case(case_id)
        return [event.to_dict() for event in record.audit_sink.events]


    # Vendor and administrator API surface -----------------------------------

    def list_vendors(self) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self._vendor.list_vendors()]}

    def get_vendor_record(self, vendor_id: str) -> dict[str, Any]:
        return self._vendor_call(lambda: self._vendor.get_vendor(vendor_id).to_dict())

    def create_vendor_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_vendor_payload(payload, "vendor-records", "CreateVendor")
        return self._vendor_call(
            lambda: self._vendor.create_vendor(
                payload["name"], payload.get("official_domain")
            ).to_dict()
        )

    def update_vendor_record(self, vendor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) - {"name", "official_domain"} or not payload:
            raise LocalApiError(400, "validation_error", "unsupported vendor update fields")
        return self._vendor_call(
            lambda: self._vendor.update_vendor(
                vendor_id,
                name=payload.get("name"),
                official_domain=payload.get("official_domain"),
            ).to_dict()
        )

    def delete_vendor_record(self, vendor_id: str) -> dict[str, Any]:
        self._vendor_call(lambda: self._vendor.delete_vendor(vendor_id))
        return {"deleted": True, "vendor_id": vendor_id}

    def list_vendor_products(self, vendor_id: str | None = None) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self._vendor.list_products(vendor_id)]}

    def get_vendor_product(self, product_id: str) -> dict[str, Any]:
        return self._vendor_call(lambda: self._vendor.get_product(product_id).to_dict())

    def create_vendor_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_vendor_payload(payload, "vendor-records", "CreateProduct")
        return self._vendor_call(
            lambda: self._vendor.create_product(payload["vendor_id"], payload["name"]).to_dict()
        )

    def update_vendor_product(self, product_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != {"name"}:
            raise LocalApiError(400, "validation_error", "product update requires only name")
        return self._vendor_call(
            lambda: self._vendor.update_product(product_id, name=payload["name"]).to_dict()
        )

    def delete_vendor_product(self, product_id: str) -> dict[str, Any]:
        self._vendor_call(lambda: self._vendor.delete_product(product_id))
        return {"deleted": True, "product_id": product_id}

    def list_vendor_contacts(self, vendor_id: str | None = None) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self._vendor.list_contacts(vendor_id)]}

    def get_vendor_contact(self, contact_id: str) -> dict[str, Any]:
        return self._vendor_call(lambda: self._vendor.get_contact(contact_id).to_dict())

    def create_vendor_contact(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_vendor_payload(payload, "vendor-records", "CreateContact")
        return self._vendor_call(
            lambda: self._vendor.create_contact(
                payload["vendor_id"], payload["name"], payload["email"]
            ).to_dict()
        )

    def update_vendor_contact(self, contact_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) - {"name", "email"} or not payload:
            raise LocalApiError(400, "validation_error", "unsupported contact update fields")
        return self._vendor_call(
            lambda: self._vendor.update_contact(
                contact_id, name=payload.get("name"), email=payload.get("email")
            ).to_dict()
        )

    def delete_vendor_contact(self, contact_id: str) -> dict[str, Any]:
        self._vendor_call(lambda: self._vendor.delete_contact(contact_id))
        return {"deleted": True, "contact_id": contact_id}

    def issue_vendor_invite(self, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_case(case_id)
        self._validate_vendor_payload(payload, "vendor-intake", "IssueInvite")
        return self._vendor_call(lambda: self._vendor.issue_invite(case_id, payload["contact_id"]))

    def list_case_invites(self, case_id: str) -> dict[str, Any]:
        self._require_case(case_id)
        return {
            "items": [invite.to_reviewer_dict() for invite in self._vendor.list_invites(case_id)]
        }

    def revoke_vendor_invite(self, invite_id: str) -> dict[str, Any]:
        return self._vendor_call(lambda: self._vendor.revoke_invite(invite_id))

    def resend_vendor_invite(self, invite_id: str) -> dict[str, Any]:
        return self._vendor_call(lambda: self._vendor.resend_invite(invite_id))

    def resolve_vendor_invite(self, token: str, *, mark_open: bool = False) -> dict[str, Any]:
        return self._vendor_call(lambda: self._vendor.resolve_invite(token, mark_open=mark_open))

    def vendor_add_evidence(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_vendor_payload(payload, "vendor-intake", "EvidenceMetadata")
        return self._vendor_call(lambda: self._vendor.add_evidence(token, payload).to_dict())

    def vendor_set_trust_center(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_vendor_payload(payload, "vendor-intake", "TrustCenter")
        return self._vendor_call(
            lambda: self._vendor.set_trust_center_url(
                token, payload["trust_center_url"]
            ).to_vendor_dict()
        )

    def vendor_save_answers(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_vendor_payload(payload, "vendor-intake", "Answers")
        return self._vendor_call(
            lambda: self._vendor.save_answers(token, payload["answers"]).to_vendor_dict()
        )

    def vendor_add_coverage(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_vendor_payload(payload, "vendor-intake", "Coverage")
        return self._vendor_call(
            lambda: self._vendor.add_coverage(
                token, payload["requirement_id"], payload["evidence_artifact_ids"]
            ).to_dict()
        )

    def vendor_questions(self, token: str) -> dict[str, Any]:
        return self._vendor_call(
            lambda: {
                "items": self._vendor.unresolved_questions(token),
                **self._vendor.intake_stage(token),
            }
        )

    def vendor_run_intake_analysis(self, token: str) -> dict[str, Any]:
        return self._vendor_call(
            lambda: self._vendor.run_intake_analysis(token).to_vendor_dict()
        )

    def vendor_finalize(self, token: str) -> dict[str, Any]:
        return self._vendor_call(
            lambda: self._vendor.finalize_submission(token).to_vendor_dict()
        )

    def vendor_review_status(self, token: str) -> dict[str, Any]:
        status = self._vendor_call(lambda: self._vendor.review_status(token))
        validate_definition(status, "vendor-intake", "ReviewStatus")
        return status

    def list_profiles(self) -> dict[str, Any]:
        return {"items": [profile.to_dict() for profile in self._profiles.list_versions()]}

    def create_profile_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_vendor_payload(payload, "review-profile-version", "CreateDraft")
        return self._profile_call(
            lambda: self._profiles.create_draft(
                payload["profile_key"], payload["criteria"]
            ).to_dict()
        )

    def update_profile_draft(self, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != {"criteria"} or not isinstance(payload["criteria"], list):
            raise LocalApiError(400, "validation_error", "profile update requires criteria")
        return self._profile_call(
            lambda: self._profiles.update_draft(profile_id, payload["criteria"]).to_dict()
        )

    def fixture_test_profile(self, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_vendor_payload(payload, "review-profile-version", "FixtureTest")
        return self._profile_call(
            lambda: self._profiles.fixture_test(profile_id, payload["fixtures"])
        )

    def activate_profile(self, profile_id: str) -> dict[str, Any]:
        return self._profile_call(lambda: self._profiles.activate(profile_id).to_dict())

    def rollback_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self._profile_call(lambda: self._profiles.get(profile_id))
        return self._profile_call(
            lambda: self._profiles.rollback(
                profile.profile_key, profile.profile_version_id
            ).to_dict()
        )

    def create_review_run(self, case_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        record = self._require_case(case_id)
        instructions = None
        if payload:
            if set(payload) - {"instructions"}:
                raise LocalApiError(400, "validation_error", "review run accepts only instructions")
            raw = payload.get("instructions")
            if raw is not None and not isinstance(raw, str):
                raise LocalApiError(400, "validation_error", "instructions must be a string")
            instructions = raw
        run = self._vendor_call(lambda: self._vendor.create_review_run(case_id, instructions))
        record.state.human_decision = None
        record.state.write_preview = None
        record.state.write_result = None
        record.state.idempotency_key = None
        return run.to_dict()

    def list_review_runs(self, case_id: str) -> dict[str, Any]:
        self._require_case(case_id)
        return {"items": [run.to_dict() for run in self._vendor.list_review_runs(case_id)]}

    def search_catalog(self, query: str, vendor: str | None = None) -> dict[str, Any]:
        return self._vendor_call(lambda: self._vendor.search_catalog(query, vendor))

    def list_catalog(
        self, query: str | None = None, limit: str | int | None = None, offset: str | int | None = None
    ) -> dict[str, Any]:
        parsed_limit = self._parse_bounded_int(limit, "limit", default=50, minimum=1, maximum=500)
        parsed_offset = self._parse_bounded_int(offset, "offset", default=0, minimum=0, maximum=10_000_000)
        clean_query = query.strip() if isinstance(query, str) and query.strip() else None
        return self._vendor_call(
            lambda: self._vendor.list_catalog(
                query=clean_query, limit=parsed_limit, offset=parsed_offset
            )
        )

    @staticmethod
    def _parse_bounded_int(
        value: str | int | None, name: str, *, default: int, minimum: int, maximum: int
    ) -> int:
        if value is None or value == "":
            return default
        if isinstance(value, bool):
            raise LocalApiError(400, "validation_error", f"{name} must be an integer")
        if isinstance(value, str):
            try:
                value = int(value)
            except ValueError as error:
                raise LocalApiError(400, "validation_error", f"{name} must be an integer") from error
        if not isinstance(value, int) or value < minimum or value > maximum:
            raise LocalApiError(
                400, "validation_error", f"{name} must be between {minimum} and {maximum}"
            )
        return value

    def confirm_catalog_match(self, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != {"match_method", "reviewer_id"}:
            raise LocalApiError(
                400,
                "validation_error",
                "catalog confirmation requires match_method and reviewer_id",
            )
        return self._vendor_call(
            lambda: self._vendor.confirm_catalog_match(
                record_id, payload["match_method"], payload["reviewer_id"]
            )
        )

    def preview_servicenow_import(self, external_id: str) -> dict[str, Any]:
        try:
            return self._connector.preview_import(external_id)
        except ConnectorError as error:
            raise self._connector_error(error) from error

    def create_from_servicenow_import(self, external_id: str) -> dict[str, Any]:
        preview = self.preview_servicenow_import(external_id)
        created = self.create_case(preview["mapped_values"])
        record = self._require_case(created["case_id"])
        record.audit.record(
            event_id=f"{created['case_id']}-servicenow-import",
            event_type="servicenow.imported",
            case_id=created["case_id"],
            occurred_at=self._now(),
            actor_type=self._reviewer_actor(),
            workflow_version=record.state.workflow_version,
            detail={
                "external_id": external_id,
                "mapping_version": preview["mapping_version"],
                "simulated": True,
            },
        )
        return {"preview": preview, "case": created}

    def integration_events(self) -> dict[str, Any]:
        return {
            "items": [
                event.to_dict()
                for event in self._vendor_repository.list(
                    "event", workspace_id=self._vendor.workspace_id
                )
            ]
        }

    @staticmethod
    def _validate_vendor_payload(payload: dict[str, Any], schema: str, definition: str) -> None:
        try:
            validate_definition(payload, schema, definition)
        except ContractValidationError as error:
            raise LocalApiError(400, "validation_error", str(error)) from error

    @staticmethod
    def _vendor_call(operation):
        try:
            return operation()
        except VendorBackendError as error:
            raise LocalApiError(error.status, error.code, str(error)) from error

    @staticmethod
    def _profile_call(operation):
        try:
            return operation()
        except ProfileError as error:
            raise LocalApiError(400, "profile_error", str(error)) from error
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
            model=self._model_client,
            software_index=self._software_index,
            ruleset=default_ruleset(),
            registry=default_conflict_registry(),
            audit=audit,
            checkpointer=InMemoryCheckpointer(),
            clock=lambda: _FIXED_CLOCK,
            specialist_profiles=self._specialist_profiles(),
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
        self._register_vendor_case(case_id, intake)
        return record

    def _register_vendor_case(self, case_id: str, intake: CaseIntake) -> None:
        vendor = next(
            (
                item
                for item in self._vendor.list_vendors()
                if item.name.casefold() == intake.vendor_name.casefold()
            ),
            None,
        )
        if vendor is None:
            vendor = self._vendor.create_vendor(
                intake.vendor_name,
                official_domain=intake.official_domain,
            )
        product = next(
            (
                item
                for item in self._vendor.list_products(vendor.vendor_id)
                if item.name.casefold() == intake.product_name.casefold()
            ),
            None,
        )
        if product is None:
            product = self._vendor.create_product(vendor.vendor_id, intake.product_name)
        scope = (
            f"data_classification={intake.data_classification.value};"
            f"platform={','.join(sorted(intake.platform))}"
        )
        self._vendor.register_case(case_id, product.product_id, intake.use_case, scope)

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

    def _specialist_profiles(self) -> dict[str, str]:
        """Map specialist key -> active profile version id for run metadata."""
        return {
            profile.profile_key: profile.profile_version_id
            for profile in self._profiles.active_profiles()
            if profile.profile_key in {"security", "accessibility"}
        }

    def _transition_vendor_case(
        self,
        case_id: str,
        target: CaseLifecycle,
        *,
        vendor_visible_comment: str | None | object = _UNSET,
        vendor_next_actions: tuple[str, ...] | object = _UNSET,
    ) -> None:
        """Persist the vendor-case lifecycle transition, tolerating benign no-ops."""
        kwargs: dict[str, Any] = {}
        if vendor_visible_comment is not _UNSET:
            kwargs["vendor_visible_comment"] = vendor_visible_comment
        if vendor_next_actions is not _UNSET:
            kwargs["vendor_next_actions"] = vendor_next_actions
        try:
            self._vendor.transition_case(case_id, target, **kwargs)
        except VendorBackendError:
            # A lifecycle that cannot legally advance (e.g. an already-closed
            # case) must not mask the primary reviewer action; the workflow
            # state remains the source of truth for the write boundary.
            pass

    # Deterministic outcome copy (issue #38). Recipients get the human decision
    # verbatim; no model-generated text is sent to vendors.
    _OUTCOME_EMAILS: dict[CaseLifecycle, tuple[str, str]] = {
        CaseLifecycle.APPROVED: (
            "passed",
            "The campus technology review for {product} has passed. The campus "
            "team will follow up with any remaining onboarding steps. Reply to "
            "this email if you have questions.",
        ),
        CaseLifecycle.DECLINED: (
            "did not pass",
            "The campus technology review for {product} did not pass. Reply to "
            "this email or contact your campus reviewer for details about the "
            "decision.",
        ),
        CaseLifecycle.CHANGES_REQUESTED: (
            "needs changes",
            "The campus technology review for {product} needs additional "
            "information before it can be completed. Open your invitation link "
            "to see the outstanding items, or reply to this email if you are "
            "unsure what is being requested.",
        ),
    }

    def _email_vendor_outcome(
        self, case_id: str, lifecycle: CaseLifecycle, *, product_name: str
    ) -> None:
        """Email the invited vendor contact when a human decision is recorded.

        The recipient is the contact whose invitation carries the submitted
        evidence (the SUBMITTED invite); a newer invitation issued to a
        different contact never diverts the outcome. Only when no submission
        was finalized does the newest non-revoked invitation apply. Delivery is
        recorded idempotently: the same outcome for a case (a re-recorded
        decision or a retried invocation) never sends or persists a duplicate.
        Best-effort: a case without a vendor invitation (no intake ran) sends
        nothing, and a failed delivery never blocks the reviewer decision. The
        truthful delivery mode is persisted on an integration event.
        """
        outcome = self._OUTCOME_EMAILS.get(lifecycle)
        if outcome is None:
            return
        dedupe_key = f"{case_id}:{lifecycle.value}"
        if self._vendor.notification_recorded(
            event_type="email.notification", dedupe_key=dedupe_key
        ):
            return
        invites = [
            invite
            for invite in self._vendor.list_invites(case_id)
            if invite.status is not InviteStatus.REVOKED
        ]
        if not invites:
            return
        submitted = [
            invite for invite in invites if invite.status is InviteStatus.SUBMITTED
        ]
        if submitted:
            invite = max(submitted, key=lambda item: item.submitted_at or item.issued_at)
        else:
            invite = max(invites, key=lambda item: item.issued_at)
        try:
            contact = self._vendor.get_contact(invite.contact_id)
        except VendorBackendError:
            return
        headline, body_template = outcome
        subject = f"VETTED review outcome for {product_name}: {headline}"
        body = body_template.format(product=product_name)
        try:
            delivery = self._email_sender.send(to=contact.email, subject=subject, body=body)
        except Exception:  # noqa: BLE001 - never let notification block the decision
            delivery = {
                "delivery": "failed",
                "simulated": False,
                "channel": "email",
                "to": contact.email,
            }
        self._vendor.record_notification(
            case_id=case_id,
            summary=subject,
            delivery=delivery,
            event_type="email.notification",
            dedupe_key=dedupe_key,
        )

    def _notify(self, case_id: str | None, event_type: str, summary: str) -> None:
        """Send/record a truthful notification (live Slack only when configured)."""
        try:
            delivery = self._notifier.notify(event_type=event_type, summary=summary)
        except Exception:  # noqa: BLE001 - never let notification block the workflow
            delivery = {"delivery": "failed", "simulated": False}
        self._vendor.record_notification(case_id=case_id, summary=summary, delivery=delivery)

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
