"""Normalize supplied institutional sources into traceable metadata records.

A record keeps the source's classification, a citation locator, extraction
warnings, and any untrusted-content findings. It intentionally does not carry
document bodies. A content hash is optional: it is computed from real bytes only
at runtime and is never committed, so nothing tied to downloadable contents
lands in Git (AGENTS.md, PRD sec 1 and sec 7).

The corpus result keeps institutional policy and case/vendor evidence in
separate collections and refuses to let a draft, example, or unresolved source
be activated.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from ..contracts.common import SourceCoordinates
from .classification import (
    Classification,
    ConfirmationStatus,
    CorpusMembership,
    classify,
)
from .untrusted import UntrustedFinding, scan_untrusted_text


class ActivationBlockedError(RuntimeError):
    """Raised when a non-activatable source is asked to be activated."""


def _basename(relative_path: str) -> str:
    parts = [p for p in relative_path.replace("\\", "/").split("/") if p]
    return parts[-1] if parts else relative_path


@dataclass(slots=True)
class InstitutionalSourceRecord:
    source_id: str
    filename: str
    relative_path: str
    mime_type: str
    classification: Classification
    locator: SourceCoordinates
    sha256: str | None = None
    version: str | None = None
    ingested_at: str | None = None
    extraction_warnings: list[str] = field(default_factory=list)
    untrusted_findings: list[UntrustedFinding] = field(default_factory=list)

    @property
    def activatable(self) -> bool:
        return self.classification.activation_allowed

    @property
    def is_institutional_policy(self) -> bool:
        return self.classification.is_institutional_policy

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "filename": self.filename,
            "relative_path": self.relative_path,
            "mime_type": self.mime_type,
            "classification": self.classification.to_dict(),
            "locator": self.locator.to_dict(),
            "sha256": self.sha256,
            "version": self.version,
            "ingested_at": self.ingested_at,
            "extraction_warnings": list(self.extraction_warnings),
            "untrusted_findings": [f.to_dict() for f in self.untrusted_findings],
        }


def normalize_source(
    *,
    source_id: str,
    relative_path: str,
    mime_type: str,
    filename: str | None = None,
    text: str | None = None,
    sha256: str | None = None,
    version: str | None = None,
    ingested_at: str | None = None,
    extra_warnings: Iterable[str] | None = None,
) -> InstitutionalSourceRecord:
    """Normalize one source into a record.

    ``text`` is optional already-extracted text used only for the untrusted
    scan; embedded instructions are flagged, never obeyed. ``sha256`` is
    optional and, when supplied, is treated as runtime-only metadata.
    """

    filename = filename or _basename(relative_path)
    classification = classify(relative_path)
    warnings: list[str] = list(classification.notes)
    if extra_warnings:
        warnings.extend(extra_warnings)

    findings = scan_untrusted_text(text)
    if any(f.kind == "tracking_url" for f in findings):
        warnings.append(
            "untrusted: tracking/AI-provenance URL (chatgpt.com) present; "
            "provenance suspect, not treated as authoritative and not fetched"
        )
    if any(f.kind == "prompt_injection" for f in findings):
        warnings.append("untrusted: embedded instruction detected and ignored")

    locator = SourceCoordinates(
        source_id=source_id,
        filename=filename,
        version=version,
        sha256=sha256,
    )

    return InstitutionalSourceRecord(
        source_id=source_id,
        filename=filename,
        relative_path=relative_path,
        mime_type=mime_type,
        classification=classification,
        locator=locator,
        sha256=sha256,
        version=version,
        ingested_at=ingested_at,
        extraction_warnings=warnings,
        untrusted_findings=findings,
    )


@dataclass(slots=True)
class CorpusNormalizationResult:
    records: list[InstitutionalSourceRecord] = field(default_factory=list)

    def institutional_policy(self) -> list[InstitutionalSourceRecord]:
        return [r for r in self.records if r.is_institutional_policy]

    def case_vendor_evidence(self) -> list[InstitutionalSourceRecord]:
        return [
            r
            for r in self.records
            if r.classification.membership is CorpusMembership.CASE_VENDOR_EVIDENCE
        ]

    def excluded(self) -> list[InstitutionalSourceRecord]:
        return [
            r
            for r in self.records
            if r.classification.membership is CorpusMembership.EXCLUDED
        ]

    def unresolved(self) -> list[InstitutionalSourceRecord]:
        return [
            r
            for r in self.records
            if r.classification.membership is CorpusMembership.UNRESOLVED
        ]

    def activatable(self) -> list[InstitutionalSourceRecord]:
        return [r for r in self.records if r.activatable]

    def flagged(self) -> list[InstitutionalSourceRecord]:
        return [r for r in self.records if r.untrusted_findings]

    def drafts(self) -> list[InstitutionalSourceRecord]:
        return [
            r
            for r in self.records
            if r.classification.status is ConfirmationStatus.DRAFT_UNCONFIRMED
        ]

    def assert_scope_separation(self) -> None:
        """Fail loudly if policy and evidence scopes have leaked into each other."""

        from ..contracts.common import CitationScope

        for record in self.institutional_policy():
            if record.classification.retrieval_scope is CitationScope.CASE_EVIDENCE:
                raise ValueError(
                    f"scope leak: institutional-policy source {record.source_id} "
                    "carries the case-evidence retrieval scope"
                )
        for record in self.case_vendor_evidence():
            if record.is_institutional_policy:
                raise ValueError(
                    f"scope leak: case/vendor source {record.source_id} "
                    "is marked institutional policy"
                )

    def summary(self) -> dict:
        """Counts only. No filenames, bodies, or hashes."""

        return {
            "total": len(self.records),
            "institutional_policy": len(self.institutional_policy()),
            "case_vendor_evidence": len(self.case_vendor_evidence()),
            "excluded": len(self.excluded()),
            "unresolved": len(self.unresolved()),
            "activatable": len(self.activatable()),
            "drafts": len(self.drafts()),
            "flagged_untrusted": len(self.flagged()),
        }

    def to_dict(self) -> dict:
        return {"records": [r.to_dict() for r in self.records]}


def normalize_corpus(entries: Iterable[Mapping[str, object]]) -> CorpusNormalizationResult:
    """Normalize many sources.

    Each entry needs ``source_id``, ``relative_path``, and ``mime_type``; it may
    also carry ``text``, ``sha256``, ``version``, ``ingested_at``, and
    ``extra_warnings``. The result is validated for scope separation before it
    is returned.
    """

    records: list[InstitutionalSourceRecord] = []
    for entry in entries:
        records.append(
            normalize_source(
                source_id=str(entry["source_id"]),
                relative_path=str(entry["relative_path"]),
                mime_type=str(entry["mime_type"]),
                filename=entry.get("filename"),  # type: ignore[arg-type]
                text=entry.get("text"),  # type: ignore[arg-type]
                sha256=entry.get("sha256"),  # type: ignore[arg-type]
                version=entry.get("version"),  # type: ignore[arg-type]
                ingested_at=entry.get("ingested_at"),  # type: ignore[arg-type]
                extra_warnings=entry.get("extra_warnings"),  # type: ignore[arg-type]
            )
        )
    result = CorpusNormalizationResult(records=records)
    result.assert_scope_separation()
    return result


def assert_activatable(record: InstitutionalSourceRecord) -> None:
    """Raise ``ActivationBlockedError`` unless the source may be activated.

    Draft/unconfirmed decision trees, evidence examples, the signed TAAP, and
    unresolved sources are all blocked here. Activation stays a human decision.
    """

    if not record.classification.activation_allowed:
        raise ActivationBlockedError(
            f"source {record.source_id} ({record.classification.status.value}) "
            f"is not activatable: {record.classification.reason}"
        )
