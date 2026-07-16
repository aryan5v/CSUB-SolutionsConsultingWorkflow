"""Structured metrics emission (PRD sec 6/7, issue #50).

Emits CloudWatch Embedded Metric Format (EMF) JSON lines via the standard
``logging`` module. CloudWatch Logs parses EMF automatically once the process
runs under Lambda/ECS with a subscribed log group, so this needs no
``PutMetricData`` calls, no extra IAM permissions, and no live AWS dependency
in the local slice (mirrors ``audit/log.py``'s stdlib-logging-first design).

Only low-cardinality fields (workflow step, model label, profile version,
workflow version) are CloudWatch *dimensions*. Per-case/run/correlation
identifiers are EMF *properties*: they still appear in the log line for
correlation, but keeping them out of ``Dimensions`` avoids multiplying
CloudWatch metric-stream cardinality (and cost) per case.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable

_LOGGER = logging.getLogger("review_agent.metrics")

_NAMESPACE = "ReviewAgent"

# Same guard as audit/log.py: metric properties must never carry prompts,
# document bodies, or credentials (AGENTS.md, PRD sec 7).
_FORBIDDEN_KEYS = frozenset(
    {"document_body", "body", "content", "prompt", "password", "secret", "token", "credentials"}
)


@runtime_checkable
class MetricsEmitter(Protocol):
    def emit(
        self,
        name: str,
        value: float,
        *,
        unit: str = "None",
        dimensions: Mapping[str, str] | None = None,
        properties: Mapping[str, object] | None = None,
    ) -> None: ...


def _reject_sensitive(detail: Mapping[str, object]) -> None:
    offenders = _FORBIDDEN_KEYS.intersection(str(k).lower() for k in detail)
    if offenders:
        raise ValueError(f"metric properties contain forbidden keys: {sorted(offenders)}")


class NullMetricsEmitter:
    """No-op emitter: the default when a caller doesn't wire observability."""

    def emit(
        self,
        name: str,
        value: float,
        *,
        unit: str = "None",
        dimensions: Mapping[str, str] | None = None,
        properties: Mapping[str, object] | None = None,
    ) -> None:
        return None


class InMemoryMetricsSink:
    """Collects emitted metrics for tests and the demo."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def emit(
        self,
        name: str,
        value: float,
        *,
        unit: str = "None",
        dimensions: Mapping[str, str] | None = None,
        properties: Mapping[str, object] | None = None,
    ) -> None:
        _reject_sensitive(properties or {})
        self.records.append(
            {
                "name": name,
                "value": value,
                "unit": unit,
                "dimensions": dict(dimensions or {}),
                "properties": dict(properties or {}),
            }
        )

    def values_for(self, name: str) -> list[float]:
        return [r["value"] for r in self.records if r["name"] == name]

    def names(self) -> list[str]:
        return [r["name"] for r in self.records]


class EmbeddedMetricsEmitter:
    """Writes one CloudWatch EMF JSON line per metric via stdlib ``logging``."""

    def __init__(
        self, *, namespace: str = _NAMESPACE, clock: Callable[[], float] = time.time
    ) -> None:
        self._namespace = namespace
        self._clock = clock

    def emit(
        self,
        name: str,
        value: float,
        *,
        unit: str = "None",
        dimensions: Mapping[str, str] | None = None,
        properties: Mapping[str, object] | None = None,
    ) -> None:
        dims = dict(dimensions or {})
        props = dict(properties or {})
        _reject_sensitive(props)
        document = {
            "_aws": {
                "Timestamp": int(self._clock() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": self._namespace,
                        "Dimensions": [list(dims.keys())],
                        "Metrics": [{"Name": name, "Unit": unit}],
                    }
                ],
            },
            **dims,
            **props,
            name: value,
        }
        _LOGGER.info(json.dumps(document, sort_keys=True, default=str))
