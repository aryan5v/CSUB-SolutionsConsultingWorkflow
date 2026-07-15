"""Case-scoped vendor upload link (PLAN stretch: vendor document-upload link).

The app mints a tokenized, expiring link the vendor uses to drop compliance
evidence. The link points to a portal URL; the actual file drop lands in the
KMS-encrypted raw bucket under a case-scoped prefix. ``boto3`` stays behind the
S3 issuer and is imported lazily by ``S3Storage``; the local fake needs no AWS.

The token is a keyed digest of the case id and a per-invite nonce. In the local
slice the nonce is injected for determinism; in production it must come from a
high-entropy secret so links are unguessable.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..contracts.vendor import VendorInvite, VendorPortalLink

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..adapters.storage import S3Storage


def vendor_upload_key(case_id: str, filename: str) -> str:
    """S3 key for one vendor-dropped file. Case-scoped so retrieval never
    crosses case boundaries (FR-4). Filename is sanitized to a safe leaf."""
    safe = filename.replace("\\", "/").rsplit("/", 1)[-1].strip() or "upload"
    safe = "".join(c for c in safe if c.isalnum() or c in ("-", "_", ".", " ")).strip()
    return f"raw/{case_id}/vendor-upload/{safe or 'upload'}"


def _mint_token(case_id: str, nonce: str) -> str:
    return hashlib.sha256(f"{case_id}:{nonce}".encode()).hexdigest()[:40]


def mint_invite(
    *,
    case_id: str,
    vendor: str,
    product: str,
    vendor_recipient: str,
    committee_recipients: list[str],
    nonce: str,
    created_at: str,
    expires_at: str,
) -> VendorInvite:
    """Build a case-scoped invite. Pure: token derives from case_id + nonce."""
    return VendorInvite(
        case_id=case_id,
        vendor=vendor,
        product=product,
        token=_mint_token(case_id, nonce),
        upload_prefix=f"raw/{case_id}/vendor-upload/",
        vendor_recipient=vendor_recipient,
        committee_recipients=list(committee_recipients),
        created_at=created_at,
        expires_at=expires_at,
    )


@runtime_checkable
class UploadLinkIssuer(Protocol):
    def portal_link(self, invite: VendorInvite) -> VendorPortalLink:
        """The link the vendor opens to submit evidence."""
        ...

    def upload_url(self, *, case_id: str, filename: str, expires_in: int = 3600) -> str:
        """A direct upload target for one file (presigned in S3)."""
        ...


class LocalUploadLinkIssuer:
    """Deterministic issuer for the local slice and tests (no AWS)."""

    def __init__(self, *, portal_base_url: str = "https://portal.example.edu") -> None:
        self._base = portal_base_url.rstrip("/")

    def portal_link(self, invite: VendorInvite) -> VendorPortalLink:
        return VendorPortalLink(
            url=f"{self._base}/vendor/upload?token={invite.token}",
            token=invite.token,
            upload_prefix=invite.upload_prefix,
            expires_at=invite.expires_at,
        )

    def upload_url(self, *, case_id: str, filename: str, expires_in: int = 3600) -> str:
        # No presign locally; return the deterministic object location.
        return f"memory://{vendor_upload_key(case_id, filename)}"


class S3PresignedUploadIssuer:
    """Issues a portal link plus presigned S3 PUT URLs for each dropped file."""

    def __init__(self, *, storage: S3Storage, portal_base_url: str) -> None:
        self._storage = storage
        self._base = portal_base_url.rstrip("/")

    def portal_link(self, invite: VendorInvite) -> VendorPortalLink:
        return VendorPortalLink(
            url=f"{self._base}/vendor/upload?token={invite.token}",
            token=invite.token,
            upload_prefix=invite.upload_prefix,
            expires_at=invite.expires_at,
        )

    def upload_url(self, *, case_id: str, filename: str, expires_in: int = 3600) -> str:
        return self._storage.presigned_put_url(
            key=vendor_upload_key(case_id, filename), expires_in=expires_in
        )
