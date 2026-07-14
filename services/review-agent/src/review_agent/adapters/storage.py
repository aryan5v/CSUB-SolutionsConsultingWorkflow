"""Storage adapter: object storage behind an interface with an in-memory fake.

The prototype keeps originals, lossless snapshots, evidence, and generated
packets in KMS-encrypted S3 (PRD sec 5). The local slice uses an in-memory
store so ingestion and packet flows run without AWS. The S3 implementation is a
documented seam wired Wednesday.
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable


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
    """Amazon S3 implementation (wired Wednesday).

    Will use ``boto3.client("s3")`` with SSE-KMS enforced by bucket policy and
    the key layout from PRD sec 5
    (``raw/<box-file-id>/<sha256>/<filename>`` etc.). Kept as a seam so the
    interface is real now without importing boto3 in the local slice.
    """

    def __init__(self, *, bucket: str, region: str, kms_key_id: str | None = None) -> None:
        self._bucket = bucket
        self._region = region
        self._kms_key_id = kms_key_id

    def put_object(self, *, key: str, body: bytes) -> str:  # pragma: no cover - Wednesday
        raise NotImplementedError("S3Storage is wired during Wednesday AWS integration.")

    def get_object(self, *, key: str) -> bytes:  # pragma: no cover - Wednesday
        raise NotImplementedError("S3Storage is wired during Wednesday AWS integration.")

    def exists(self, *, key: str) -> bool:  # pragma: no cover - Wednesday
        raise NotImplementedError("S3Storage is wired during Wednesday AWS integration.")
