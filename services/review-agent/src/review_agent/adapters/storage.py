"""Storage adapter: object storage behind an interface with an in-memory fake.

The prototype keeps originals, lossless snapshots, evidence, and generated
packets in KMS-encrypted S3 (PRD sec 5). The local slice uses an in-memory
store so ingestion and packet flows run without AWS. The S3 implementation is a
documented seam wired Wednesday.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import AppConfig


@runtime_checkable
class StorageClient(Protocol):
    def put_object(self, *, key: str, body: bytes) -> str:
        """Store ``body`` at ``key`` and return its sha256 hex digest."""
        ...

    def get_object(self, *, key: str) -> bytes: ...

    def exists(self, *, key: str) -> bool: ...


class InMemoryStorage:
    """Deterministic in-memory object store for the local slice and tests."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put_object(self, *, key: str, body: bytes) -> str:
        self._objects[key] = body
        return hashlib.sha256(body).hexdigest()

    def get_object(self, *, key: str) -> bytes:
        return self._objects[key]

    def exists(self, *, key: str) -> bool:
        return key in self._objects


class S3Storage:
    """Amazon S3 implementation with SSE-KMS enforced per object.

    The deployed buckets default to ``aws:kms`` with the foundation data key, but
    this writer also sets ``ServerSideEncryption``/``SSEKMSKeyId`` explicitly so
    every put is encrypted with the intended key regardless of bucket defaults
    (PRD sec 5). ``boto3`` is imported lazily so the stdlib local slice and CI are
    unchanged. Callers own the key layout, e.g.
    ``raw/<box-file-id>/<sha256>/<filename>``.
    """

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        kms_key_id: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._bucket = bucket
        self._region = region
        self._kms_key_id = kms_key_id
        self._client = client

    def _s3(self) -> Any:
        if self._client is None:
            import boto3  # lazy: only needed when talking to live AWS

            self._client = boto3.client("s3", region_name=self._region)
        return self._client

    def put_object(self, *, key: str, body: bytes) -> str:
        extra: dict[str, Any] = {"ServerSideEncryption": "aws:kms"}
        if self._kms_key_id:
            extra["SSEKMSKeyId"] = self._kms_key_id
        self._s3().put_object(Bucket=self._bucket, Key=key, Body=body, **extra)
        return hashlib.sha256(body).hexdigest()

    def get_object(self, *, key: str) -> bytes:
        response = self._s3().get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def exists(self, *, key: str) -> bool:
        try:
            self._s3().head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception as exc:  # botocore ClientError, duck-typed to keep CI stdlib-only
            response = getattr(exc, "response", None)
            if not isinstance(response, dict):
                raise
            error = response.get("Error", {})
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if error.get("Code") in ("404", "NoSuchKey", "NotFound") or status == 404:
                return False
            raise


def build_storage(config: AppConfig, *, bucket: str | None = None) -> StorageClient:
    """Composition-root factory: in-memory locally, SSE-KMS S3 on AWS.

    ``bucket`` defaults to the raw-sources bucket from config. Returns
    ``InMemoryStorage`` when ``use_local_fakes`` is set (default and CI).
    """
    if config.use_local_fakes:
        return InMemoryStorage()
    target = bucket or config.aws.raw_bucket
    if not target:
        raise ValueError(
            "RAW_BUCKET (or an explicit bucket) is required when USE_LOCAL_FAKES=false"
        )
    return S3Storage(
        bucket=target,
        region=config.aws.region,
        kms_key_id=config.aws.kms_key_arn,
    )
