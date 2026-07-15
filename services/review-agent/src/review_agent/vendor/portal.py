"""Vendor evidence portal orchestrator.

Ties the pieces into the flow the internal tool drives:

1. ``send_invite`` — mint a case-scoped link, notify the vendor AND the
   committee, and deploy the research agent (best-effort, in parallel with the
   vendor's upload).
2. ``ingest_upload`` — land a dropped file in the KMS-encrypted bucket and record
   its evidence metadata.
3. ``evaluate_gaps`` — deterministically compare provided vs. required evidence
   for a human to confirm.

Every step emits an audit event carrying identifiers/counts only — never
document bodies or credentials.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import TYPE_CHECKING

from ..adapters.storage import StorageClient
from ..audit.log import AuditLog
from ..contracts.audit import ActorType
from ..contracts.common import SourceCoordinates
from ..contracts.evidence import EvidenceRecord, EvidenceType
from ..contracts.policy import PolicyResult
from ..contracts.vendor import EvidenceGapReport
from .gaps import analyze_gaps
from .link import (
    LocalUploadLinkIssuer,
    S3PresignedUploadIssuer,
    UploadLinkIssuer,
    mint_invite,
    vendor_upload_key,
)
from .notify import MockNotifier, Notifier
from .research import DeterministicVendorResearch, ModelVendorResearch, VendorResearchClient

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import AppConfig

_DEFAULT_TTL_SECONDS = 7 * 24 * 3600  # seven days, aligning with the checkpoint TTL


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _add_seconds(iso: str, seconds: int) -> str:
    return (datetime.datetime.fromisoformat(iso) + datetime.timedelta(seconds=seconds)).isoformat()


class VendorEvidencePortal:
    def __init__(
        self,
        *,
        issuer: UploadLinkIssuer,
        notifier: Notifier,
        research: VendorResearchClient,
        storage: StorageClient,
        audit: AuditLog,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._issuer = issuer
        self._notifier = notifier
        self._research = research
        self._storage = storage
        self._audit = audit
        self._clock = clock
        self._seq = 0

    # -- step 1: send the link, notify both parties, deploy research -----------

    def send_invite(
        self,
        *,
        case_id: str,
        vendor: str,
        product: str,
        vendor_recipient: str,
        committee_recipients: list[str],
        official_domain: str | None = None,
        nonce: str,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> dict:
        created_at = self._clock()
        expires_at = _add_seconds(created_at, ttl_seconds)
        invite = mint_invite(
            case_id=case_id,
            vendor=vendor,
            product=product,
            vendor_recipient=vendor_recipient,
            committee_recipients=committee_recipients,
            nonce=nonce,
            created_at=created_at,
            expires_at=expires_at,
        )
        link = self._issuer.portal_link(invite)
        self._emit(case_id, "vendor.invite_created", ActorType.SYSTEM, expires_at=expires_at)

        vendor_receipt = self._notifier.notify_vendor(invite, link)
        committee_receipts = self._notifier.notify_committee(invite, link)
        self._emit(
            case_id,
            "vendor.link_sent",
            ActorType.SYSTEM,
            vendor_notified=vendor_receipt.sent,
            committee_notified=len(committee_receipts),
            simulated=True,
        )

        # Deploy the research agent now; it works while the vendor uploads.
        research = self._research.research(
            vendor=vendor, product=product, official_domain=official_domain
        )
        self._emit(
            case_id,
            "vendor.research_completed",
            ActorType.MODEL,
            findings=len(research.findings),
            uncertainty_disclosed=bool(research.uncertainty),
        )
        return {
            "invite": invite,
            "link": link,
            "vendor_receipt": vendor_receipt,
            "committee_receipts": committee_receipts,
            "research": research,
        }

    # -- step 2: the vendor drops a file; it lands in the bucket ---------------

    def ingest_upload(
        self,
        *,
        case_id: str,
        filename: str,
        body: bytes,
        evidence_type: EvidenceType,
        vendor: str | None = None,
        product: str | None = None,
    ) -> EvidenceRecord:
        key = vendor_upload_key(case_id, filename)
        sha256 = self._storage.put_object(key=key, body=body)
        record = EvidenceRecord(
            evidence_id=f"ev:{sha256[:16]}",
            case_id=case_id,
            evidence_type=evidence_type,
            source_sha256=sha256,
            vendor=vendor,
            product=product,
            source_coordinates=SourceCoordinates(source_id=key, sha256=sha256),
        )
        self._emit(
            case_id,
            "vendor.evidence_received",
            ActorType.SYSTEM,
            evidence_type=evidence_type.value,
            object_key=key,
            sha256=sha256,
        )
        return record

    # -- step 3: find the gaps against CSUB's required evidence ----------------

    def evaluate_gaps(
        self, *, case_id: str, policy_result: PolicyResult, evidence: list[EvidenceRecord]
    ) -> EvidenceGapReport:
        report = analyze_gaps(
            case_id=case_id, policy_result=policy_result, provided=evidence, clock=self._clock
        )
        self._emit(
            case_id,
            "vendor.gaps_evaluated",
            ActorType.SYSTEM,
            required=len(report.required),
            satisfied=len(report.satisfied),
            missing=len(report.missing),
        )
        return report

    # -- internals -------------------------------------------------------------

    def _emit(self, case_id: str, event_type: str, actor: ActorType, **detail: object) -> None:
        self._seq += 1
        self._audit.record(
            event_id=f"{case_id}-vendor-{self._seq:03d}",
            event_type=event_type,
            case_id=case_id,
            occurred_at=self._clock(),
            actor_type=actor,
            detail=dict(detail),
        )


def build_vendor_portal(config: AppConfig, audit: AuditLog) -> VendorEvidencePortal:
    """Composition-root factory: local fakes by default, live AWS otherwise.

    Notifications stay the ``MockNotifier`` in both modes — real SES/SNS delivery
    is out of scope until a channel and identities are approved (mirrors the
    ServiceNow write-back discipline).
    """
    from ..adapters.model import build_model_client
    from ..adapters.storage import build_storage

    storage = build_storage(config)
    if config.use_local_fakes:
        issuer: UploadLinkIssuer = LocalUploadLinkIssuer(portal_base_url=config.portal_base_url)
        research: VendorResearchClient = DeterministicVendorResearch()
    else:
        issuer = S3PresignedUploadIssuer(storage=storage, portal_base_url=config.portal_base_url)  # type: ignore[arg-type]
        research = ModelVendorResearch(build_model_client(config))
    return VendorEvidencePortal(
        issuer=issuer,
        notifier=MockNotifier(),
        research=research,
        storage=storage,
        audit=audit,
    )
