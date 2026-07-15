"""AWS Lambda adapter for the deterministic review API.

The handler maps API Gateway HTTP API events to ``LocalReviewApi`` and persists
only JSON-safe, workspace-scoped state.  It never uses pickle, never persists
an opaque invite token, and never logs request bodies, identities, or evidence.
The active ServiceNow connector remains the explicitly simulated local mock.
"""

from __future__ import annotations

import argparse
import base64
import copy
import dataclasses
import datetime
import decimal
import enum
import hashlib
import json
import os
import re
import sys
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs

from .adapters.model import DeterministicModelClient
from .adapters.servicenow import MockServiceNowConnector, _Record
from .adapters.storage import StorageClient
from .api import LocalApiError, LocalReviewApi, _CaseRecord, _default_evidence_storage
from .config import AppConfig
from .audit.log import AuditLog, InMemoryAuditSink
from .contracts.audit import ActorType, AuditEvent
from .contracts.case import CaseIntake, DataClassification, Requester
from .contracts.common import (
    Citation,
    CitationScope,
    Conflict,
    ConflictPosition,
    SourceCoordinates,
)
from .contracts.graph_state import ReviewGraphState, WorkflowStatus
from .contracts.packet import Packet, PacketSection, PacketType
from .contracts.policy import PolicyResult, PolicyTrigger, RiskRoute
from .contracts.servicenow import (
    Attachment,
    FieldChange,
    HumanDecision,
    ReviewAction,
    WritePreview,
    WriteResult,
)
from .contracts.software import ApprovedSoftwareRecord, MatchMethod, SoftwareMatch
from .contracts.vendor import (
    DEFAULT_WORKSPACE_ID,
    ApprovalScope,
    CaseLifecycle,
    CoverageItem,
    EvidenceArtifact,
    EvidenceValidationFinding,
    IntegrationEvent,
    InviteStatus,
    ProfileStatus,
    ReviewCriterion,
    ReviewProfileVersion,
    ReviewRun,
    SoftwareCatalogEntry,
    Submission,
    SubmissionStatus,
    Vendor,
    VendorCase,
    VendorContact,
    VendorInvite,
    VendorProduct,
)
from .ingestion.software_workbook import XlsxWorkbookReader, normalize_workbook
from .lookup.approved_software import ApprovedSoftwareIndex
from .orchestration.graph import ReviewWorkflow
from .orchestration.state import InMemoryCheckpointer
from .policy.conflicts import default_conflict_registry
from .policy.rules import default_ruleset
from .profiles.service import ReviewProfileService
from .vendor.repository import InMemoryVendorRepository
from .vendor.service import VendorBackend

_SCHEMA_VERSION = 1
_MAX_JSON_BYTES = 1_048_576
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_BEARER = re.compile(r"^Bearer ([A-Za-z0-9._~+/=-]{16,512})$")
_FIXED_CLOCK = "2026-07-14T20:00:00+00:00"
_PUBLIC_ROUTES = {
    ("GET", "/health"),
    ("GET", "/vendor/invites/current"),
    ("POST", "/vendor/invites/current/open"),
    ("GET", "/vendor/invites/current/questions"),
    ("POST", "/vendor/invites/current/evidence"),
    ("POST", "/vendor/invites/current/trust-center"),
    ("POST", "/vendor/invites/current/answers"),
    ("POST", "/vendor/invites/current/coverage"),
    ("POST", "/vendor/invites/current/analyze"),
    ("POST", "/vendor/invites/current/finalize"),
    ("GET", "/vendor/invites/current/findings"),
    ("GET", "/intake"),
    ("POST", "/intake"),
    ("POST", "/intake/evidence"),
    ("POST", "/intake/trust-center"),
    ("POST", "/intake/answers"),
    ("POST", "/intake/coverage"),
    ("POST", "/intake/analyze"),
    ("GET", "/intake/questions"),
    ("POST", "/intake/finalize"),
    ("GET", "/intake/findings"),
}


class WorkspaceStore(Protocol):
    def load_snapshot(self, workspace_id: str) -> dict[str, Any] | None: ...

    def save_snapshot(self, workspace_id: str, snapshot: dict[str, Any]) -> None: ...

    def load_catalog(self, workspace_id: str) -> list[dict[str, Any]]: ...

    def replace_catalog(self, workspace_id: str, entries: list[dict[str, Any]]) -> None: ...


class InMemoryWorkspaceStore:
    """JSON-round-tripping persistence fake used by focused Lambda tests."""

    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._catalogs: dict[str, list[dict[str, Any]]] = {}

    def load_snapshot(self, workspace_id: str) -> dict[str, Any] | None:
        value = self._snapshots.get(workspace_id)
        return _json_clone(value) if value is not None else None

    def save_snapshot(self, workspace_id: str, snapshot: dict[str, Any]) -> None:
        self._snapshots[workspace_id] = _json_clone(snapshot)

    def load_catalog(self, workspace_id: str) -> list[dict[str, Any]]:
        return _json_clone(self._catalogs.get(workspace_id, []))

    def replace_catalog(self, workspace_id: str, entries: list[dict[str, Any]]) -> None:
        self._catalogs[workspace_id] = _json_clone(entries)


