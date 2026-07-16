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

import re
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .model import ModelClient, invoke_structured

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import AppConfig

# Fields the validator understands. Anything else an extractor returns is
# dropped so untrusted document text cannot smuggle arbitrary keys downstream.
EXTRACTED_DATE_FIELDS = ("issued_date", "expires_date", "report_date", "assessment_date")
EXTRACTED_TEXT_FIELDS = ("authority", "vendor", "product")
EXTRACTION_COORDINATES_FIELD = "_source_coordinates"

# A "cyber liability" mention negated on the same line ("NOT COVERED",
# "EXCLUDED") is absence of coverage, not coverage.
_NEGATED_MENTION = re.compile(r"excluded|exclusion|not\s+covered|no\s+coverage|none")


@runtime_checkable
class EvidenceExtractor(Protocol):
    def extract_fields(
        self, *, filename: str, content_type: str, evidence_type: str, text: str
    ) -> dict:
        """Return extracted values and optional trusted ``_source_coordinates``."""
        ...


def _clean_fields(
    candidate: dict[str, Any], *, source_coordinates: dict[str, dict[str, int]] | None = None
) -> dict[str, Any]:
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
    if source_coordinates:
        allowed = {"coverages", *EXTRACTED_DATE_FIELDS, *EXTRACTED_TEXT_FIELDS}
        coordinates = {
            key: {"line": coordinate["line"]}
            for key, coordinate in source_coordinates.items()
            if key in allowed
            and isinstance(coordinate, dict)
            and isinstance(coordinate.get("line"), int)
            and not isinstance(coordinate["line"], bool)
            and coordinate["line"] >= 1
            and key in fields
        }
        if coordinates:
            fields[EXTRACTION_COORDINATES_FIELD] = coordinates
    return fields


class DeterministicEvidenceExtractor:
    """Stdlib ``key: value`` line extraction for the local slice and CI.

    A pure function of the document text: no model, no network. Lines like
    ``expires_date: 2026-06-30`` populate the known fields; a ``coverage:``
    line (comma-separated) or a plain "cyber liability" mention populates
    coverages. Every extracted value carries its exact one-based source line.
    """

    def extract_fields(
        self, *, filename: str, content_type: str, evidence_type: str, text: str
    ) -> dict:
        candidate: dict[str, Any] = {"coverages": []}
        coordinates: dict[str, dict[str, int]] = {}
        lines = text.splitlines()
        for line_number, line in enumerate(lines, start=1):
            key, separator, value = line.partition(":")
            if not separator:
                continue
            key = key.strip().lower().replace(" ", "_").replace("-", "_")
            value = value.strip()
            if not value:
                continue
            if key in EXTRACTED_DATE_FIELDS + EXTRACTED_TEXT_FIELDS:
                candidate[key] = value
                coordinates[key] = {"line": line_number}
            elif key in {"coverage", "coverages"}:
                values = [part.strip() for part in value.split(",") if part.strip()]
                if values:
                    candidate["coverages"].extend(values)
                    coordinates.setdefault("coverages", {"line": line_number})
        for line_number, line in enumerate(lines, start=1):
            lowered = line.lower()
            # A negated mention ("Cyber liability: NOT COVERED / EXCLUDED") is
            # absence, not coverage; the validator filters negated entries too.
            if "cyber liability" in lowered and not _NEGATED_MENTION.search(lowered):
                candidate["coverages"].append("cyber liability")
                coordinates.setdefault("coverages", {"line": line_number})
                break
        return _clean_fields(candidate, source_coordinates=coordinates)


class ModelEvidenceExtractor:
    """Bedrock-backed extraction (cheap extraction profile, e.g. Nova Lite).

    The document text travels as fenced untrusted context; the reply must be a
    structured object whose ``fields`` are then filtered to the known keys.
    """

    _SYSTEM = (
        "You extract metadata fields from one vendor evidence document. You may "
        "only extract; you must not judge validity, set thresholds, or approve "
        "anything. Return JSON with a 'fields' object using only these keys: "
        "coverages (list of strings; include only coverages the document states "
        "as present — never coverages it marks excluded or not covered), "
        "issued_date, expires_date, report_date, assessment_date, authority, "
        "vendor, product (ISO dates where possible). Include an 'uncertainty' "
        "string describing anything unreadable."
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
