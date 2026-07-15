"""Source manifest construction (PRD sec 5).

Every ingested Box artifact gets a manifest entry retaining its original
identity, hash, and version. Source bytes are hashed here but never committed to
Git. ``ingested_at`` is passed in by the caller so ingestion stays deterministic
and testable.
"""

from __future__ import annotations

import hashlib

from ..contracts.evidence import SourceManifestEntry


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def build_manifest_entry(
    *,
    source_id: str,
    filename: str,
    mime_type: str,
    body: bytes,
    category: str,
    version: str,
    ingested_at: str,
    vendor: str | None = None,
    product: str | None = None,
    authority: str | None = None,
    allowed_use: str | None = None,
    retention: str | None = None,
) -> SourceManifestEntry:
    return SourceManifestEntry(
        source_id=source_id,
        filename=filename,
        mime_type=mime_type,
        sha256=sha256_bytes(body),
        version=version,
        category=category,
        ingested_at=ingested_at,
        vendor=vendor,
        product=product,
        authority=authority,
        allowed_use=allowed_use,
        retention=retention,
        extraction_state="ingested",
    )
