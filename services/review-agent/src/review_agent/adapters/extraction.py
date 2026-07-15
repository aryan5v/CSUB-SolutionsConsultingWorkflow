"""Evidence field extraction behind an interface with a deterministic fake.

Extraction pulls dates, coverages, and authority strings out of untrusted
evidence text so the deterministic validator (``evidence/validation.py``) can
check them. Per the FR-5 trust boundary a model may *extract* fields; it may
never decide pass/fail, set thresholds, or mark a document as received — those
decisions stay in deterministic code.

The deterministic extractor is the default locally and in CI. The live
implementation uses the configured Bedrock extraction profile through the same
structured-output contract as the specialists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .model import ModelClient, invoke_structured

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import AppConfig

# Fields the validator understands. Anything else an extractor returns is
# dropped so untrusted document text cannot smuggle arbitrary keys downstream.
EXTRACTED_DATE_FIELDS = ("issued_date", "expires_date", "report_date", "assessment_date")
EXTRACTED_TEXT_FIELDS = ("authority",)


@runtime_checkable
class EvidenceExtractor(Protocol):
    def extract_fields(
        self, *, filename: str, content_type: str, evidence_type: str, text: str
    ) -> dict:
        """Return ``{coverages: [str], issued_date, expires_date, ...}`` (all optional)."""
        ...


def _clean_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {"coverages": []}
    raw_coverages = candidate.get("coverages")
    if isinstance(raw_coverages, list):
        fields["coverages"] = [
            item.strip().lower() for item in raw_coverages if isinstance(item, str) and item.strip()
        ]
    for key in EXTRACTED_DATE_FIELDS + EXTRACTED_TEXT_FIELDS:
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            fields[key] = value.strip()
    return fields


class DeterministicEvidenceExtractor:
    """Stdlib ``key: value`` line extraction for the local slice and CI.

    A pure function of the document text: no model, no network. Lines like
    ``expires_date: 2026-06-30`` populate the known fields; a ``coverage:``
    line (comma-separated) or a plain "cyber liability" mention populates
    coverages.
    """

    def extract_fields(
        self, *, filename: str, content_type: str, evidence_type: str, text: str
    ) -> dict:
        candidate: dict[str, Any] = {"coverages": []}
        for line in text.splitlines():
            key, separator, value = line.partition(":")
            if not separator:
                continue
            key = key.strip().lower().replace(" ", "_").replace("-", "_")
            value = value.strip()
            if not value:
                continue
            if key in EXTRACTED_DATE_FIELDS + EXTRACTED_TEXT_FIELDS:
                candidate[key] = value
            elif key in {"coverage", "coverages"}:
                candidate["coverages"].extend(
                    part.strip() for part in value.split(",") if part.strip()
                )
        if "cyber liability" in text.lower():
            candidate["coverages"].append("cyber liability")
        return _clean_fields(candidate)


class ModelEvidenceExtractor:
    """Bedrock-backed extraction (cheap extraction profile, e.g. Nova Lite).

    The document text travels as fenced untrusted context; the reply must be a
    structured object whose ``fields`` are then filtered to the known keys.
    """

    _SYSTEM = (
        "You extract metadata fields from one vendor evidence document. You may "
        "only extract; you must not judge validity, set thresholds, or approve "
        "anything. Return JSON with a 'fields' object using only these keys: "
        "coverages (list of strings), issued_date, expires_date, report_date, "
        "assessment_date, authority (ISO dates where possible). Include an "
        "'uncertainty' string describing anything unreadable."
    )

    def __init__(self, model: ModelClient) -> None:
        self._model = model

    def extract_fields(
        self, *, filename: str, content_type: str, evidence_type: str, text: str
    ) -> dict:
        result = invoke_structured(
            self._model,
            system=self._SYSTEM,
            prompt=(
                f"Extract the metadata fields from this {evidence_type} document "
                f"({filename}, {content_type})."
            ),
            context={"task": f"extract.{evidence_type}", "document_text": text},
            required_keys=("fields", "uncertainty"),
        )
        fields = result.get("fields")
        return _clean_fields(fields if isinstance(fields, dict) else {})


def build_evidence_extractor(config: AppConfig) -> EvidenceExtractor:
    """Deterministic extractor locally/CI; Bedrock extraction profile on AWS."""
    if config.use_local_fakes or not config.model.extraction_model_id:
        return DeterministicEvidenceExtractor()
    from .model import BedrockModelClient

    return ModelEvidenceExtractor(
        BedrockModelClient(
            model_id=config.model.extraction_model_id,
            region=config.aws.region,
            guardrail_id=config.model.guardrail_id,
            max_tokens=config.model.max_tokens,
        )
    )
