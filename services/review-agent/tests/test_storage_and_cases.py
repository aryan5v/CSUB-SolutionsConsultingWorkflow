"""S3Storage and DynamoDb/InMemory cases repository tests.

No network and no boto3: fake S3 and DynamoDB clients are injected so these run
in the stdlib-only CI gate. They cover SSE-KMS put shaping, get/exists behavior
(including the not-found path), lossless JSON round-tripping of a case snapshot,
and the config-driven factories.
"""

from __future__ import annotations

import hashlib
import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.cases_repository import (
    DynamoDbCasesRepository,
    InMemoryCasesRepository,
    build_cases_repository,
)
from review_agent.adapters.storage import (
    InMemoryStorage,
    S3Storage,
    build_storage,
)
from review_agent.config import AppConfig, AwsConfig


class _FakeS3:
    """Minimal S3 stand-in that records put args and simulates head/get."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.last_put: dict | None = None

    def put_object(self, **kwargs):
        self.last_put = kwargs
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {}

    def get_object(self, *, Bucket, Key):  # noqa: N803 - boto3 kwarg names
        class _Body:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

        return {"Body": _Body(self.objects[Key])}

    def head_object(self, *, Bucket, Key):  # noqa: N803 - boto3 kwarg names
        if Key not in self.objects:
            raise _ClientError({"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}})
        return {}


class _ClientError(Exception):
    """Duck-typed botocore.ClientError: carries a ``response`` dict."""

    def __init__(self, response: dict) -> None:
        super().__init__("client error")
        self.response = response


class S3StorageTests(unittest.TestCase):
    def test_put_enforces_sse_kms_and_returns_sha256(self) -> None:
        fake = _FakeS3()
        storage = S3Storage(
            bucket="raw-bucket",
            region="us-west-2",
            kms_key_id="arn:aws:kms:us-west-2:000000000000:key/abc",
            client=fake,
        )
        body = b"hello evidence"
        digest = storage.put_object(key="raw/x/hash/file.txt", body=body)
        self.assertEqual(digest, hashlib.sha256(body).hexdigest())
        self.assertEqual(fake.last_put["ServerSideEncryption"], "aws:kms")
        self.assertEqual(fake.last_put["SSEKMSKeyId"], "arn:aws:kms:us-west-2:000000000000:key/abc")

    def test_round_trip_get(self) -> None:
        fake = _FakeS3()
        storage = S3Storage(bucket="b", region="r", client=fake)
        storage.put_object(key="k", body=b"data")
        self.assertEqual(storage.get_object(key="k"), b"data")

    def test_exists_true_and_false(self) -> None:
        fake = _FakeS3()
        storage = S3Storage(bucket="b", region="r", client=fake)
        storage.put_object(key="present", body=b"x")
        self.assertTrue(storage.exists(key="present"))
        self.assertFalse(storage.exists(key="absent"))

    def test_exists_reraises_non_404(self) -> None:
        fake = _FakeS3()

        def boom(**kwargs):
            raise _ClientError({"Error": {"Code": "AccessDenied"}, "ResponseMetadata": {"HTTPStatusCode": 403}})

        fake.head_object = boom
        storage = S3Storage(bucket="b", region="r", client=fake)
        with self.assertRaises(_ClientError):
            storage.exists(key="anything")


class _FakeDynamo:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def put_item(self, *, TableName, Item):  # noqa: N803 - boto3 kwarg names
        self.items[Item["case_id"]["S"]] = Item

    def get_item(self, *, TableName, Key, **kwargs):  # noqa: N803 - boto3 kwarg names
        item = self.items.get(Key["case_id"]["S"])
        return {"Item": item} if item is not None else {}


class CasesRepositoryTests(unittest.TestCase):
    _SNAPSHOT = {
        "case_id": "CASE-1",
        "status": "awaiting_review",
        "policy_result": {"risk_route": "medium", "escalated": False},
        "citations": [],
        "notes": "",  # empty string must survive
    }

    def test_dynamodb_put_get_round_trip_is_lossless(self) -> None:
        fake = _FakeDynamo()
        repo = DynamoDbCasesRepository(
            table_name="CasesTable", region="us-west-2", client=fake, clock=lambda: "T0"
        )
        repo.put("CASE-1", self._SNAPSHOT)
        stored = fake.items["CASE-1"]
        self.assertEqual(stored["status"]["S"], "awaiting_review")
        self.assertEqual(stored["updated_at"]["S"], "T0")
        self.assertEqual(repo.get("CASE-1"), self._SNAPSHOT)

    def test_dynamodb_get_missing_returns_none(self) -> None:
        repo = DynamoDbCasesRepository(table_name="t", region="r", client=_FakeDynamo())
        self.assertIsNone(repo.get("nope"))
        self.assertFalse(repo.exists("nope"))

    def test_in_memory_repo_isolates_stored_state(self) -> None:
        repo = InMemoryCasesRepository()
        record = {"case_id": "C", "status": "policy"}
        repo.put("C", record)
        record["status"] = "mutated"
        self.assertEqual(repo.get("C")["status"], "policy")
        self.assertTrue(repo.exists("C"))


class FactoryTests(unittest.TestCase):
    def test_storage_factory_local_vs_aws(self) -> None:
        self.assertIsInstance(build_storage(AppConfig(use_local_fakes=True)), InMemoryStorage)
        aws = AppConfig(use_local_fakes=False, aws=AwsConfig(raw_bucket="raw-b"))
        self.assertIsInstance(build_storage(aws), S3Storage)

    def test_storage_factory_requires_bucket_in_aws_mode(self) -> None:
        with self.assertRaises(ValueError):
            build_storage(AppConfig(use_local_fakes=False, aws=AwsConfig(raw_bucket=None)))

    def test_cases_factory_local_vs_aws(self) -> None:
        self.assertIsInstance(
            build_cases_repository(AppConfig(use_local_fakes=True)), InMemoryCasesRepository
        )
        aws = AppConfig(use_local_fakes=False, aws=AwsConfig(cases_table="CasesTable"))
        self.assertIsInstance(build_cases_repository(aws), DynamoDbCasesRepository)

    def test_cases_factory_requires_table_in_aws_mode(self) -> None:
        with self.assertRaises(ValueError):
            build_cases_repository(AppConfig(use_local_fakes=False, aws=AwsConfig(cases_table=None)))


if __name__ == "__main__":
    unittest.main()
