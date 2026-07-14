"""Checkpointer boundary for durable pause/resume (PRD sec 5).

The local slice checkpoints ``ReviewGraphState`` snapshots in memory. AWS
integration binds this interface to a durable store so a case can pause at a
human interrupt and resume in a later process. Snapshots are plain dicts so they
serialize identically across every implementation.

Durability today is DynamoDB (``DynamoDbCheckpointer``), backed by the deployed
``CasesTable``. AgentCore Memory (``AgentCoreMemoryCheckpointer``) is kept as a
documented seam: the camp sandbox denies AgentCore control-plane calls
(``ListMemories`` -> ``AccessDeniedException`` under the ISB SCP), and a Memory
resource must be provisioned with IAM before it can be wired.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..adapters.cases_repository import CasesRepository
    from ..config import AppConfig


@runtime_checkable
class Checkpointer(Protocol):
    def save(self, case_id: str, snapshot: dict) -> None: ...

    def load(self, case_id: str) -> dict | None: ...


class InMemoryCheckpointer:
    def __init__(self) -> None:
        self._snapshots: dict[str, dict] = {}

    def save(self, case_id: str, snapshot: dict) -> None:
        self._snapshots[case_id] = snapshot

    def load(self, case_id: str) -> dict | None:
        return self._snapshots.get(case_id)

    def has(self, case_id: str) -> bool:
        return case_id in self._snapshots


class DynamoDbCheckpointer:
    """Durable checkpointer backed by the deployed ``CasesTable``.

    Delegates to a ``CasesRepository`` so a case's ``ReviewGraphState`` snapshot
    is persisted, KMS-encrypted, keyed by ``case_id`` — one durable record per
    case that survives process restarts for pause/resume across human interrupts.
    """

    def __init__(self, repository: CasesRepository) -> None:
        self._repository = repository

    def save(self, case_id: str, snapshot: dict) -> None:
        self._repository.put(case_id, snapshot)

    def load(self, case_id: str) -> dict | None:
        return self._repository.get(case_id)

    def has(self, case_id: str) -> bool:
        return self._repository.exists(case_id)


class AgentCoreMemoryCheckpointer:
    """Amazon Bedrock AgentCore Memory checkpointer (documented seam).

    Intended to store snapshots as AgentCore Memory events with a seven-day TTL
    (PRD sec 5). Not wired: the camp sandbox denies AgentCore control-plane calls
    (``ListMemories`` -> ``AccessDeniedException`` under the ISB SCP), so no
    Memory resource can be provisioned here yet. Kept as a real interface so
    swapping it in later is a factory change once IAM/provisioning is approved.
    """

    def __init__(self, *, memory_id: str, region: str) -> None:
        self._memory_id = memory_id
        self._region = region

    def save(self, case_id: str, snapshot: dict) -> None:  # pragma: no cover - not provisioned
        raise NotImplementedError(
            "AgentCore Memory is not provisioned in the sandbox (ListMemories -> "
            "AccessDeniedException). Use DynamoDbCheckpointer for durable resume."
        )

    def load(self, case_id: str) -> dict | None:  # pragma: no cover - not provisioned
        raise NotImplementedError(
            "AgentCore Memory is not provisioned in the sandbox (ListMemories -> "
            "AccessDeniedException). Use DynamoDbCheckpointer for durable resume."
        )


def build_checkpointer(config: AppConfig) -> Checkpointer:
    """Composition-root factory: in-memory locally, DynamoDB on AWS."""
    if config.use_local_fakes:
        return InMemoryCheckpointer()
    from ..adapters.cases_repository import build_cases_repository

    return DynamoDbCheckpointer(build_cases_repository(config))
