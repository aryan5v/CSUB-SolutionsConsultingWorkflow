"""Cases repository: durable case records behind an interface with a fake.

The deployed ``CasesTable`` is keyed by ``case_id`` (string hash key, on-demand,
KMS-encrypted). A case record is a ``ReviewGraphState.to_dict()`` snapshot plus a
few queryable attributes. The snapshot is stored as a single JSON string so
nested structures, empty strings, and numbers round-trip losslessly without
DynamoDB's item-type constraints; ``case_id``/``status``/``updated_at`` are kept
as top-level attributes for lookups and operator visibility.

``boto3`` is imported lazily so the stdlib local slice and CI are unchanged.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import AppConfig


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@runtime_checkable
class CasesRepository(Protocol):
    def put(self, case_id: str, record: dict) -> None:
        """Create or replace the record for ``case_id``."""
        ...

    def get(self, case_id: str) -> dict | None:
        """Return the stored record, or ``None`` if absent."""
        ...

    def exists(self, case_id: str) -> bool: ...


class InMemoryCasesRepository:
    """Deterministic in-memory cases repository for the local slice and tests."""

    def __init__(self) -> None:
        self._items: dict[str, dict] = {}

    def put(self, case_id: str, record: dict) -> None:
        # Deep-copy via JSON round-trip so callers can't mutate stored state.
        self._items[case_id] = json.loads(json.dumps(record, default=str))

    def get(self, case_id: str) -> dict | None:
        item = self._items.get(case_id)
        return json.loads(json.dumps(item)) if item is not None else None

    def exists(self, case_id: str) -> bool:
        return case_id in self._items


class DynamoDbCasesRepository:
    """Amazon DynamoDB implementation over the foundation ``CasesTable``.

    Stores the record as a JSON blob under ``record`` with top-level
    ``case_id``/``status``/``updated_at`` attributes. Writes are idempotent
    replaces keyed by ``case_id``.
    """

    def __init__(
        self,
        *,
        table_name: str,
        region: str,
        client: Any | None = None,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._table = table_name
        self._region = region
        self._client = client
        self._clock = clock

    def _ddb(self) -> Any:
        if self._client is None:
            import boto3  # lazy: only needed when talking to live AWS

            self._client = boto3.client("dynamodb", region_name=self._region)
        return self._client

    def put(self, case_id: str, record: dict) -> None:
        status = str(record.get("status", "unknown"))
        item = {
            "case_id": {"S": case_id},
            "status": {"S": status},
            "updated_at": {"S": self._clock()},
            "record": {"S": json.dumps(record, default=str)},
        }
        self._ddb().put_item(TableName=self._table, Item=item)

    def get(self, case_id: str) -> dict | None:
        response = self._ddb().get_item(
            TableName=self._table, Key={"case_id": {"S": case_id}}
        )
        item = response.get("Item")
        if not item:
            return None
        return json.loads(item["record"]["S"])

    def exists(self, case_id: str) -> bool:
        response = self._ddb().get_item(
            TableName=self._table,
            Key={"case_id": {"S": case_id}},
            ProjectionExpression="case_id",
        )
        return "Item" in response


def build_cases_repository(config: AppConfig) -> CasesRepository:
    """Composition-root factory: in-memory locally, DynamoDB on AWS."""
    if config.use_local_fakes:
        return InMemoryCasesRepository()
    if not config.aws.cases_table:
        raise ValueError("CASES_TABLE is required when USE_LOCAL_FAKES=false")
    return DynamoDbCasesRepository(
        table_name=config.aws.cases_table,
        region=config.aws.region,
    )
