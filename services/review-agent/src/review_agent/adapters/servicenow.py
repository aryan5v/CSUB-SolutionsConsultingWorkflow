"""ServiceNow connector interface and the active mock implementation (FR-7).

The prototype writes only through ``MockServiceNowConnector``. A future
restricted Serac MCP adapter must satisfy the same ``ServiceNowConnector``
protocol. Table and field selection is deterministic configuration seeded by an
administrator, never chosen by a model. Every write is simulated and labeled.

Guarantees implemented here:

- A write requires a recorded approved ``HumanDecision`` (no approval -> refusal).
- Optimistic concurrency: a commit fails if the expected record version is stale.
- Idempotency on ``case_id + decision_version``: a repeated commit is suppressed,
  never duplicated.
- A packet attaches at most once per (record, sha256).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..contracts.servicenow import (
    Attachment,
    FieldChange,
    HumanDecision,
    ReviewAction,
    WritePreview,
    WriteResult,
)


class ConnectorError(RuntimeError):
    """Base class for connector-level failures."""


class UnknownRecordError(ConnectorError):
    """The target record does not exist (mock equivalent of a 404)."""


class StaleRecordError(ConnectorError):
    """Expected record version did not match current (mock equivalent of a 409)."""


class UnapprovedWriteError(ConnectorError):
    """No recorded approved HumanDecision for this case/decision version (refuse)."""


@runtime_checkable
class ServiceNowConnector(Protocol):
    def inspect_schema(self, table: str) -> dict: ...

    def get_request(self, external_id: str) -> dict | None: ...

    def preview_update(self, case_id: str, decision_version: int) -> WritePreview: ...

    def update_request(
        self, case_id: str, decision_version: int, expected_version: int
    ) -> WriteResult: ...

    def attach_packet(self, record_id: str, packet_sha256: str) -> Attachment: ...

    def verify_writeback(self, idempotency_key: str) -> WriteResult | None: ...


@dataclass
class _Record:
    record_id: str
    table: str
    fields: dict
    version: int = 1
    attachments: dict[str, str] = field(default_factory=dict)  # sha256 -> attachment_id


# Deterministic, administrator-owned table field schema. A model cannot add to
# or select from this; it is configuration.
_TABLE_SCHEMAS: dict[str, dict] = {
    "sc_req_item": {
        "table": "sc_req_item",
        "writable_fields": [
            "state",
            "assignment_group",
            "work_notes",
            "u_review_outcome",
            "u_risk_route",
        ],
        "read_only_fields": ["number", "sys_id", "opened_by"],
    }
}


class MockServiceNowConnector:
    """In-memory, contract-faithful ServiceNow simulation for the prototype."""

    def __init__(self) -> None:
        self._records: dict[str, _Record] = {}
        self._case_target: dict[str, tuple[str, str]] = {}  # case_id -> (table, record_id)
        self._staged: dict[str, HumanDecision] = {}  # idempotency_key -> approved decision
        self._committed: dict[str, WriteResult] = {}  # idempotency_key -> result
        self._attachment_seq = 0

    # -- administrator/config surface (deterministic, not model-driven) --------

    def seed_record(self, *, record_id: str, table: str, fields: dict) -> None:
        """Create a synthetic ServiceNow record for the demo/tests."""
        self._records[record_id] = _Record(record_id=record_id, table=table, fields=dict(fields))

    def configure_case(self, *, case_id: str, table: str, record_id: str) -> None:
        """Map a case to its target record. Deterministic configuration."""
        if record_id not in self._records:
            raise UnknownRecordError(f"record '{record_id}' not seeded")
        self._case_target[case_id] = (table, record_id)

    def stage_decision(self, decision: HumanDecision) -> None:
        """Record an approved decision so preview/commit can reference it.

        Only ``approve`` decisions become writable; reject/request_info are
        recorded upstream but never staged for a write.
        """
        if decision.action is not ReviewAction.APPROVE:
            raise UnapprovedWriteError(
                f"decision action '{decision.action.value}' is not writable"
            )
        self._staged[decision.idempotency_key] = decision

    # -- ServiceNowConnector protocol -----------------------------------------

    def inspect_schema(self, table: str) -> dict:
        schema = _TABLE_SCHEMAS.get(table)
        if schema is None:
            raise UnknownRecordError(f"unknown table '{table}'")
        return dict(schema)

    def get_request(self, external_id: str) -> dict | None:
        record = self._records.get(external_id)
        if record is None:
            return None
        return {
            "record_id": record.record_id,
            "table": record.table,
            "fields": dict(record.fields),
            "version": record.version,
        }

    def preview_update(self, case_id: str, decision_version: int) -> WritePreview:
        table, record = self._resolve(case_id)
        decision = self._require_staged(case_id, decision_version)
        approved = self._writable_only(table, decision.approved_fields)
        before = dict(record.fields)
        after = {**before, **approved}
        changes = [
            FieldChange(field=key, from_value=before.get(key), to_value=value)
            for key, value in approved.items()
            if before.get(key) != value
        ]
        return WritePreview(
            case_id=case_id,
            decision_version=decision_version,
            table=table,
            record_id=record.record_id,
            before=before,
            after=after,
            field_changes=changes,
        )

    def update_request(
        self, case_id: str, decision_version: int, expected_version: int
    ) -> WriteResult:
        table, record = self._resolve(case_id)
        decision = self._require_staged(case_id, decision_version)
        key = decision.idempotency_key

        # Idempotency: a repeated commit for the same decision is suppressed.
        existing = self._committed.get(key)
        if existing is not None:
            return WriteResult(
                idempotency_key=key,
                record_id=existing.record_id,
                record_version=existing.record_version,
                committed=True,
                duplicate_suppressed=True,
                attachment=existing.attachment,
                connector_response={"note": "idempotent replay", "simulated": True},
            )

        # Optimistic concurrency: refuse a stale write.
        if record.version != expected_version:
            raise StaleRecordError(
                f"expected version {expected_version} but record is at {record.version}"
            )

        approved = self._writable_only(table, decision.approved_fields)
        record.fields.update(approved)
        record.version += 1
        result = WriteResult(
            idempotency_key=key,
            record_id=record.record_id,
            record_version=record.version,
            committed=True,
            duplicate_suppressed=False,
            connector_response={"status": "updated", "simulated": True},
        )
        self._committed[key] = result
        return result

    def attach_packet(self, record_id: str, packet_sha256: str) -> Attachment:
        record = self._records.get(record_id)
        if record is None:
            raise UnknownRecordError(f"record '{record_id}' not found")
        if packet_sha256 in record.attachments:
            return Attachment(
                attachment_id=record.attachments[packet_sha256],
                sha256=packet_sha256,
                already_present=True,
            )
        self._attachment_seq += 1
        attachment_id = f"attach-{self._attachment_seq:04d}"
        record.attachments[packet_sha256] = attachment_id
        return Attachment(attachment_id=attachment_id, sha256=packet_sha256, already_present=False)

    def verify_writeback(self, idempotency_key: str) -> WriteResult | None:
        return self._committed.get(idempotency_key)

    # -- internals -------------------------------------------------------------

    def _resolve(self, case_id: str) -> tuple[str, _Record]:
        target = self._case_target.get(case_id)
        if target is None:
            raise UnknownRecordError(f"no configured record for case '{case_id}'")
        table, record_id = target
        record = self._records.get(record_id)
        if record is None:
            raise UnknownRecordError(f"record '{record_id}' not found")
        return table, record

    def _require_staged(self, case_id: str, decision_version: int) -> HumanDecision:
        key = f"{case_id}:{decision_version}"
        decision = self._staged.get(key)
        if decision is None:
            raise UnapprovedWriteError(f"no approved decision for {key}")
        return decision

    @staticmethod
    def _writable_only(table: str, fields: dict) -> dict:
        schema = _TABLE_SCHEMAS.get(table, {})
        writable = set(schema.get("writable_fields", []))
        # Silently dropping is unsafe; a caller-supplied field outside the
        # deterministic allowlist is a configuration error, not a model choice.
        rejected = set(fields) - writable
        if rejected:
            raise ConnectorError(f"fields not writable on '{table}': {sorted(rejected)}")
        return {k: v for k, v in fields.items() if k in writable}