class FileWorkspaceStore:
    """JSON-file-backed store for boto3-free local seeding and demo verification.

    Uses only the standard library, so an operator can reconcile the 982-row
    workbook and seed the sanitized demo workspace to a local file without AWS
    credentials or the ``aws`` extra. The Lambda runtime still uses
    ``DynamoWorkspaceStore``; this store makes the seed CLI reliably runnable and
    inspectable during development.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser()

    def _read(self) -> dict[str, Any]:
        if not self._path.is_file():
            return {"snapshots": {}, "catalogs": {}}
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError("workspace file is malformed")
        data.setdefault("snapshots", {})
        data.setdefault("catalogs", {})
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(_json_dumps(data), encoding="utf-8")

    def load_snapshot(self, workspace_id: str) -> dict[str, Any] | None:
        value = self._read()["snapshots"].get(workspace_id)
        return _json_clone(value) if value is not None else None

    def save_snapshot(self, workspace_id: str, snapshot: dict[str, Any]) -> None:
        data = self._read()
        data["snapshots"][workspace_id] = _json_clone(snapshot)
        self._write(data)

    def load_catalog(self, workspace_id: str) -> list[dict[str, Any]]:
        return _json_clone(self._read()["catalogs"].get(workspace_id, []))

    def replace_catalog(self, workspace_id: str, entries: list[dict[str, Any]]) -> None:
        data = self._read()
        data["catalogs"][workspace_id] = _json_clone(entries)
        self._write(data)


class DynamoWorkspaceStore:
    """DynamoDB implementation over the existing PlatformStack tables.

    The versioned workspace snapshot is the restore source.  Individual records
    are also projected to their purpose-built tables for scoped inspection and
    future migration.  Catalog rows remain separate to stay below DynamoDB's
    item-size limit and preserve every imported workbook row.
    """

    def __init__(self, tables: dict[str, Any]) -> None:
        self._tables = tables

    @classmethod
    def from_environment(cls) -> DynamoWorkspaceStore:
        required = {
            "cases": "CASES_TABLE",
            "vendor": "VENDOR_TABLE",
            "product": "PRODUCT_TABLE",
            "contact": "CONTACT_TABLE",
            "invite": "INVITE_TABLE",
            "submission": "SUBMISSION_TABLE",
            "review": "REVIEW_TABLE",
            "profile": "PROFILE_TABLE",
            "integration": "INTEGRATION_EVENT_TABLE",
            "audit": "AUDIT_TABLE",
            "idempotency": "IDEMPOTENCY_TABLE",
        }
        missing = [env for env in required.values() if not os.environ.get(env)]
        if missing:
            raise RuntimeError(f"missing DynamoDB table configuration: {', '.join(sorted(missing))}")
        import boto3

        resource = boto3.resource("dynamodb")
        return cls({name: resource.Table(os.environ[env]) for name, env in required.items()})

    @classmethod
    def from_stacks(
        cls,
        *,
        platform_stack: str,
        foundation_stack: str,
        profile: str | None = None,
        region: str | None = None,
        session: Any | None = None,
    ) -> DynamoWorkspaceStore:
        if session is None:
            import boto3

            session = boto3.Session(profile_name=profile, region_name=region)
        cloudformation = session.client("cloudformation")

        def table_names(stack_name: str) -> dict[str, str]:
            values: dict[str, str] = {}
            paginator = cloudformation.get_paginator("list_stack_resources")
            for page in paginator.paginate(StackName=stack_name):
                for summary in page.get("StackResourceSummaries", []):
                    if summary.get("ResourceType") != "AWS::DynamoDB::Table":
                        continue
                    logical = summary.get("LogicalResourceId")
                    physical = summary.get("PhysicalResourceId")
                    if isinstance(logical, str) and isinstance(physical, str):
                        values[logical] = physical
            return values

        platform = table_names(platform_stack)
        foundation = table_names(foundation_stack)
        prefixes = {
            "vendor": "VendorTable",
            "product": "ProductTable",
            "contact": "ContactTable",
            "invite": "InviteTable",
            "submission": "SubmissionTable",
            "review": "ReviewTable",
            "profile": "ProfileTable",
            "integration": "IntegrationEventTable",
            "audit": "AuditTable",
            "idempotency": "IdempotencyTable",
        }

        def require(source: dict[str, str], prefix: str) -> str:
            matches = [value for key, value in source.items() if key.startswith(prefix)]
            if len(matches) != 1:
                raise RuntimeError(f"expected one {prefix} table in the configured stack")
            return matches[0]

        names = {name: require(platform, prefix) for name, prefix in prefixes.items()}
        names["cases"] = require(foundation, "CasesTable")
        resource = session.resource("dynamodb")
        return cls({name: resource.Table(table_name) for name, table_name in names.items()})

    def load_snapshot(self, workspace_id: str) -> dict[str, Any] | None:
        response = self._tables["cases"].get_item(
            Key={"case_id": _physical(workspace_id, "snapshot")},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not isinstance(item, dict) or item.get("workspace_id") != workspace_id:
            return None
        raw = item.get("snapshot")
        if not isinstance(raw, str):
            raise RuntimeError("workspace snapshot is malformed")
        value = json.loads(raw, parse_float=decimal.Decimal)
        if not isinstance(value, dict):
            raise RuntimeError("workspace snapshot is malformed")
        return _decimal_to_native(value)

    def save_snapshot(self, workspace_id: str, snapshot: dict[str, Any]) -> None:
        encoded = _json_dumps(snapshot)
        if len(encoded.encode("utf-8")) >= 350_000:
            raise RuntimeError("workspace snapshot exceeds the safe DynamoDB item limit")
        self._tables["cases"].put_item(
            Item={
                "case_id": _physical(workspace_id, "snapshot"),
                "workspace_id": workspace_id,
                "record_type": "workspace_snapshot",
                "schema_version": _SCHEMA_VERSION,
                "snapshot": encoded,
                "updated_at": _utc_now(),
            }
        )
        self._write_projections(workspace_id, snapshot)

    def load_catalog(self, workspace_id: str) -> list[dict[str, Any]]:
        items = self._scan_workspace(self._tables["product"], workspace_id, "catalog")
        values = [json.loads(item["payload"]) for item in items if isinstance(item.get("payload"), str)]
        return sorted(values, key=lambda value: (value.get("source_row", 0), value.get("record_id", "")))

    def replace_catalog(self, workspace_id: str, entries: list[dict[str, Any]]) -> None:
        table = self._tables["product"]
        for item in self._scan_workspace(table, workspace_id, "catalog"):
            table.delete_item(Key={"product_id": item["product_id"], "version": item["version"]})
        with table.batch_writer() as batch:
            for entry in entries:
                record_id = _required_string(entry, "record_id")
                batch.put_item(
                    Item={
                        "product_id": _physical(workspace_id, f"catalog#{record_id}"),
                        "version": 0,
                        "workspace_id": workspace_id,
                        "record_type": "catalog",
                        "payload": _json_dumps(entry),
                    }
                )

    def _write_projections(self, workspace_id: str, snapshot: dict[str, Any]) -> None:
        repository = snapshot.get("repository", {})
        records = repository.get("records", {}) if isinstance(repository, dict) else {}
        mapping = {
            "vendor": "vendor",
            "product": "product",
            "contact": "contact",
            "invite": "invite",
            "submission": "submission",
            "evidence": "submission",
            "coverage": "submission",
            "profile": "profile",
            "run": "review",
            "event": "integration",
            "case": "cases",
        }
        for kind, table_name in mapping.items():
            table = self._tables[table_name]
            for item in self._scan_workspace(table, workspace_id, kind):
                self._delete_projection(table_name, item)
            values = records.get(kind, []) if isinstance(records, dict) else []
            for value in values:
                if isinstance(value, dict):
                    self._put_projection(table_name, workspace_id, kind, value)
        cases = snapshot.get("cases", {})
        for item in self._scan_workspace(self._tables["cases"], workspace_id, "review_case"):
            self._delete_projection("cases", item)
        for item in self._scan_workspace(self._tables["audit"], workspace_id, "audit"):
            self._delete_projection("audit", item)
        for item in self._scan_workspace(
            self._tables["idempotency"], workspace_id, "simulated_servicenow_commit"
        ):
            self._delete_projection("idempotency", item)
        if isinstance(cases, dict):
            for case_id, value in cases.items():
                if not isinstance(value, dict):
                    continue
                self._tables["cases"].put_item(
                    Item={
                        "case_id": _physical(workspace_id, f"review#{case_id}"),
                        "workspace_id": workspace_id,
                        "record_type": "review_case",
                        "payload": _json_dumps(value),
                    }
                )
                for sequence, event in enumerate(value.get("audit_events", []), start=1):
                    self._tables["audit"].put_item(
                        Item={
                            "case_id": _physical(workspace_id, case_id),
                            "sequence": sequence,
                            "workspace_id": workspace_id,
                            "record_type": "audit",
                            "payload": _json_dumps(event),
                        }
                    )
        connector = snapshot.get("connector", {})
        committed = connector.get("committed", {}) if isinstance(connector, dict) else {}
        if isinstance(committed, dict):
            for key, value in committed.items():
                self._tables["idempotency"].put_item(
                    Item={
                        "idempotency_key": _physical(workspace_id, key),
                        "workspace_id": workspace_id,
                        "record_type": "simulated_servicenow_commit",
                        "payload": _json_dumps(value),
                        "ttl": int(datetime.datetime.now(datetime.timezone.utc).timestamp()) + 7_776_000,
                    }
                )

    def _put_projection(
        self, table_name: str, workspace_id: str, kind: str, value: dict[str, Any]
    ) -> None:
        record_id = _record_id(kind, value)
        item = {
            "workspace_id": workspace_id,
            "record_type": kind,
            "payload": _json_dumps(value),
        }
        if table_name == "vendor":
            item["vendor_id"] = _physical(workspace_id, f"{kind}#{record_id}")
        elif table_name == "product":
            item["product_id"] = _physical(workspace_id, f"{kind}#{record_id}")
            item["version"] = int(value.get("version", 1))
        elif table_name == "contact":
            item["contact_id"] = _physical(workspace_id, f"{kind}#{record_id}")
        elif table_name == "invite":
            item["token_hash"] = _required_string(value, "token_hash")
            item["expires_at"] = int(
                datetime.datetime.fromisoformat(_required_string(value, "expires_at")).timestamp()
            )
        elif table_name == "submission":
            item["submission_id"] = _physical(workspace_id, f"{kind}#{record_id}")
            item["case_id"] = _physical(workspace_id, str(value.get("case_id") or record_id))
        elif table_name == "profile":
            item["user_id"] = _physical(workspace_id, str(value.get("profile_key", "profile")))
            item["version"] = int(value.get("version", 1))
        elif table_name == "review":
            item["case_id"] = _physical(workspace_id, _required_string(value, "case_id"))
            item["decision_version"] = int(value.get("run_version", 0))
        elif table_name == "integration":
            item["event_id"] = _physical(workspace_id, record_id)
            item["occurred_at"] = _epoch_micros(_required_string(value, "occurred_at"))
            item["ttl"] = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) + 7_776_000
        elif table_name == "cases":
            item["case_id"] = _physical(workspace_id, f"vendor#{record_id}")
        self._tables[table_name].put_item(Item=item)

    def _delete_projection(self, table_name: str, item: dict[str, Any]) -> None:
        key_fields = {
            "vendor": ("vendor_id",),
            "product": ("product_id", "version"),
            "contact": ("contact_id",),
            "invite": ("token_hash",),
            "submission": ("submission_id", "case_id"),
            "review": ("case_id", "decision_version"),
            "profile": ("user_id", "version"),
            "integration": ("event_id", "occurred_at"),
            "audit": ("case_id", "sequence"),
            "idempotency": ("idempotency_key",),
            "cases": ("case_id",),
        }[table_name]
        if not all(field in item for field in key_fields):
            raise RuntimeError(f"persisted {table_name} projection has an invalid key")
        self._tables[table_name].delete_item(
            Key={field: item[field] for field in key_fields}
        )

    @staticmethod
    def _scan_workspace(table: Any, workspace_id: str, record_type: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        start_key = None
        while True:
            kwargs = {"ExclusiveStartKey": start_key} if start_key else {}
            response = table.scan(**kwargs)
            page = response.get("Items", [])
            if not isinstance(page, list):
                raise RuntimeError("DynamoDB scan returned malformed Items")
            items.extend(
                item
                for item in page
                if isinstance(item, dict)
                and item.get("workspace_id") == workspace_id
                and item.get("record_type") == record_type
            )
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                return items


_VENDOR_DECODERS: dict[str, Callable[[dict[str, Any]], object]] = {
    "vendor": lambda value: Vendor(**value),
    "product": lambda value: VendorProduct(**value),
    "contact": lambda value: VendorContact(**value),
    "case": lambda value: VendorCase(**{**value, "lifecycle": CaseLifecycle(value["lifecycle"])}),
    "invite": lambda value: VendorInvite(**{**value, "status": InviteStatus(value["status"])}),
    "evidence": lambda value: EvidenceArtifact(**value),
    "coverage": lambda value: CoverageItem(
        **{**value, "evidence_artifact_ids": tuple(value["evidence_artifact_ids"])}
    ),
    "submission": lambda value: Submission(
        **{
            **value,
            "status": SubmissionStatus(value["status"]),
            "evidence_artifact_ids": tuple(value["evidence_artifact_ids"]),
            "coverage_ids": tuple(value["coverage_ids"]),
        }
    ),
    "profile": lambda value: ReviewProfileVersion(
        **{
            **value,
            "criteria": tuple(_criterion(item) for item in value["criteria"]),
            "status": ProfileStatus(value["status"]),
        }
    ),
    "run": lambda value: ReviewRun(
        **{
            **value,
            "approval_scope": ApprovalScope(
                **{
                    **value["approval_scope"],
                    "profile_version_ids": tuple(value["approval_scope"]["profile_version_ids"]),
                }
            ),
            "unresolved_requirement_ids": tuple(value["unresolved_requirement_ids"]),
        }
    ),
    "event": lambda value: IntegrationEvent(**value),
    "finding": lambda value: EvidenceValidationFinding(**value),
}


def seed_workspace(
    store: WorkspaceStore,
    *,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
    catalog_entries: Iterable[SoftwareCatalogEntry] | None = None,
) -> dict[str, Any]:
    """Replace the fixed sanitized golden-demo workspace deterministically."""
    if workspace_id != DEFAULT_WORKSPACE_ID:
        raise ValueError(f"only the {DEFAULT_WORKSPACE_ID!r} demo workspace can be seeded")
    api = LocalReviewApi(seed_demo=True)
    entries = list(catalog_entries or _catalog_from_api(api))
    if not entries:
        raise ValueError("catalog seed must contain at least one record")
    repository = api._vendor_repository
    repository._records[(workspace_id, "catalog")].clear()
    for entry in entries:
        if entry.workspace_id != workspace_id:
            raise ValueError("catalog workspace does not match seed workspace")
        repository.put("catalog", entry.record_id, entry, workspace_id=workspace_id)
    store.replace_catalog(workspace_id, [entry.to_dict() for entry in entries])
    snapshot = snapshot_api(api, workspace_id=workspace_id)
    store.save_snapshot(workspace_id, snapshot)
    return {
        "workspace_id": workspace_id,
        "seeded_cases": len(api._cases),
        "catalog_records": len(entries),
        "catalog_membership_is_approval": False,
        "simulated_servicenow": True,
    }


def snapshot_api(api: LocalReviewApi, *, workspace_id: str) -> dict[str, Any]:
    records: dict[str, list[dict[str, Any]]] = {}
    repository = api._vendor_repository
    for (record_workspace, kind), values in repository._records.items():
        if record_workspace != workspace_id or kind == "catalog":
            continue
        records[kind] = [_json_safe(values[key]) for key in sorted(values)]
    active_profiles = {
        key: value
        for (record_workspace, key), value in repository._active_profiles.items()
        if record_workspace == workspace_id
    }
    current_runs = {
        key: value
        for (record_workspace, key), value in repository._current_runs.items()
        if record_workspace == workspace_id
    }
    cases = {
        case_id: {
            "state": record.state.to_dict(),
            "documents": _json_safe(record.documents),
            "audit_events": [event.to_dict() for event in record.audit_sink.events],
            "workflow_sequence": record.workflow._seq,
        }
        for case_id, record in sorted(api._cases.items())
    }
    connector = api._connector
    connector_records = {
        key: {
            "record_id": value.record_id,
            "table": value.table,
            "fields": _json_safe(value.fields),
            "version": value.version,
            "attachments": dict(value.attachments),
        }
        for key, value in sorted(connector._records.items())
    }
    return {
        "schema_version": _SCHEMA_VERSION,
        "workspace_id": workspace_id,
        "case_sequence": api._case_sequence,
        "repository": {
            "records": records,
            "active_profiles": active_profiles,
            "current_runs": current_runs,
        },
        "cases": cases,
        "connector": {
            "records": connector_records,
            "case_target": {key: list(value) for key, value in connector._case_target.items()},
            "staged": {key: value.to_dict() for key, value in connector._staged.items()},
            "committed": {key: value.to_dict() for key, value in connector._committed.items()},
            "attachment_sequence": connector._attachment_seq,
        },
    }


def restore_api(
    snapshot: dict[str, Any],
    catalog_values: list[dict[str, Any]],
    *,
    workspace_id: str,
    evidence_storage: StorageClient | None = None,
) -> LocalReviewApi:
    if snapshot.get("schema_version") != _SCHEMA_VERSION:
        raise RuntimeError("unsupported workspace snapshot version")
    if snapshot.get("workspace_id") != workspace_id:
        raise RuntimeError("workspace snapshot isolation check failed")
    api = LocalReviewApi(seed_demo=False, evidence_storage=evidence_storage)
    repository = InMemoryVendorRepository()
    repository_data = snapshot.get("repository")
    if not isinstance(repository_data, dict):
        raise RuntimeError("workspace repository snapshot is malformed")
    records = repository_data.get("records", {})
    if not isinstance(records, dict):
        raise RuntimeError("workspace repository snapshot is malformed")
    for kind, values in records.items():
        decoder = _VENDOR_DECODERS.get(kind)
        if decoder is None or not isinstance(values, list):
            raise RuntimeError(f"unsupported persisted vendor record kind: {kind}")
        for value in values:
            if not isinstance(value, dict):
                raise RuntimeError("persisted vendor record is malformed")
            record = decoder(value)
            repository.put(kind, _record_id(kind, value), record, workspace_id=workspace_id)
    catalog = [_catalog_entry(value, workspace_id=workspace_id) for value in catalog_values]
    for entry in catalog:
        repository.put("catalog", entry.record_id, entry, workspace_id=workspace_id)
    for key, value in _string_map(repository_data.get("active_profiles", {})).items():
        repository.set_active_profile(key, value, workspace_id=workspace_id)
    for key, value in _string_map(repository_data.get("current_runs", {})).items():
        repository.set_current_run(key, value, workspace_id=workspace_id)
    api._vendor_repository = repository
    api._profiles = ReviewProfileService(repository)
    # The restored backend keeps the evidence storage/extractor seams so
    # deployed content validation (issue #36) can read stored evidence bytes.
    api._vendor = VendorBackend(
        repository,
        api._profiles,
        evidence_storage=api._evidence_storage,
        extractor=api._evidence_extractor,
    )
    api._software_index = ApprovedSoftwareIndex([_approved_record(entry) for entry in catalog])
    api._connector = _restore_connector(snapshot.get("connector"))
    api._cases = {}
    api._case_sequence = int(snapshot.get("case_sequence", 0))
    specialist_profiles = {
        profile.profile_key: profile.profile_version_id
        for profile in api._profiles.active_profiles()
        if profile.profile_key in {"security", "accessibility"}
    }
    case_values = snapshot.get("cases", {})
    if not isinstance(case_values, dict):
        raise RuntimeError("workspace case snapshot is malformed")
    for case_id, value in case_values.items():
        if not isinstance(case_id, str) or not isinstance(value, dict):
            raise RuntimeError("workspace case snapshot is malformed")
        state = _review_state(_required_dict(value, "state"))
        sink = InMemoryAuditSink()
        events = value.get("audit_events", [])
        if not isinstance(events, list):
            raise RuntimeError("workspace audit snapshot is malformed")
        sink.events = [_audit_event(event) for event in events]
        audit = AuditLog(sink=sink)
        workflow = _workflow(api._software_index, audit, specialist_profiles, api._model_client)
        workflow._seq = int(value.get("workflow_sequence", len(events)))
        documents = value.get("documents", [])
        if not isinstance(documents, list):
            raise RuntimeError("workspace documents snapshot is malformed")
        api._cases[case_id] = _CaseRecord(
            state=state,
            workflow=workflow,
            audit=audit,
            audit_sink=sink,
            documents=copy.deepcopy(documents),
        )
    return api


def create_handler(
    store: WorkspaceStore,
    *,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
    allowed_origins: Iterable[str] = (),
    evidence_storage: StorageClient | None = None,
) -> Callable[[dict[str, Any], Any], dict[str, Any]]:
    origins = frozenset(origin for origin in allowed_origins if origin)
    # Built once per handler so evidence bytes survive across requests within
    # a warm container; on AWS the S3-backed store is durable across restores.
    evidence_store = evidence_storage or _default_evidence_storage(AppConfig.from_env())

    def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
        correlation_id = _correlation_id(event, context)
        try:
            method, path = _method_path(event)
            origin = _header(event, "origin")
            if method == "OPTIONS":
                return _response(204, None, correlation_id, origin=origin, allowed_origins=origins)
            if (method, path) == ("GET", "/health"):
                return _response(
                    200,
                    {"status": "ok", "mode": "aws-lambda", "live": True},
                    correlation_id,
                    origin=origin,
                    allowed_origins=origins,
                )
            body = _body(event, method)
            is_public = (method, path) in _PUBLIC_ROUTES
            reviewer_id = None if is_public else _reviewer_identity(event, workspace_id)
            token = None
            if path.startswith("/intake") or path.startswith("/vendor/invites/current"):
                _reject_token_query(event)
                token = _bearer_token(event)
            snapshot = store.load_snapshot(workspace_id)
            if snapshot is None:
                raise LocalApiError(503, "workspace_not_seeded", "demo workspace is not seeded")
            api = restore_api(
                snapshot,
                store.load_catalog(workspace_id),
                workspace_id=workspace_id,
                evidence_storage=evidence_store,
            )
            result, status, mutated = _dispatch(
                api,
                method,
                path,
                body,
                event,
                token=token,
                reviewer_id=reviewer_id,
            )
            if mutated:
                store.save_snapshot(workspace_id, snapshot_api(api, workspace_id=workspace_id))
            _log(correlation_id, "request.completed", status)
            return _response(
                status,
                result,
                correlation_id,
                origin=origin,
                allowed_origins=origins,
            )
        except LocalApiError as error:
            _log(correlation_id, "request.rejected", error.status)
            return _response(
                error.status,
                {"error": {"code": error.code, "message": str(error)}},
                correlation_id,
                origin=_header(event, "origin"),
                allowed_origins=origins,
            )
        except Exception:
            _log(correlation_id, "request.failed", 500)
            return _response(
                500,
                {"error": {"code": "internal_error", "message": "request failed"}},
                correlation_id,
                origin=_header(event, "origin"),
                allowed_origins=origins,
            )

    return handler


def _dispatch(
    api: LocalReviewApi,
    method: str,
    path: str,
    body: dict[str, Any],
    event: dict[str, Any],
    *,
    token: str | None,
    reviewer_id: str | None,
) -> tuple[dict[str, Any], int, bool]:
    if method == "GET" and path == "/review-queue":
        return api.list_review_queue(), 200, False
    if method == "POST" and path == "/cases":
        return api.create_case(body), 201, True
    if method == "GET" and path == "/integration-events":
        return api.integration_events(), 200, False
    if method == "GET" and path == "/catalog":
        query = _query(event)
        return (
            api.list_catalog(
                query.get("q", [None])[0],
                query.get("limit", [None])[0],
                query.get("offset", [None])[0],
            ),
            200,
            False,
        )
    if method == "GET" and path == "/catalog/search":
        query = _query(event)
        return api.search_catalog(query.get("q", [""])[0], query.get("vendor", [None])[0]), 200, False
    match = re.fullmatch(r"/catalog/matches/([^/]+)/confirm", path)
    if method == "POST" and match:
        payload = dict(body)
        payload["reviewer_id"] = reviewer_id
        return api.confirm_catalog_match(_safe_id(match.group(1)), payload), 200, True
    if path == "/review-profiles":
        if method == "GET":
            return api.list_profiles(), 200, False
        if method == "POST":
            return api.create_profile_draft(body), 201, True
    resource = re.fullmatch(r"/(vendors|vendor-products|vendor-contacts)(?:/([^/]+))?", path)
    if resource:
        return _dispatch_resource(api, method, resource.group(1), resource.group(2), body, event)
    invite = re.fullmatch(r"/invites/([^/]+)/(revoke|resend)", path)
    if method == "POST" and invite:
        invite_id, action = invite.groups()
        value = api.revoke_vendor_invite(_safe_id(invite_id)) if action == "revoke" else api.resend_vendor_invite(_safe_id(invite_id))
        return value, 200, True
    profile = re.fullmatch(r"/review-profiles/([^/]+)(?:/(fixture-test|activate|rollback))?", path)
    if profile:
        profile_id, action = profile.groups()
        profile_id = _safe_id(profile_id)
        if method == "PATCH" and action is None:
            return api.update_profile_draft(profile_id, body), 200, True
        if method == "POST" and action == "fixture-test":
            return api.fixture_test_profile(profile_id, body), 200, True
        if method == "POST" and action == "activate":
            return api.activate_profile(profile_id), 200, True
        if method == "POST" and action == "rollback":
            return api.rollback_profile(profile_id), 200, True
    imported = re.fullmatch(r"/servicenow/imports/([^/]+)/(preview|create)", path)
    if imported:
        external_id, action = imported.groups()
        if method == "GET" and action == "preview":
            return api.preview_servicenow_import(_safe_id(external_id)), 200, False
        if method == "POST" and action == "create":
            return api.create_from_servicenow_import(_safe_id(external_id)), 201, True
    if path.startswith("/intake") or path.startswith("/vendor/invites/current"):
        return _dispatch_intake(api, method, path, body, token)
    case = re.fullmatch(r"/cases/([^/]+)(?:/(.*))?", path)
    if case:
        return _dispatch_case(api, method, _safe_id(case.group(1)), case.group(2) or "", body, reviewer_id)
    raise LocalApiError(404, "route_not_found", "route not found")


def _dispatch_resource(
    api: LocalReviewApi,
    method: str,
    kind: str,
    resource_id: str | None,
    body: dict[str, Any],
    event: dict[str, Any],
) -> tuple[dict[str, Any], int, bool]:
    resource_id = _safe_id(resource_id) if resource_id else None
    vendor_id = _query(event).get("vendor_id", [None])[0]
    if kind == "vendors":
        operations = {
            ("GET", False): (api.list_vendors, 200, False),
            ("POST", False): (lambda: api.create_vendor_record(body), 201, True),
            ("GET", True): (lambda: api.get_vendor_record(resource_id or ""), 200, False),
            ("PATCH", True): (lambda: api.update_vendor_record(resource_id or "", body), 200, True),
            ("DELETE", True): (lambda: api.delete_vendor_record(resource_id or ""), 200, True),
        }
    elif kind == "vendor-products":
        operations = {
            ("GET", False): (lambda: api.list_vendor_products(vendor_id), 200, False),
            ("POST", False): (lambda: api.create_vendor_product(body), 201, True),
            ("GET", True): (lambda: api.get_vendor_product(resource_id or ""), 200, False),
            ("PATCH", True): (lambda: api.update_vendor_product(resource_id or "", body), 200, True),
            ("DELETE", True): (lambda: api.delete_vendor_product(resource_id or ""), 200, True),
        }
    else:
        operations = {
            ("GET", False): (lambda: api.list_vendor_contacts(vendor_id), 200, False),
            ("POST", False): (lambda: api.create_vendor_contact(body), 201, True),
            ("GET", True): (lambda: api.get_vendor_contact(resource_id or ""), 200, False),
            ("PATCH", True): (lambda: api.update_vendor_contact(resource_id or "", body), 200, True),
            ("DELETE", True): (lambda: api.delete_vendor_contact(resource_id or ""), 200, True),
        }
    operation = operations.get((method, resource_id is not None))
    if operation is None:
        raise LocalApiError(404, "route_not_found", "route not found")
    callback, status, mutated = operation
    return callback(), status, mutated


def _dispatch_case(
    api: LocalReviewApi,
    method: str,
    case_id: str,
    suffix: str,
    body: dict[str, Any],
    reviewer_id: str | None,
) -> tuple[dict[str, Any], int, bool]:
    if method == "GET" and suffix == "":
        return api.get_state(case_id), 200, False
    if method == "POST" and suffix == "documents":
        return api.add_document(case_id, body), 201, True
    if method == "POST" and suffix == "analyze":
        confirmed = body.get("confirmed_match_id")
        if confirmed is not None and not isinstance(confirmed, str):
            raise LocalApiError(400, "invalid_match", "confirmed_match_id must be a string")
        return api.analyze_case(case_id, confirmed_match_id=confirmed, reviewer_id=reviewer_id), 202, True
    if method == "GET" and suffix == "stream":
        return {"event": "state", "data": api.get_state(case_id)}, 200, False
    if method == "POST" and suffix == "review":
        payload = dict(body)
        payload["case_id"] = case_id
        payload["reviewer_id"] = reviewer_id
        return api.review_case(case_id, payload), 200, True
    if method == "POST" and suffix == "servicenow/preview":
        return api.preview_servicenow(case_id), 200, True
    if method == "POST" and suffix == "servicenow/commit":
        return api.commit_servicenow(case_id, body), 200, True
    if method == "GET" and suffix == "evidence-findings":
        return api.case_evidence_findings(case_id), 200, False
    if method == "GET" and suffix == "packet":
        return api.get_packet(case_id), 200, False
    if method == "GET" and suffix == "packet/pdf":
        return api.get_packet_pdf(case_id), 200, False
    if method == "POST" and suffix == "invites":
        return api.issue_vendor_invite(case_id, body), 201, True
    if method == "GET" and suffix == "invites":
        return api.list_case_invites(case_id), 200, False
    if method == "POST" and suffix == "review-runs":
        return api.create_review_run(case_id, body), 201, True
    if method == "GET" and suffix == "review-runs":
        return api.list_review_runs(case_id), 200, False
    raise LocalApiError(404, "route_not_found", "route not found")


def _dispatch_intake(
    api: LocalReviewApi,
    method: str,
    path: str,
    body: dict[str, Any],
    token: str | None,
) -> tuple[dict[str, Any], int, bool]:
    if token is None:
        raise LocalApiError(401, "invalid_invite", "valid bearer invitation is required")
    aliases = {
        "/vendor/invites/current": "/intake",
        "/vendor/invites/current/open": "/intake",
        "/vendor/invites/current/questions": "/intake/questions",
        "/vendor/invites/current/evidence": "/intake/evidence",
        "/vendor/invites/current/trust-center": "/intake/trust-center",
        "/vendor/invites/current/answers": "/intake/answers",
        "/vendor/invites/current/coverage": "/intake/coverage",
        "/vendor/invites/current/analyze": "/intake/analyze",
        "/vendor/invites/current/finalize": "/intake/finalize",
        "/vendor/invites/current/findings": "/intake/findings",
    }
    path = aliases.get(path, path)
    if method == "GET" and path == "/intake":
        return api.resolve_vendor_invite(token), 200, False
    if method == "POST" and path == "/intake":
        return api.resolve_vendor_invite(token, mark_open=True), 200, True
    operations: dict[tuple[str, str], Callable[[], dict[str, Any]]] = {
        ("POST", "/intake/evidence"): lambda: api.vendor_add_evidence(token, body),
        ("POST", "/intake/trust-center"): lambda: api.vendor_set_trust_center(token, body),
        ("POST", "/intake/answers"): lambda: api.vendor_save_answers(token, body),
        ("POST", "/intake/coverage"): lambda: api.vendor_add_coverage(token, body),
        ("POST", "/intake/analyze"): lambda: api.vendor_run_intake_analysis(token),
        ("GET", "/intake/questions"): lambda: api.vendor_questions(token),
        ("POST", "/intake/finalize"): lambda: api.vendor_finalize(token),
        ("GET", "/intake/findings"): lambda: api.vendor_evidence_findings(token),
    }
    operation = operations.get((method, path))
    if operation is None:
        raise LocalApiError(404, "route_not_found", "route not found")
    return operation(), 200, method != "GET"


def _reviewer_identity(event: dict[str, Any], workspace_id: str) -> str:
    request_context = event.get("requestContext")
    authorizer = request_context.get("authorizer") if isinstance(request_context, dict) else None
    jwt = authorizer.get("jwt") if isinstance(authorizer, dict) else None
    claims = jwt.get("claims") if isinstance(jwt, dict) else None
    if not isinstance(claims, dict):
        raise LocalApiError(401, "reviewer_auth_required", "reviewer authentication is required")
    subject = claims.get("email") or claims.get("sub")
    claim_workspace = claims.get("custom:workspace_id") or claims.get("workspace_id") or workspace_id
    if claim_workspace != workspace_id:
        raise LocalApiError(403, "workspace_forbidden", "reviewer workspace is not allowed")
    if not isinstance(subject, str) or not subject.strip():
        raise LocalApiError(401, "reviewer_auth_required", "reviewer identity is required")
    return subject.strip()


def _bearer_token(event: dict[str, Any]) -> str:
    authorization = _header(event, "authorization")
    match = _BEARER.fullmatch(authorization or "")
    if match is None:
        raise LocalApiError(401, "invalid_invite", "valid bearer invitation is required")
    return match.group(1)


def _reject_token_query(event: dict[str, Any]) -> None:
    query = _query(event)
    if {"token", "token_hash", "invite", "invite_token"}.intersection(query):
        raise LocalApiError(400, "token_in_url_forbidden", "invitation tokens are not accepted in URLs")


def _body(event: dict[str, Any], method: str) -> dict[str, Any]:
    raw = event.get("body")
    if raw in (None, "") or method in {"GET", "OPTIONS"}:
        return {}
    if not isinstance(raw, str):
        raise LocalApiError(400, "invalid_json", "request body must be JSON")
    try:
        encoded_size = len(base64.b64decode(raw, validate=True)) if event.get("isBase64Encoded") else len(raw.encode("utf-8"))
    except (ValueError, UnicodeError) as error:
        raise LocalApiError(400, "invalid_encoding", "request body encoding is invalid") from error
    if encoded_size > _MAX_JSON_BYTES:
        raise LocalApiError(413, "payload_too_large", "request body exceeds the metadata limit")
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw, validate=True).decode("utf-8")

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        value = json.loads(raw, parse_constant=reject_constant)
    except (json.JSONDecodeError, UnicodeError, ValueError) as error:
        raise LocalApiError(400, "invalid_json", "request body must be strict JSON") from error
    if not isinstance(value, dict):
        raise LocalApiError(400, "invalid_body", "request body must be a JSON object")
    return value


def _method_path(event: dict[str, Any]) -> tuple[str, str]:
    request_context = event.get("requestContext")
    http = request_context.get("http") if isinstance(request_context, dict) else None
    method = http.get("method") if isinstance(http, dict) else None
    if not isinstance(method, str):
        route_key = event.get("routeKey", "")
        method = route_key.split(" ", 1)[0] if isinstance(route_key, str) else ""
    path = event.get("rawPath")
    if not isinstance(path, str):
        path = http.get("path") if isinstance(http, dict) else None
    if not isinstance(path, str) or not path.startswith("/"):
        raise LocalApiError(400, "invalid_route", "request route is invalid")
    if path == "/api" or path.startswith("/api/"):
        path = path[4:] or "/"
    return method.upper(), path.rstrip("/") or "/"


def _response(
    status: int,
    payload: dict[str, Any] | None,
    correlation_id: str,
    *,
    origin: str | None,
    allowed_origins: frozenset[str],
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Correlation-Id": correlation_id,
        "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Correlation-Id",
        "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
    }
    if origin and origin in allowed_origins:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
    return {
        "statusCode": status,
        "headers": headers,
        "isBase64Encoded": False,
        "body": "" if payload is None else _json_dumps(payload),
    }


def _query(event: dict[str, Any]) -> dict[str, list[str]]:
    raw = event.get("rawQueryString", "")
    if not isinstance(raw, str):
        return {}
    return parse_qs(raw, keep_blank_values=False)


def _header(event: dict[str, Any], name: str) -> str | None:
    headers = event.get("headers")
    if not isinstance(headers, dict):
        return None
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == name.lower() and isinstance(value, str):
            return value
    return None


def _correlation_id(event: dict[str, Any], context: Any) -> str:
    supplied = _header(event, "x-correlation-id")
    if supplied and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied):
        return supplied
    request_id = getattr(context, "aws_request_id", None)
    return request_id if isinstance(request_id, str) and request_id else str(uuid.uuid4())


def _log(correlation_id: str, event_type: str, status: int) -> None:
    print(_json_dumps({"correlation_id": correlation_id, "event_type": event_type, "status": status}))


def _workflow(
    index: ApprovedSoftwareIndex,
    audit: AuditLog,
    specialist_profiles: dict[str, str] | None = None,
    model: Any | None = None,
) -> ReviewWorkflow:
    return ReviewWorkflow(
        model=model or DeterministicModelClient(),
        software_index=index,
        ruleset=default_ruleset(),
        registry=default_conflict_registry(),
        audit=audit,
        checkpointer=InMemoryCheckpointer(),
        clock=lambda: _FIXED_CLOCK,
        specialist_profiles=specialist_profiles or {},
    )


def _review_state(value: dict[str, Any]) -> ReviewGraphState:
    policy = value.get("policy_result")
    packet = value.get("draft_packet")
    decision = value.get("human_decision")
    preview = value.get("write_preview")
    result = value.get("write_result")
    return ReviewGraphState(
        case_id=_required_string(value, "case_id"),
        case_input=_case_intake(_required_dict(value, "case_input")),
        status=WorkflowStatus(_required_string(value, "status")),
        workflow_version=_required_string(value, "workflow_version"),
        document_ids=_string_list(value.get("document_ids", [])),
        software_candidates=[_software_match(item) for item in _dict_list(value.get("software_candidates", []))],
        confirmed_match_id=_optional_string(value.get("confirmed_match_id")),
        policy_result=_policy_result(policy) if isinstance(policy, dict) else None,
        specialist_results=copy.deepcopy(_required_dict(value, "specialist_results")),
        evidence_gaps=_string_list(value.get("evidence_gaps", [])),
        citations=[_citation(item) for item in _dict_list(value.get("citations", []))],
        conflicts=[_conflict(item) for item in _dict_list(value.get("conflicts", []))],
        draft_packet=_packet(packet) if isinstance(packet, dict) else None,
        human_edits=copy.deepcopy(_dict_list(value.get("human_edits", []))),
        human_decision=_human_decision(decision) if isinstance(decision, dict) else None,
        connector_target=copy.deepcopy(value.get("connector_target")) if isinstance(value.get("connector_target"), dict) else None,
        write_preview=_write_preview(preview) if isinstance(preview, dict) else None,
        write_result=_write_result(result) if isinstance(result, dict) else None,
        idempotency_key=_optional_string(value.get("idempotency_key")),
        repair_passes_used=int(value.get("repair_passes_used", 0)),
    )


def _case_intake(value: dict[str, Any]) -> CaseIntake:
    requester = _required_dict(value, "requester")
    return CaseIntake(
        product_name=_required_string(value, "product_name"),
        vendor_name=_required_string(value, "vendor_name"),
        requester=Requester(
            name=_required_string(requester, "name"),
            email=_required_string(requester, "email"),
            department=_optional_string(requester.get("department")),
        ),
        use_case=_required_string(value, "use_case"),
        expected_users=int(value["expected_users"]),
        platform=_string_list(value["platform"]),
        data_classification=DataClassification(_required_string(value, "data_classification")),
        estimated_cost_usd=float(value["estimated_cost_usd"]),
        integrations=_string_list(value.get("integrations", [])),
        uses_sso=value.get("uses_sso") is True,
        uses_ai=value.get("uses_ai") is True,
        accessibility_context=_optional_string(value.get("accessibility_context")),
        official_domain=_optional_string(value.get("official_domain")),
        classroom_or_public_use=value.get("classroom_or_public_use") is True,
    )


def _source(value: dict[str, Any]) -> SourceCoordinates:
    allowed = {field.name for field in dataclasses.fields(SourceCoordinates)}
    return SourceCoordinates(**{key: item for key, item in value.items() if key in allowed})


def _citation(value: dict[str, Any]) -> Citation:
    return Citation(
        claim=_required_string(value, "claim"),
        source=_source(_required_dict(value, "source")),
        scope=CitationScope(_required_string(value, "scope")),
        verified=value.get("verified") is True,
    )


def _conflict(value: dict[str, Any]) -> Conflict:
    return Conflict(
        conflict_id=_required_string(value, "conflict_id"),
        topic=_required_string(value, "topic"),
        positions=[
            ConflictPosition(
                value=_required_string(item, "value"),
                source=_source(_required_dict(item, "source")),
                precedence=int(item["precedence"]),
            )
            for item in _dict_list(value.get("positions", []))
        ],
        resolution=_optional_string(value.get("resolution")),
    )


def _software_match(value: dict[str, Any]) -> SoftwareMatch:
    return SoftwareMatch(
        record_id=_required_string(value, "record_id"),
        canonical_name=_optional_string(value.get("canonical_name")),
        match_method=MatchMethod(_required_string(value, "match_method")),
        score=float(value["score"]),
        source_row_ref=_source(_required_dict(value, "source_row_ref")),
    )


def _policy_result(value: dict[str, Any]) -> PolicyResult:
    return PolicyResult(
        policy_version=_required_string(value, "policy_version"),
        risk_route=RiskRoute(_required_string(value, "risk_route")),
        triggers=[
            PolicyTrigger(
                rule_id=_required_string(item, "rule_id"),
                description=_required_string(item, "description"),
                citation=_source(item["citation"]) if isinstance(item.get("citation"), dict) else None,
            )
            for item in _dict_list(value.get("triggers", []))
        ],
        required_evidence=_string_list(value.get("required_evidence", [])),
        recommendation_clause_ids=_string_list(value.get("recommendation_clause_ids", [])),
        conflicts=[_conflict(item) for item in _dict_list(value.get("conflicts", []))],
        citations=[_citation(item) for item in _dict_list(value.get("citations", []))],
        escalated=value.get("escalated") is True,
        escalation_reasons=_string_list(value.get("escalation_reasons", [])),
    )


def _packet(value: dict[str, Any]) -> Packet:
    return Packet(
        packet_id=_required_string(value, "packet_id"),
        case_id=_required_string(value, "case_id"),
        packet_version=int(value["packet_version"]),
        packet_type=PacketType(_required_string(value, "packet_type")),
        sections=[
            PacketSection(
                key=_required_string(item, "key"),
                title=_required_string(item, "title"),
                body=_required_string(item, "body"),
                editable=item.get("editable") is True,
                citations=[_citation(citation) for citation in _dict_list(item.get("citations", []))],
            )
            for item in _dict_list(value.get("sections", []))
        ],
        recommendation_clause_ids=_string_list(value.get("recommendation_clause_ids", [])),
        unsupported_claims=_string_list(value.get("unsupported_claims", [])),
        citations=[_citation(item) for item in _dict_list(value.get("citations", []))],
        sha256=_optional_string(value.get("sha256")),
    )


def _human_decision(value: dict[str, Any]) -> HumanDecision:
    return HumanDecision(
        case_id=_required_string(value, "case_id"),
        decision_version=int(value["decision_version"]),
        reviewer_id=_required_string(value, "reviewer_id"),
        action=ReviewAction(_required_string(value, "action")),
        decided_at=_required_string(value, "decided_at"),
        approved_fields=copy.deepcopy(_required_dict(value, "approved_fields")),
        comments=_optional_string(value.get("comments")),
        edits=tuple(copy.deepcopy(_dict_list(value.get("edits", [])))),
    )


def _write_preview(value: dict[str, Any]) -> WritePreview:
    return WritePreview(
        case_id=_required_string(value, "case_id"),
        decision_version=int(value["decision_version"]),
        table=_required_string(value, "table"),
        record_id=_required_string(value, "record_id"),
        expected_record_version=int(value["expected_record_version"]),
        before=copy.deepcopy(_required_dict(value, "before")),
        after=copy.deepcopy(_required_dict(value, "after")),
        packet_version=int(value["packet_version"]) if value.get("packet_version") is not None else None,
        packet_sha256=_optional_string(value.get("packet_sha256")),
        field_changes=[
            FieldChange(field=_required_string(item, "field"), from_value=item.get("from"), to_value=item.get("to"))
            for item in _dict_list(value.get("field_changes", []))
        ],
        simulated=True,
    )


def _write_result(value: dict[str, Any]) -> WriteResult:
    attachment = value.get("attachment")
    return WriteResult(
        idempotency_key=_required_string(value, "idempotency_key"),
        record_id=_required_string(value, "record_id"),
        record_version=int(value["record_version"]),
        committed=value.get("committed") is True,
        duplicate_suppressed=value.get("duplicate_suppressed") is True,
        attachment=Attachment(
            attachment_id=_required_string(attachment, "attachment_id"),
            sha256=_required_string(attachment, "sha256"),
            already_present=attachment.get("already_present") is True,
        ) if isinstance(attachment, dict) else None,
        connector_response=copy.deepcopy(_required_dict(value, "connector_response")),
        simulated=True,
    )


def _audit_event(value: object) -> AuditEvent:
    if not isinstance(value, dict):
        raise RuntimeError("persisted audit event is malformed")
    return AuditEvent(
        event_id=_required_string(value, "event_id"),
        event_type=_required_string(value, "event_type"),
        case_id=_required_string(value, "case_id"),
        occurred_at=_required_string(value, "occurred_at"),
        actor_type=ActorType(_required_string(value, "actor_type")),
        actor_id=_optional_string(value.get("actor_id")),
        correlation_id=_optional_string(value.get("correlation_id")),
        workflow_version=_optional_string(value.get("workflow_version")),
        policy_version=_optional_string(value.get("policy_version")),
        decision_version=int(value["decision_version"]) if value.get("decision_version") is not None else None,
        detail=copy.deepcopy(value.get("detail", {})) if isinstance(value.get("detail", {}), dict) else {},
    )


def _restore_connector(value: object) -> MockServiceNowConnector:
    if not isinstance(value, dict):
        raise RuntimeError("workspace connector snapshot is malformed")
    connector = MockServiceNowConnector()
    records = value.get("records", {})
    if not isinstance(records, dict):
        raise RuntimeError("workspace connector snapshot is malformed")
    connector._records = {
        key: _Record(
            record_id=_required_string(item, "record_id"),
            table=_required_string(item, "table"),
            fields=copy.deepcopy(_required_dict(item, "fields")),
            version=int(item.get("version", 1)),
            attachments=_string_map(item.get("attachments", {})),
        )
        for key, item in records.items()
        if isinstance(key, str) and isinstance(item, dict)
    }
    connector._case_target = {
        key: (values[0], values[1])
        for key, values in value.get("case_target", {}).items()
        if isinstance(key, str)
        and isinstance(values, list)
        and len(values) == 2
        and all(isinstance(item, str) for item in values)
    }
    connector._staged = {
        key: _human_decision(item)
        for key, item in value.get("staged", {}).items()
        if isinstance(key, str) and isinstance(item, dict)
    }
    connector._committed = {
        key: _write_result(item)
        for key, item in value.get("committed", {}).items()
        if isinstance(key, str) and isinstance(item, dict)
    }
    connector._attachment_seq = int(value.get("attachment_sequence", 0))
    return connector


def _catalog_entry(value: dict[str, Any], *, workspace_id: str) -> SoftwareCatalogEntry:
    if value.get("workspace_id") != workspace_id:
        raise RuntimeError("catalog workspace isolation check failed")
    return SoftwareCatalogEntry(
        record_id=_required_string(value, "record_id"),
        canonical_name=_required_string(value, "canonical_name"),
        # The institutional export contains legitimately blank vendor cells.
        # Keep the raw null in raw_values while the typed search contract uses
        # an empty string for "not supplied".
        vendor=_optional_string(value.get("vendor")) or "",
        normalized_identity=_required_string(value, "normalized_identity"),
        source_row=int(value["source_row"]),
        source_hash=_required_string(value, "source_hash"),
        raw_values={str(key): item if item is None or isinstance(item, str) else str(item) for key, item in _required_dict(value, "raw_values").items()},
        supported_software=_optional_string(value.get("supported_software")),
        campus_license=_optional_string(value.get("campus_license")),
        aliases=tuple(_string_list(value.get("aliases", []))),
        short_name=_optional_string(value.get("short_name")),
        platform=tuple(_string_list(value.get("platform", []))),
        audience=_optional_string(value.get("audience")),
        workspace_id=workspace_id,
    )


def _approved_record(entry: SoftwareCatalogEntry) -> ApprovedSoftwareRecord:
    return ApprovedSoftwareRecord(
        record_id=entry.record_id,
        canonical_name=entry.canonical_name,
        vendor=entry.vendor,
        source_row=dict(entry.raw_values),
        aliases=list(entry.aliases),
        short_name=entry.short_name,
        platform=list(entry.platform),
        audience=entry.audience,
        support=entry.supported_software,
        licensing=entry.campus_license,
        supported_software=entry.supported_software,
        campus_license=entry.campus_license,
        source_hash=entry.source_hash,
        source_row_number=entry.source_row,
        normalized_identity=entry.normalized_identity,
        workspace_id=entry.workspace_id,
        source_coordinates=SourceCoordinates(
            source_id=f"operator:{entry.source_hash}",
            filename="SNOW Export_approved_software_database.xlsx",
            sheet="approved_software",
            row=entry.source_row,
            sha256=entry.source_hash,
        ),
    )


def _catalog_from_api(api: LocalReviewApi) -> list[SoftwareCatalogEntry]:
    return [
        item
        for item in api._vendor_repository.list("catalog", workspace_id=DEFAULT_WORKSPACE_ID)
        if isinstance(item, SoftwareCatalogEntry)
    ]


def _criterion(value: dict[str, Any]) -> ReviewCriterion:
    return ReviewCriterion(
        requirement_id=_required_string(value, "requirement_id"),
        question=_required_string(value, "question"),
        source_citation=copy.deepcopy(_required_dict(value, "source_citation")),
        expected_evidence=tuple(_string_list(value["expected_evidence"])),
        output_fields=tuple(_string_list(value["output_fields"])),
        remediation_guidance=_required_string(value, "remediation_guidance"),
    )


def _record_id(kind: str, value: dict[str, Any]) -> str:
    keys = {
        "vendor": "vendor_id",
        "product": "product_id",
        "contact": "contact_id",
        "case": "case_id",
        "invite": "invite_id",
        "submission": "submission_id",
        "evidence": "artifact_id",
        "coverage": "coverage_id",
        "profile": "profile_version_id",
        "run": "run_id",
        "event": "event_id",
        "finding": "finding_id",
    }
    key = keys.get(kind)
    if key is None:
        raise RuntimeError(f"unsupported record kind: {kind}")
    return _required_string(value, key)


def _required_dict(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise RuntimeError(f"persisted field {key!r} must be an object")
    return item


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise RuntimeError(f"persisted field {key!r} must be a string")
    return item


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError("persisted optional string is malformed")
    return value


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError("persisted string list is malformed")
    return list(value)


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeError("persisted object list is malformed")
    return value


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise RuntimeError("persisted string map is malformed")
    return dict(value)


def _safe_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise LocalApiError(400, "invalid_identifier", "identifier is invalid")
    return value


def _json_safe(value: object) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_safe(dataclasses.asdict(value))
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"value of type {type(value).__name__} is not JSON-safe")


def _json_dumps(value: object) -> str:
    return json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _json_clone(value: Any) -> Any:
    return json.loads(_json_dumps(value))


def _decimal_to_native(value: Any) -> Any:
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _decimal_to_native(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decimal_to_native(item) for item in value]
    return value


def _physical(workspace_id: str, value: str) -> str:
    return f"{workspace_id}#{value}"


def _epoch_micros(value: str) -> int:
    return int(datetime.datetime.fromisoformat(value).timestamp() * 1_000_000)


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the connected deterministic Lambda demo")
    parser.add_argument("seed", choices=["seed"])
    parser.add_argument("--workbook", required=True, help="operator-local 982-row approved-software XLSX")
    parser.add_argument("--workspace-id", default=DEFAULT_WORKSPACE_ID)
    parser.add_argument("--platform-stack", default="PlatformStack")
    parser.add_argument("--foundation-stack", default="ReviewFoundationStack")
    parser.add_argument("--profile")
    parser.add_argument("--region")
    parser.add_argument(
        "--out",
        help="seed to a local JSON workspace file (stdlib only, no AWS/boto3 required)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="reconcile and report counts only; write nothing",
    )
    parser.add_argument(
        "--expected-rows",
        type=int,
        default=982,
        help="required reconciled catalog row count (default 982)",
    )
    args = parser.parse_args(argv)
    reader = XlsxWorkbookReader(Path(args.workbook))
    normalized = normalize_workbook(
        reader,
        source_id=f"operator:{reader.source_hash}",
        workspace_id=args.workspace_id,
    )
    report = normalized.reconciliation
    if not report.rows_reconcile or not report.columns_reconcile:
        print("seed refused: workbook reconciliation failed", file=sys.stderr)
        return 2
    if report.output_rows != args.expected_rows:
        print(
            f"seed refused: expected {args.expected_rows} catalog rows, got {report.output_rows}",
            file=sys.stderr,
        )
        return 2
    if args.dry_run:
        print(
            _json_dumps(
                {
                    "dry_run": True,
                    "workspace_id": args.workspace_id,
                    "reconciled_rows": report.output_rows,
                    "preserved_columns": report.preserved_columns,
                    "duplicate_identity_groups": report.duplicate_identity_groups,
                    "catalog_membership_is_approval": False,
                }
            )
        )
        return 0
    if args.out:
        store: WorkspaceStore = FileWorkspaceStore(args.out)
    else:
        try:
            store = DynamoWorkspaceStore.from_stacks(
                platform_stack=args.platform_stack,
                foundation_stack=args.foundation_stack,
                profile=args.profile,
                region=args.region,
            )
        except ImportError:
            print(
                "seed refused: boto3 is required for the DynamoDB seed. Install the "
                "workspace's declared AWS extra (pip install -e '.[aws]') or seed a "
                "local file with --out PATH.",
                file=sys.stderr,
            )
            return 3
    result = seed_workspace(
        store,
        workspace_id=args.workspace_id,
        catalog_entries=normalized.catalog_entries(),
    )
    print(_json_dumps(result))
    return 0


_store: WorkspaceStore | None = None


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    global _store
    if _store is None:
        _store = DynamoWorkspaceStore.from_environment()
    origins = [item.strip() for item in os.environ.get("ALLOWED_ORIGINS", "").split(",") if item.strip()]
    application = create_handler(
        _store,
        workspace_id=os.environ.get("WORKSPACE_ID", DEFAULT_WORKSPACE_ID),
        allowed_origins=origins,
    )
    return application(event, context)


if __name__ == "__main__":
    raise SystemExit(main())
