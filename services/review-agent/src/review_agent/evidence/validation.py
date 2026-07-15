"""Deterministic content checks for COI, penetration-test, and PCI evidence.

Thresholds live here in code with source citations, never in a model. The
customer ask (2026-07-15 feedback call, recorded as issue #36) defines the
three checks:

- **COI**: cyber-liability coverage must be listed and the policy unexpired.
- **Penetration test**: flag a report older than one year.
- **PCI attestation (AoC)**: must be current; AoCs are validated annually, so
  older than one year is stale.

A model (or the deterministic extractor) may only *extract* the fields checked
here; pass/fail is decided by these pure functions (AGENTS.md AI trust
boundaries). Only failures are reported — a document with no failures simply
covers its requirement.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

# Source citation attached to every finding these rules produce.
RULE_SOURCE = {
    "source_id": "issue:36",
    "section": "customer-feedback-call-2026-07-15",
}

PENTEST_MAX_AGE_DAYS = 365  # issue #36: "flag if older than 1 year"
PCI_MAX_AGE_DAYS = 365  # issue #36: AoC must be current; AoCs are annual

# Post-approval monitoring (issue #53) derives next-check dates from the same
# validated fields these rules check — never from unvalidated metadata.
EXPIRY_RULE_SOURCE = {
    "source_id": "issue:53",
    "section": "expiring-evidence-monitoring",
}

_NORMALIZE = re.compile(r"[^a-z0-9]+")

# Ordered so the most specific token set wins; matching is a deterministic
# filename/content-type heuristic like the coverage matcher, not a model.
_TYPE_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("coi", ("certificateofinsurance", "cyberliability", "coi", "insurance")),
    ("pentest", ("penetrationtest", "pentest")),
    ("pci", ("attestationofcompliance", "pciaoc", "pcidss", "aoc", "pci")),
)


def classify_evidence_type(filename: str, content_type: str = "") -> str | None:
    """Return 'coi' | 'pentest' | 'pci' when the artifact looks like one, else None."""
    haystack = _NORMALIZE.sub("", f"{filename} {content_type}".lower())
    for evidence_type, tokens in _TYPE_TOKENS:
        if any(token in haystack for token in tokens):
            return evidence_type
    return None


def _parse_date(value: object) -> datetime.date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def compute_expires_on(evidence_type: str, fields: dict[str, Any]) -> datetime.date | None:
    """Derive when a validated document stops being current (issue #53).

    COI carries its own policy expiration; penetration tests and PCI AoCs are
    current for one year from their report/assessment date (the same windows
    ``validate_evidence`` enforces at intake). Returns ``None`` when no
    validated date exists — such documents cannot be monitored.
    """
    if evidence_type == "coi":
        return _parse_date(fields.get("expires_date"))
    if evidence_type == "pentest":
        base = _parse_date(fields.get("report_date")) or _parse_date(fields.get("issued_date"))
        return base + datetime.timedelta(days=PENTEST_MAX_AGE_DAYS) if base else None
    if evidence_type == "pci":
        base = _parse_date(fields.get("assessment_date")) or _parse_date(
            fields.get("issued_date")
        )
        return base + datetime.timedelta(days=PCI_MAX_AGE_DAYS) if base else None
    return None


def validate_evidence(
    *, evidence_type: str, fields: dict[str, Any], today: datetime.date
) -> list[dict[str, str]]:
    """Return the failed checks (``{check, reason}``) for one artifact."""
    failures: list[dict[str, str]] = []
    if evidence_type == "coi":
        coverages = [str(item).lower() for item in fields.get("coverages") or []]
        if not any("cyber" in coverage for coverage in coverages):
            failures.append(
                {
                    "check": "coi.cyber_liability_missing",
                    "reason": "Certificate of insurance does not list cyber-liability coverage.",
                }
            )
        expires = _parse_date(fields.get("expires_date"))
        if expires is None:
            failures.append(
                {
                    "check": "coi.expiry_unknown",
                    "reason": "No readable policy expiration date was found on the certificate.",
                }
            )
        elif expires < today:
            failures.append(
                {
                    "check": "coi.expired",
                    "reason": f"Insurance policy expired {expires.isoformat()}.",
                }
            )
    elif evidence_type == "pentest":
        report = _parse_date(fields.get("report_date")) or _parse_date(fields.get("issued_date"))
        if report is None:
            failures.append(
                {
                    "check": "pentest.date_unknown",
                    "reason": "No readable report date was found on the penetration test.",
                }
            )
        elif (today - report).days > PENTEST_MAX_AGE_DAYS:
            failures.append(
                {
                    "check": "pentest.stale",
                    "reason": (
                        f"Penetration test report dated {report.isoformat()} is older "
                        f"than one year."
                    ),
                }
            )
    elif evidence_type == "pci":
        assessed = _parse_date(fields.get("assessment_date")) or _parse_date(
            fields.get("issued_date")
        )
        if assessed is None:
            failures.append(
                {
                    "check": "pci.date_unknown",
                    "reason": "No readable assessment date was found on the PCI attestation.",
                }
            )
        elif (today - assessed).days > PCI_MAX_AGE_DAYS:
            failures.append(
                {
                    "check": "pci.stale",
                    "reason": (
                        f"PCI attestation of compliance dated {assessed.isoformat()} is "
                        f"no longer current (older than one year)."
                    ),
                }
            )
    return failures
