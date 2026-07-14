"""Live S3 + DynamoDB smoke check (manual, not part of CI).

Round-trips a synthetic object through the raw-sources bucket (SSE-KMS enforced)
and a synthetic case record through the CasesTable, then deletes both so it
leaves no litter. Requires AWS credentials with S3 and DynamoDB access to the
foundation resources. It writes only synthetic, non-sensitive data.

    USE_LOCAL_FAKES=false AWS_REGION=us-west-2 \
        RAW_BUCKET=... CASES_TABLE=... DATA_KEY_ARN=... \
        python services/review-agent/scripts/smoke_storage.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from review_agent.adapters.cases_repository import build_cases_repository  # noqa: E402
from review_agent.adapters.storage import build_storage  # noqa: E402
from review_agent.config import AppConfig  # noqa: E402


def main() -> int:
    os.environ.setdefault("USE_LOCAL_FAKES", "false")
    config = AppConfig.from_env()
    if config.use_local_fakes:
        print("USE_LOCAL_FAKES is true; set it to false to exercise live storage.")
        return 1
    if not config.aws.raw_bucket or not config.aws.cases_table:
        print("Set RAW_BUCKET and CASES_TABLE to the foundation resource names.")
        return 1

    import boto3

    key = "smoke/aws-integration/roundtrip.txt"
    case_id = "SMOKE-AWS-0001"
    body = b"synthetic smoke payload - safe to delete"

    storage = build_storage(config)
    digest = storage.put_object(key=key, body=body)
    assert storage.exists(key=key)
    assert storage.get_object(key=key) == body
    assert not storage.exists(key="smoke/does-not-exist")
    print(f"S3 OK  -> sha256 {digest[:16]} | put/get/exists round-trip, SSE-KMS enforced")

    repo = build_cases_repository(config)
    snapshot = {"case_id": case_id, "status": "awaiting_review", "notes": "", "citations": []}
    repo.put(case_id, snapshot)
    assert repo.exists(case_id)
    assert repo.get(case_id) == snapshot
    print("DDB OK -> put/get/exists round-trip, empty string + list preserved")

    boto3.client("s3", region_name=config.aws.region).delete_object(
        Bucket=config.aws.raw_bucket, Key=key
    )
    boto3.client("dynamodb", region_name=config.aws.region).delete_item(
        TableName=config.aws.cases_table, Key={"case_id": {"S": case_id}}
    )
    print("cleanup: deleted test S3 object and DynamoDB item")
    print("\nLive storage smoke OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
