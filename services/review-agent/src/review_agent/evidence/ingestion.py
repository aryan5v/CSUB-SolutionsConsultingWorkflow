"""Case-scoped evidence upload registration and durable processing state."""

from __future__ import annotations

import base64
import datetime
import hashlib
import os
import secrets
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

MAX_EVIDENCE_BYTES = 5_000_000
PRESIGN_TTL_SECONDS = 300
SUPPORTED_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
        "text/plain",
        "image/png",
        "image/jpeg",
    }
)
MANUAL_REVIEW_CONTENT_TYPES = frozenset(
    {
        "application/rtf",
        "application/octet-stream",
        "application/vnd.ms-outlook",
        "application/x-msg",
    }
)
ACCEPTED_CONTENT_TYPES = SUPPORTED_CONTENT_TYPES | MANUAL_REVIEW_CONTENT_TYPES


class ProcessingState(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True, slots=True)
class EvidenceUploadRecord:
    workspace_id: str
    case_id: str
    product_id: str
    vendor_id: str
    submission_id: str
    artifact_id: str
    filename: str
    declared_content_type: str
    expected_size_bytes: int
    source_sha256: str
    object_key: str
    processing_state: ProcessingState = ProcessingState.QUEUED
    source_version_id: str | None = None
    detected_content_type: str | None = None
    extraction_key: str | None = None
    extraction_event_id: str | None = None
    warnings: tuple[str, ...] = ()
    failure_code: str | None = None
    updated_at: str | None = None
    lease_until: int | None = None
    claim_token: str | None = None

    @property
    def scope_id(self) -> str:
        return scope_id(self.workspace_id, self.case_id)

    def to_item(self) -> dict[str, Any]:
        value = asdict(self)
        value["processing_state"] = self.processing_state.value
        value["warnings"] = list(self.warnings)
        value["scope_id"] = self.scope_id
        return value

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "case_id": self.case_id,
            "product_id": self.product_id,
            "filename": self.filename,
            "content_type": self.declared_content_type,
            "size_bytes": self.expected_size_bytes,
            "sha256": self.source_sha256,
            "processing_state": self.processing_state.value,
            "source_version_id": self.source_version_id,
            "detected_content_type": self.detected_content_type,
            "source_location": self.extraction_key,
            "warnings": list(self.warnings),
            "failure_code": self.failure_code,
            "untrusted": True,
            "model_use_allowed": False,
        }

    @classmethod
    def from_item(cls, value: dict[str, Any]) -> EvidenceUploadRecord:
        return cls(
            workspace_id=_required_string(value, "workspace_id"),
            case_id=_required_string(value, "case_id"),
            product_id=_required_string(value, "product_id"),
            vendor_id=_required_string(value, "vendor_id"),
            submission_id=_required_string(value, "submission_id"),
            artifact_id=_required_string(value, "artifact_id"),
            filename=_required_string(value, "filename"),
            declared_content_type=_required_string(value, "declared_content_type"),
            expected_size_bytes=int(value["expected_size_bytes"]),
            source_sha256=_required_string(value, "source_sha256"),
            object_key=_required_string(value, "object_key"),
            processing_state=ProcessingState(value.get("processing_state", "queued")),
            source_version_id=_optional_string(value.get("source_version_id")),
            detected_content_type=_optional_string(value.get("detected_content_type")),
            extraction_key=_optional_string(value.get("extraction_key")),
            extraction_event_id=_optional_string(value.get("extraction_event_id")),
            warnings=tuple(_string_list(value.get("warnings", []))),
            failure_code=_optional_string(value.get("failure_code")),
            updated_at=_optional_string(value.get("updated_at")),
            lease_until=int(value["lease_until"]) if value.get("lease_until") is not None else None,
            claim_token=_optional_string(value.get("claim_token")),
        )


