"""Live vendor evidence-portal smoke check (manual, not part of CI).

Drives the full flow against real AWS: send the case-scoped link (notifying the
vendor and committee via the mock notifier), deploy the Bedrock research agent,
drop a synthetic file through a presigned PUT into the KMS-encrypted bucket, and
compute the deterministic gap against CSUB's required evidence. Deletes the
dropped object afterward. Writes only synthetic, non-sensitive data and never
sends a real email.

    USE_LOCAL_FAKES=false AWS_REGION=us-west-2 RAW_BUCKET=... DATA_KEY_ARN=... \
        python services/review-agent/scripts/smoke_vendor_portal.py
"""

from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from review_agent.audit.log import AuditLog, InMemoryAuditSink  # noqa: E402
from review_agent.config import AppConfig  # noqa: E402
from review_agent.contracts.evidence import EvidenceType  # noqa: E402
from review_agent.contracts.policy import PolicyResult, RiskRoute  # noqa: E402
from review_agent.vendor.link import vendor_upload_key  # noqa: E402
from review_agent.vendor.portal import build_vendor_portal  # noqa: E402

_CASE = "SMOKE-VENDOR-1"


def main() -> int:
    os.environ.setdefault("USE_LOCAL_FAKES", "false")
    config = AppConfig.from_env()
    if config.use_local_fakes or not config.aws.raw_bucket:
        print("Set USE_LOCAL_FAKES=false and RAW_BUCKET to the foundation bucket.")
        return 1

    sink = InMemoryAuditSink()
    portal = build_vendor_portal(config, AuditLog(sink=sink))

    result = portal.send_invite(
        case_id=_CASE,
        vendor="Acme Analytics",
        product="Insight Cloud",
        vendor_recipient="security@acme.example",
        committee_recipients=["chair@csub.edu"],
        official_domain="acme.example",
        nonce="smoke-nonce",
    )
    print(f"1) link:        {result['link'].url}")
    print(f"   notified:    vendor + {len(result['committee_receipts'])} committee (simulated)")
    print(f"   research:    {len(result['research'].findings)} findings, "
          f"uncertainty disclosed={bool(result['research'].uncertainty)}")

    put_url = portal._issuer.upload_url(case_id=_CASE, filename="hecvat.pdf")  # noqa: SLF001
    body = b"%PDF-1.4 synthetic HECVAT evidence - safe to delete"
    request = urllib.request.Request(
        put_url,
        data=body,
        method="PUT",
        headers={
            "x-amz-server-side-encryption": "aws:kms",
            "x-amz-server-side-encryption-aws-kms-key-id": config.aws.kms_key_arn or "",
        },
    )
    with urllib.request.urlopen(request) as response:
        print(f"2) vendor drop via presigned PUT -> HTTP {response.status} (KMS-encrypted)")

    record = portal.ingest_upload(
        case_id=_CASE, filename="hecvat.pdf", body=body,
        evidence_type=EvidenceType.HECVAT, vendor="Acme Analytics",
    )
    report = portal.evaluate_gaps(
        case_id=_CASE,
        policy_result=PolicyResult(
            policy_version="2026.07.14-draft",
            risk_route=RiskRoute.MEDIUM,
            required_evidence=["hecvat", "soc2"],
        ),
        evidence=[record],
    )
    print(f"3) gaps -> satisfied={report.satisfied} missing={report.missing} "
          f"human_confirm={report.requires_human_confirmation}")

    import boto3

    boto3.client("s3", region_name=config.aws.region).delete_object(
        Bucket=config.aws.raw_bucket, Key=vendor_upload_key(_CASE, "hecvat.pdf")
    )
    print("cleanup: deleted dropped object")
    print("\nLive vendor-portal flow OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
