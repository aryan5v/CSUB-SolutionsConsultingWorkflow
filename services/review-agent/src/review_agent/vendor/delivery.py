"""Provider-neutral delivery claim/outbox primitives.

A claim is durable before a side effect is attempted.  Providers must make
``claim`` and ``settle`` conditional atomic operations so independent workers
cannot both deliver the same cadence item or settle another worker's attempt.
"""

from __future__ import annotations

import copy
import threading
from typing import Protocol, runtime_checkable

from ..contracts.vendor import ReminderClaim


@runtime_checkable
class DeliveryClaimStore(Protocol):
    """Durable outbox claim store for bounded-attempt external deliveries."""

    def get(
        self, *, workspace_id: str, dedupe_key: str
    ) -> ReminderClaim | None: ...

    def claim(
        self,
        *,
        workspace_id: str,
        dedupe_key: str,
        case_id: str,
        invite_id: str,
        claimed_at: str,
        max_attempts: int,
    ) -> ReminderClaim | None:
        """Atomically create/reclaim a pending attempt, or return ``None``."""
        ...

    def settle(
        self,
        *,
        workspace_id: str,
        dedupe_key: str,
        attempts: int,
        status: str,
    ) -> bool:
        """Atomically settle the matching pending attempt as sent or failed."""
        ...


class InMemoryDeliveryClaimStore:
    """Deterministic, process-safe claim store used by local APIs and tests."""

    def __init__(self) -> None:
        self._claims: dict[tuple[str, str], ReminderClaim] = {}
        self._lock = threading.Lock()

    def get(self, *, workspace_id: str, dedupe_key: str) -> ReminderClaim | None:
        with self._lock:
            claim = self._claims.get((workspace_id, dedupe_key))
            return copy.deepcopy(claim)

    def claim(
        self,
        *,
        workspace_id: str,
        dedupe_key: str,
        case_id: str,
        invite_id: str,
        claimed_at: str,
        max_attempts: int,
    ) -> ReminderClaim | None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        key = (workspace_id, dedupe_key)
        with self._lock:
            current = self._claims.get(key)
            if current is not None and (
                current.status != "failed" or current.attempts >= max_attempts
            ):
                return None
            claim = ReminderClaim(
                dedupe_key=dedupe_key,
                case_id=case_id,
                invite_id=invite_id,
                status="pending",
                attempts=(current.attempts if current is not None else 0) + 1,
                claimed_at=claimed_at,
                workspace_id=workspace_id,
            )
            self._claims[key] = claim
            return copy.deepcopy(claim)

    def settle(
        self,
        *,
        workspace_id: str,
        dedupe_key: str,
        attempts: int,
        status: str,
    ) -> bool:
        if status not in {"sent", "failed"}:
            raise ValueError("delivery claim status must be sent or failed")
        key = (workspace_id, dedupe_key)
        with self._lock:
            current = self._claims.get(key)
            if (
                current is None
                or current.status != "pending"
                or current.attempts != attempts
            ):
                return False
            self._claims[key] = ReminderClaim(
                dedupe_key=current.dedupe_key,
                case_id=current.case_id,
                invite_id=current.invite_id,
                status=status,
                attempts=current.attempts,
                claimed_at=current.claimed_at,
                workspace_id=current.workspace_id,
            )
            return True
