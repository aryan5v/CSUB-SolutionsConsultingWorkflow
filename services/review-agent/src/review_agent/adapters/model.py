"""Model adapter: a small interface over Bedrock with a deterministic local fake.

Provider SDK calls stay behind this interface so the workflow is testable
without live AWS (AGENTS.md). The model may extract, summarize, compare, and
draft; it may not establish rules, change risk tiers, confirm fuzzy matches, or
approve anything (FR-5 trust boundary). Callers enforce structured outputs.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelClient(Protocol):
    """Structured-output model boundary.

    ``complete_json`` returns a dict validated by the caller against a contract
    schema. Implementations must not perform tool calls or writes on their own.
    """

    def complete_json(self, *, system: str, prompt: str, context: dict) -> dict: ...


class DeterministicModelClient:
    """Local fake that returns deterministic structured output for tests.

    Behavior is a pure function of the prompt/context so gold cases are stable.
    It never reaches the network. This is the default in the Tuesday slice and
    in CI (``USE_LOCAL_FAKES`` default true).
    """

    def __init__(self, canned: dict[str, dict] | None = None) -> None:
        self._canned = canned or {}

    def complete_json(self, *, system: str, prompt: str, context: dict) -> dict:
        key = context.get("task", "")
        if key in self._canned:
            return dict(self._canned[key])
        # Deterministic, obviously-synthetic default so nothing is mistaken for
        # a grounded finding without an explicit citation.
        return {
            "task": key,
            "summary": f"[deterministic-fake] {key}",
            "findings": [],
            "citations": [],
            "uncertainty": "local deterministic model; no grounded analysis performed",
        }


class BedrockModelClient:
    """Amazon Bedrock implementation (wired Wednesday).

    Kept as a documented seam so the interface is real now. When enabled it will
    use ``boto3.client("bedrock-runtime").converse(...)`` with the pinned
    inference-profile ID from ``AppConfig.model`` and a Bedrock Guardrail, then
    parse a single JSON object from the response. It is intentionally not
    imported or constructed in the local slice.
    """

    def __init__(self, *, model_id: str, region: str, guardrail_id: str | None = None) -> None:
        self._model_id = model_id
        self._region = region
        self._guardrail_id = guardrail_id

    def complete_json(self, *, system: str, prompt: str, context: dict) -> dict:  # pragma: no cover - Wednesday
        raise NotImplementedError(
            "BedrockModelClient is wired during Wednesday AWS integration. Use "
            "DeterministicModelClient for the local slice."
        )

    @staticmethod
    def _parse_single_json_object(text: str) -> dict:  # pragma: no cover - Wednesday
        return json.loads(text)
