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

    def view_url(self, *, key: str, content_type: str = "application/pdf") -> str:
        """Return a view link for ``key`` (presigned on S3, CloudFront-safe path locally)."""
        ...


class InMemoryStorage:
    """Deterministic in-memory object store for the local slice and tests."""

    def __init__(self, *, cloudfront_base_url: str | None = None) -> None:
        self._objects: dict[str, bytes] = {}
        self._cloudfront_base_url = cloudfront_base_url.rstrip("/") if cloudfront_base_url else None

    def put_object(self, *, key: str, body: bytes) -> str:
        self._objects[key] = body
        return hashlib.sha256(body).hexdigest()

    def get_object(self, *, key: str) -> bytes:
        return self._objects[key]

    def exists(self, *, key: str) -> bool:
        return key in self._objects

    def view_url(self, *, key: str, content_type: str = "application/pdf") -> str:
        # A relative, CloudFront-safe path the reviewer web app (or a CloudFront
        # distribution) can serve without exposing bucket internals or presigning.
        if self._cloudfront_base_url:
            return f"{self._cloudfront_base_url}/{key}"
        return f"/generated/{key}"


class S3Storage:
    """Amazon S3 implementation for generated packet artifacts.

    Writes with SSE-KMS when a key is configured and returns a presigned GET URL
    (or a CloudFront-safe URL when a distribution domain is configured, so tokens
    are not required in access-logged paths). ``boto3`` is imported lazily so the
    stdlib local slice never needs it.
    """

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        kms_key_id: str | None = None,
        cloudfront_base_url: str | None = None,
        presign_expiry_seconds: int = 900,
        client: object | None = None,
    ) -> None:
        self._bucket = bucket
        self._region = region
        self._kms_key_id = kms_key_id
        self._cloudfront_base_url = cloudfront_base_url.rstrip("/") if cloudfront_base_url else None
        self._presign_expiry_seconds = presign_expiry_seconds
        self._client = client

    def _s3(self):
        if self._client is None:
            import boto3  # lazy: only needed when talking to live AWS

            self._client = boto3.client("s3", region_name=self._region)
        return self._client

    def put_object(self, *, key: str, body: bytes) -> str:
        params = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": body,
            "ContentType": "application/pdf",
        }
        if self._kms_key_id:
            params["ServerSideEncryption"] = "aws:kms"
            params["SSEKMSKeyId"] = self._kms_key_id
        self._s3().put_object(**params)
        return hashlib.sha256(body).hexdigest()

    def get_object(self, *, key: str) -> bytes:
        response = self._s3().get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def exists(self, *, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._s3().head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    def view_url(self, *, key: str, content_type: str = "application/pdf") -> str:
        # Prefer a CloudFront-safe URL (no query-string credentials in access
        # logs); otherwise fall back to a short-lived presigned GET URL.
        if self._cloudfront_base_url:
            return f"{self._cloudfront_base_url}/{key}"
        return self._s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key, "ResponseContentType": content_type},
            ExpiresIn=self._presign_expiry_seconds,
        )