@runtime_checkable
class EvidenceStateStore(Protocol):
    def register(self, record: EvidenceUploadRecord) -> EvidenceUploadRecord: ...

    def get(self, *, workspace_id: str, case_id: str, artifact_id: str) -> EvidenceUploadRecord | None: ...

    def claim(
        self, record: EvidenceUploadRecord, *, now_epoch: int, lease_seconds: int
    ) -> str | None: ...

    def complete(
        self,
        record: EvidenceUploadRecord,
        *,
        claim_token: str,
        state: ProcessingState,
        source_version_id: str | None,
        detected_content_type: str | None,
        extraction_key: str | None,
        warnings: tuple[str, ...],
        failure_code: str | None,
        extraction_event_id: str | None,
    ) -> EvidenceUploadRecord: ...


class EvidenceClaimLostError(RuntimeError):
    """Raised when a worker tries to complete a claim it no longer owns."""


class InMemoryEvidenceStateStore:
    """Strictly scoped state fake used by parser, authorization, and retry tests."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], EvidenceUploadRecord] = {}

    def register(self, record: EvidenceUploadRecord) -> EvidenceUploadRecord:
        key = (record.scope_id, record.artifact_id)
        current = self._records.get(key)
        if current is not None:
            _assert_same_source(current, record)
            return current
        self._records[key] = record
        return record

    def get(self, *, workspace_id: str, case_id: str, artifact_id: str) -> EvidenceUploadRecord | None:
        return self._records.get((scope_id(workspace_id, case_id), artifact_id))

    def claim(
        self, record: EvidenceUploadRecord, *, now_epoch: int, lease_seconds: int
    ) -> str | None:
        key = (record.scope_id, record.artifact_id)
        current = self._records.get(key)
        if current is None:
            return None
        if current.processing_state in {ProcessingState.READY, ProcessingState.MANUAL_REVIEW}:
            return None
        if (
            current.processing_state is ProcessingState.PROCESSING
            and current.lease_until is not None
            and current.lease_until >= now_epoch
        ):
            return None
        claim_token = secrets.token_urlsafe(32)
        self._records[key] = _replace_record(
            current,
            processing_state=ProcessingState.PROCESSING,
            updated_at=_utc_now(),
            lease_until=now_epoch + lease_seconds,
            claim_token=claim_token,
        )
        return claim_token

    def complete(
        self,
        record: EvidenceUploadRecord,
        *,
        claim_token: str,
        state: ProcessingState,
        source_version_id: str | None,
        detected_content_type: str | None,
        extraction_key: str | None,
        warnings: tuple[str, ...],
        failure_code: str | None,
        extraction_event_id: str | None,
    ) -> EvidenceUploadRecord:
        key = (record.scope_id, record.artifact_id)
        current = self._records[key]
        if (
            current.processing_state is not ProcessingState.PROCESSING
            or current.claim_token != claim_token
        ):
            raise EvidenceClaimLostError("evidence processing claim is stale")
        completed = _replace_record(
            current,
            processing_state=state,
            source_version_id=source_version_id,
            detected_content_type=detected_content_type,
            extraction_key=extraction_key,
            extraction_event_id=extraction_event_id,
            warnings=warnings,
            failure_code=failure_code,
            updated_at=_utc_now(),
            lease_until=None,
            claim_token=None,
        )
        self._records[key] = completed
        return completed


class DynamoEvidenceStateStore:
    """DynamoDB evidence-state adapter with conditional idempotency and leases."""

    def __init__(self, table: Any) -> None:
        self._table = table

    @classmethod
    def from_environment(cls) -> DynamoEvidenceStateStore:
        table_name = os.environ.get("EVIDENCE_STATE_TABLE")
        if not table_name:
            raise RuntimeError("missing EVIDENCE_STATE_TABLE")
        import boto3

        return cls(boto3.resource("dynamodb").Table(table_name))

    def register(self, record: EvidenceUploadRecord) -> EvidenceUploadRecord:
        try:
            self._table.put_item(
                Item=record.to_item(),
                ConditionExpression="attribute_not_exists(artifact_id)",
            )
            return record
        except Exception as error:
            if not _is_conditional_failure(error):
                raise
        current = self.get(
            workspace_id=record.workspace_id,
            case_id=record.case_id,
            artifact_id=record.artifact_id,
        )
        if current is None:
            raise RuntimeError("evidence registration lost after conditional conflict")
        _assert_same_source(current, record)
        return current

    def get(self, *, workspace_id: str, case_id: str, artifact_id: str) -> EvidenceUploadRecord | None:
        response = self._table.get_item(
            Key={"scope_id": scope_id(workspace_id, case_id), "artifact_id": artifact_id},
            ConsistentRead=True,
        )
        item = response.get("Item")
        return EvidenceUploadRecord.from_item(item) if isinstance(item, dict) else None

    def claim(
        self, record: EvidenceUploadRecord, *, now_epoch: int, lease_seconds: int
    ) -> str | None:
        claim_token = secrets.token_urlsafe(32)
        try:
            self._table.update_item(
                Key={"scope_id": record.scope_id, "artifact_id": record.artifact_id},
                UpdateExpression=(
                    "SET processing_state = :processing, updated_at = :updated, "
                    "lease_until = :lease, claim_token = :claim REMOVE failure_code"
                ),
                ConditionExpression=(
                    "processing_state IN (:queued, :failed) OR "
                    "(processing_state = :processing AND lease_until < :now)"
                ),
                ExpressionAttributeValues={
                    ":queued": ProcessingState.QUEUED.value,
                    ":failed": ProcessingState.FAILED.value,
                    ":processing": ProcessingState.PROCESSING.value,
                    ":now": now_epoch,
                    ":lease": now_epoch + lease_seconds,
                    ":claim": claim_token,
                    ":updated": _utc_now(),
                },
            )
            return claim_token
        except Exception as error:
            if _is_conditional_failure(error):
                return None
            raise

    def complete(
        self,
        record: EvidenceUploadRecord,
        *,
        claim_token: str,
        state: ProcessingState,
        source_version_id: str | None,
        detected_content_type: str | None,
        extraction_key: str | None,
        warnings: tuple[str, ...],
        failure_code: str | None,
        extraction_event_id: str | None,
    ) -> EvidenceUploadRecord:
        try:
            response = self._table.update_item(
                Key={"scope_id": record.scope_id, "artifact_id": record.artifact_id},
                UpdateExpression=(
                    "SET processing_state = :state, source_version_id = :version, "
                    "detected_content_type = :detected, extraction_key = :extraction, "
                    "extraction_event_id = :event, warnings = :warnings, "
                    "failure_code = :failure, updated_at = :updated "
                    "REMOVE lease_until, claim_token"
                ),
                ConditionExpression=(
                    "processing_state = :processing AND claim_token = :claim"
                ),
                ExpressionAttributeValues={
                    ":state": state.value,
                    ":version": source_version_id,
                    ":detected": detected_content_type,
                    ":extraction": extraction_key,
                    ":event": extraction_event_id,
                    ":warnings": list(warnings),
                    ":failure": failure_code,
                    ":updated": _utc_now(),
                    ":processing": ProcessingState.PROCESSING.value,
                    ":claim": claim_token,
                },
                ReturnValues="ALL_NEW",
            )
        except Exception as error:
            if _is_conditional_failure(error):
                raise EvidenceClaimLostError("evidence processing claim is stale") from error
            raise
        item = response.get("Attributes")
        if not isinstance(item, dict):
            raise RuntimeError("evidence completion did not return durable state")
        return EvidenceUploadRecord.from_item(item)


@runtime_checkable
class EvidenceUploadIssuer(Protocol):
    def issue(
        self,
        *,
        workspace_id: str,
        case_id: str,
        product_id: str,
        vendor_id: str,
        submission_id: str,
        artifact_id: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
    ) -> dict[str, Any]: ...

    def statuses(
        self, *, workspace_id: str, case_id: str, artifact_ids: list[str]
    ) -> list[dict[str, Any]]: ...


class DisabledEvidenceUploadIssuer:
    """Local fallback that records no bytes and never fabricates a live upload."""

    def issue(self, **_kwargs: Any) -> dict[str, Any]:
        return {"processing_state": ProcessingState.QUEUED.value, "upload": None}

    def statuses(
        self, *, workspace_id: str, case_id: str, artifact_ids: list[str]
    ) -> list[dict[str, Any]]:
        del workspace_id, case_id
        return [
            {"artifact_id": artifact_id, "processing_state": ProcessingState.QUEUED.value}
            for artifact_id in artifact_ids
        ]


class S3EvidenceUploadIssuer:
    """Presigned POST issuer constrained to immutable quarantine metadata."""

    def __init__(
        self,
        *,
        bucket: str,
        state_store: EvidenceStateStore,
        s3_client: Any,
        kms_key_id: str | None = None,
        expires_seconds: int = PRESIGN_TTL_SECONDS,
    ) -> None:
        self._bucket = bucket
        self._state_store = state_store
        self._s3 = s3_client
        self._kms_key_id = kms_key_id
        self._expires_seconds = min(max(expires_seconds, 60), PRESIGN_TTL_SECONDS)

    @classmethod
    def from_environment(cls) -> S3EvidenceUploadIssuer:
        bucket = os.environ.get("EVIDENCE_BUCKET")
        if not bucket:
            raise RuntimeError("missing EVIDENCE_BUCKET")
        import boto3

        return cls(
            bucket=bucket,
            state_store=DynamoEvidenceStateStore.from_environment(),
            s3_client=boto3.client("s3", region_name=os.environ.get("AWS_REGION")),
            kms_key_id=os.environ.get("EVIDENCE_KMS_KEY_ID") or None,
            expires_seconds=int(os.environ.get("PRESIGN_TTL_SECONDS", PRESIGN_TTL_SECONDS)),
        )

    def issue(
        self,
        *,
        workspace_id: str,
        case_id: str,
        product_id: str,
        vendor_id: str,
        submission_id: str,
        artifact_id: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
    ) -> dict[str, Any]:
        validate_upload_metadata(content_type=content_type, size_bytes=size_bytes, sha256=sha256)
        object_key = quarantine_key(
            workspace_id=workspace_id,
            case_id=case_id,
            artifact_id=artifact_id,
            sha256=sha256,
            filename=filename,
        )
        record = EvidenceUploadRecord(
            workspace_id=workspace_id,
            case_id=case_id,
            product_id=product_id,
            vendor_id=vendor_id,
            submission_id=submission_id,
            artifact_id=artifact_id,
            filename=filename,
            declared_content_type=content_type,
            expected_size_bytes=size_bytes,
            source_sha256=sha256,
            object_key=object_key,
            updated_at=_utc_now(),
        )
        record = self._state_store.register(record)
        checksum = base64.b64encode(bytes.fromhex(record.source_sha256)).decode("ascii")
        fields = {
            "Content-Type": record.declared_content_type,
            "x-amz-checksum-sha256": checksum,
            "x-amz-meta-workspace-id": record.workspace_id,
            "x-amz-meta-case-id": record.case_id,
            "x-amz-meta-product-id": record.product_id,
            "x-amz-meta-artifact-id": record.artifact_id,
            "x-amz-meta-source-sha256": record.source_sha256,
            "x-amz-server-side-encryption": "aws:kms",
        }
        if self._kms_key_id:
            fields["x-amz-server-side-encryption-aws-kms-key-id"] = self._kms_key_id
        conditions: list[Any] = [
            ["content-length-range", 1, MAX_EVIDENCE_BYTES],
            *({key: value} for key, value in fields.items()),
        ]
        upload = self._s3.generate_presigned_post(
            Bucket=self._bucket,
            Key=record.object_key,
            Fields=fields,
            Conditions=conditions,
            ExpiresIn=self._expires_seconds,
        )
        return {
            **record.to_public_dict(),
            "upload": {
                "url": upload["url"],
                "method": "POST",
                "fields": upload["fields"],
            },
        }

    def statuses(
        self, *, workspace_id: str, case_id: str, artifact_ids: list[str]
    ) -> list[dict[str, Any]]:
        records = []
        for artifact_id in artifact_ids:
            record = self._state_store.get(
                workspace_id=workspace_id,
                case_id=case_id,
                artifact_id=artifact_id,
            )
            if record is not None:
                records.append(record.to_public_dict())
        return records


def build_evidence_upload_issuer() -> EvidenceUploadIssuer:
    if os.environ.get("USE_LOCAL_FAKES", "true").lower() != "false":
        return DisabledEvidenceUploadIssuer()
    if not os.environ.get("EVIDENCE_BUCKET") or not os.environ.get("EVIDENCE_STATE_TABLE"):
        return DisabledEvidenceUploadIssuer()
    return S3EvidenceUploadIssuer.from_environment()


def validate_upload_metadata(*, content_type: str, size_bytes: int, sha256: str) -> None:
    if content_type not in ACCEPTED_CONTENT_TYPES:
        raise ValueError("unsupported evidence content type")
    if isinstance(size_bytes, bool) or not 1 <= size_bytes <= MAX_EVIDENCE_BYTES:
        raise ValueError(f"evidence size must be between 1 and {MAX_EVIDENCE_BYTES} bytes")
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256.lower()):
        raise ValueError("evidence sha256 must contain 64 hexadecimal characters")


def quarantine_key(
    *, workspace_id: str, case_id: str, artifact_id: str, sha256: str, filename: str
) -> str:
    safe_filename = quote(filename, safe="-_.")
    return (
        f"quarantine/{workspace_id}/{case_id}/{artifact_id}/"
        f"{sha256.lower()}/{safe_filename}"
    )


def extraction_key(record: EvidenceUploadRecord) -> str:
    return (
        f"case-evidence/{record.workspace_id}/{record.case_id}/{record.product_id}/"
        f"{record.artifact_id}/{record.source_sha256}/extraction.json"
    )


def scope_id(workspace_id: str, case_id: str) -> str:
    return f"{workspace_id}#{case_id}"


def extraction_event_id(record: EvidenceUploadRecord) -> str:
    return hashlib.sha256(
        f"{record.scope_id}:{record.artifact_id}:{record.source_sha256}".encode("utf-8")
    ).hexdigest()


def _replace_record(record: EvidenceUploadRecord, **changes: Any) -> EvidenceUploadRecord:
    values = asdict(record)
    values.update(changes)
    values.pop("scope_id", None)
    warnings = values.get("warnings", ())
    values["warnings"] = tuple(warnings)
    state = values.get("processing_state")
    if isinstance(state, str):
        values["processing_state"] = ProcessingState(state)
    return EvidenceUploadRecord(**values)


def _assert_same_source(current: EvidenceUploadRecord, requested: EvidenceUploadRecord) -> None:
    immutable = (
        "workspace_id",
        "case_id",
        "product_id",
        "vendor_id",
        "submission_id",
        "artifact_id",
        "filename",
        "declared_content_type",
        "expected_size_bytes",
        "source_sha256",
        "object_key",
    )
    if any(getattr(current, name) != getattr(requested, name) for name in immutable):
        raise ValueError("artifact identifier is already bound to different evidence metadata")


def _is_conditional_failure(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return False
    details = response.get("Error")
    return isinstance(details, dict) and details.get("Code") == "ConditionalCheckFailedException"


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"invalid evidence state field: {key}")
    return item


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid optional evidence state field")
    return value


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise ValueError("invalid evidence warnings")
    return list(value)


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
