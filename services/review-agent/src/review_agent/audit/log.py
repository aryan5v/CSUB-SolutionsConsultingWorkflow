"""Structured audit log (sec 7, ENGINEERING observability).

Events are emitted as structured records carrying identifiers, versions,
hashes, latency, and error metadata only. Document bodies, credentials, and
sensitive prompts are never logged. In the local slice events go to stdlib
``logging`` as JSON and to an optional in-memory sink for assertions. Wednesday
routes the same events to CloudWatch and DynamoDB.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable

from ..contracts.audit import ActorType, AuditEvent

_LOGGER = logging.getLogger("review_agent.audit")

# Keys that must never appear in audit detail payloads.
_FORBIDDEN_DETAIL_KEYS = frozenset(
    {"document_body", "body", "content", "prompt", "password", "secret", "token", "credentials"}
)


class InMemoryAuditSink:
    """Collects emitted events for tests and the demo."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)

    def event_types(self) -> list[str]:
        return [e.event_type for e in self.events]


class AuditLog:
    """Emits validated audit events, guarding against sensitive content."""

    def __init__(self, *, sink: InMemoryAuditSink | None = None) -> None:
        self._sink = sink

    def emit(self, event: AuditEvent) -> AuditEvent:
        self._reject_sensitive(event.detail)
        _LOGGER.info(json.dumps(event.to_dict(), sort_keys=True))
        if self._sink is not None:
            self._sink.write(event)
        return event

    def record(
        self,
        *,
        event_id: str,
        event_type: str,
        case_id: str,
        occurred_at: str,
        actor_type: ActorType,
        **kwargs: object,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=event_id,
            event_type=event_type,
            case_id=case_id,
            occurred_at=occurred_at,
            actor_type=actor_type,
            **kwargs,  # type: ignore[arg-type]
        )
        return self.emit(event)

    @staticmethod
    def _reject_sensitive(detail: dict) -> None:
        offenders = _FORBIDDEN_DETAIL_KEYS.intersection(_lower_keys(detail))
        if offenders:
            raise ValueError(
                f"audit detail contains forbidden keys: {sorted(offenders)}"
            )


def _lower_keys(mapping: dict) -> Iterable[str]:
    return (str(k).lower() for k in mapping)
