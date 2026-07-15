"""Checkpointer boundary for durable pause/resume (PRD sec 5).

The local slice checkpoints ``ReviewGraphState`` snapshots in memory. Wednesday
binds this interface to a LangGraph checkpointer backed by AgentCore Memory with
a seven-day TTL. Snapshots are plain dicts so they serialize identically in both.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


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
