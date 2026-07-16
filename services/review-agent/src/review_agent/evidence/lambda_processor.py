"""SQS-triggered Lambda entry point for quarantined evidence extraction."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import unquote_plus

from .extraction import AwsTextractAdapter, EvidenceProcessor, S3EvidenceObjectStore
from .ingestion import DynamoEvidenceStateStore

_processor: EvidenceProcessor | None = None
_state_store: DynamoEvidenceStateStore | None = None


def _build() -> tuple[EvidenceProcessor, DynamoEvidenceStateStore]:
    bucket = os.environ.get("EVIDENCE_BUCKET")
    if not bucket:
        raise RuntimeError("missing EVIDENCE_BUCKET")
    import boto3

    state = DynamoEvidenceStateStore.from_environment()
    processor = EvidenceProcessor(
        state_store=state,
        object_store=S3EvidenceObjectStore(
            bucket=bucket,
            client=boto3.client("s3", region_name=os.environ.get("AWS_REGION")),
            kms_key_id=os.environ.get("EVIDENCE_KMS_KEY_ID") or None,
        ),
        textract=AwsTextractAdapter(
            bucket=bucket,
            client=boto3.client("textract", region_name=os.environ.get("AWS_REGION")),
        ),
    )
    return processor, state


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    del context
    global _processor, _state_store
    if _processor is None or _state_store is None:
        _processor, _state_store = _build()
    failures: list[dict[str, str]] = []
    records = event.get("Records", [])
    if not isinstance(records, list):
        raise ValueError("SQS event Records must be a list")
    for message in records:
        message_id = str(message.get("messageId") or "") if isinstance(message, dict) else ""
        try:
            _process_message(message, _processor, _state_store)
        except Exception as error:
            print(
                json.dumps(
                    {
                        "event_type": "evidence.processing_failed",
                        "message_id": message_id,
                        "error_type": type(error).__name__,
                    },
                    sort_keys=True,
                )
            )
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}


def _process_message(
    message: Any,
    processor: EvidenceProcessor,
    state_store: DynamoEvidenceStateStore,
) -> None:
    if not isinstance(message, dict) or not isinstance(message.get("body"), str):
        raise ValueError("SQS message body is missing")
    payload = json.loads(message["body"])
    s3_records = payload.get("Records", []) if isinstance(payload, dict) else []
    if not isinstance(s3_records, list) or not s3_records:
        raise ValueError("S3 notification Records are missing")
    expected_bucket = os.environ.get("EVIDENCE_BUCKET")
    for notification in s3_records:
        s3 = notification.get("s3") if isinstance(notification, dict) else None
        bucket = s3.get("bucket") if isinstance(s3, dict) else None
        obj = s3.get("object") if isinstance(s3, dict) else None
        bucket_name = bucket.get("name") if isinstance(bucket, dict) else None
        object_key = unquote_plus(str(obj.get("key") or "")) if isinstance(obj, dict) else ""
        if bucket_name != expected_bucket:
            raise ValueError("S3 notification bucket does not match configuration")
        parts = object_key.split("/")
        if len(parts) < 6 or parts[0] != "quarantine":
            raise ValueError("S3 notification key is outside the quarantine prefix")
        workspace_id, case_id, artifact_id = parts[1], parts[2], parts[3]
        record = state_store.get(
            workspace_id=workspace_id,
            case_id=case_id,
            artifact_id=artifact_id,
        )
        if record is None or record.object_key != object_key:
            raise ValueError("S3 notification is not bound to a registered case artifact")
        result = processor.process(record)
        print(
            json.dumps(
                {
                    "event_type": "evidence.processing_completed",
                    "artifact_id": result.artifact_id,
                    "case_id": result.case_id,
                    "processing_state": result.processing_state.value,
                },
                sort_keys=True,
            )
        )
