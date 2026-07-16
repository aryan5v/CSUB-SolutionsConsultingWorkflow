"""Deterministic content checks for COI, penetration-test, and PCI evidence.

Thresholds live here in code with source citations, never in a model. The
customer ask (2026-07-15 feedback call, recorded as issue #36) defines the
checks:

- **COI**: cyber-liability coverage must be listed and the policy unexpired
  (confirmed in issue #36's end-user evidence; a required coverage *amount*
  remains TBD and is not checked).
- **Penetration test**: flag a report older than one year (issue #36: "The
  transcript confirms a one-year penetration-test freshness check").
- **PCI attestation (AoC)**: CSUB has not cited an authoritative currency
  rule (issue #36 open question, tracked in issue #52). No freshness
  threshold is executable, so every PCI attestation is routed to explicit
  manual review (``pci.currency_unverified``) instead of passing or failing
  on an invented age limit.

A model (or the deterministic extractor) may only *extract* the fields checked
here; every disposition is decided by these pure functions (AGENTS.md AI trust
boundaries). Each result carries a ``disposition``:

- ``failed`` — a confirmed deterministic rule was violated.
- ``manual_review`` — the document is unverifiable (unreadable dates, TBD
  policy rules, vendor/product mismatch) and needs a human decision.

Only failures/manual-review items are reported — a document with no results
simply covers its requirement.
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

# issue #36: "The transcript confirms a one-year penetration-test freshness check".
PENTEST_MAX_AGE_DAYS = 365

# Post-approval monitoring (issue #53) derives next-check dates from the same
# validated fields these rules check — never from unvalidated metadata.
EXPIRY_RULE_SOURCE = {
    "source_id": "issue:53",
    "section": "expiring-evidence-monitoring",
}

DISPOSITION_FAILED = "failed"
DISPOSITION_MANUAL_REVIEW = "manual_review"

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
_NORMALIZE = re.compile(r"[^a-z0-9]+")

# Coverage entries carrying an explicit negation are absence, not coverage
# ("Cyber liability: NOT COVERED", "cyber liability (excluded)").
_NEGATION = re.compile(r"excluded|exclusion|not\s+covered|no\s+coverage|none")

# Deterministic filename/content-type classification. Short markers ("coi",
# "pci", "aoc") must match a whole token so substrings inside unrelated words
# ("coinbase_soc2.pdf") can never classify; multi-word phrases are matched
# against the token sequence. This is a heuristic like the coverage matcher,
# not a model.
_TYPE_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("coi", ("certificate of insurance", "cyber liability"), ("coi", "insurance")),
    ("pentest", ("penetration test",), ("pentest",)),
    ("pci", ("attestation of compliance", "pci dss", "pci aoc"), ("pci", "aoc")),
)


def classify_evidence_type(filename: str, content_type: str = "") -> str | None:
    """Return 'coi' | 'pentest' | 'pci' when the artifact looks like one, else None."""
    tokens = [token for token in _TOKEN_SPLIT.split(f"{filename} {content_type}".lower()) if token]
    token_set = set(tokens)
    joined = " ".join(tokens)
    for evidence_type, phrases, exact_tokens in _TYPE_RULES:
        for phrase in phrases:
            # "certificate-of-insurance.pdf" and "CertificateOfInsurance.pdf".
            if phrase in joined or phrase.replace(" ", "") in token_set:
                return evidence_type
        if token_set & set(exact_tokens):
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

    Only cited rules produce a date: a COI carries its own policy expiration,
    and penetration tests use the one-year freshness rule cited verbatim in
    issue #36. PCI AoCs have NO authoritative currency rule (issue #36 open
    question; issue #52), so no expiry date is ever computed for them — they
    already route to explicit manual review (``pci.currency_unverified``) at
    intake. Returns ``None`` when no cited rule yields a validated date —
    such documents cannot be scheduled for expiry.
    """
    if evidence_type == "coi":
        return _parse_date(fields.get("expires_date"))
    if evidence_type == "pentest":
        base = _parse_date(fields.get("report_date")) or _parse_date(fields.get("issued_date"))
        return base + datetime.timedelta(days=PENTEST_MAX_AGE_DAYS) if base else None
    # PCI (and anything else) has no cited expiry rule (issue #52): never
    # schedule an expiry date; manual review is the explicit state instead.
    return None


def _result(check: str, reason: str, disposition: str) -> dict[str, str]:
    return {"check": check, "reason": reason, "disposition": disposition}


def validate_evidence(
    *, evidence_type: str, fields: dict[str, Any], today: datetime.date
) -> list[dict[str, str]]:
    """Return the failed/manual-review checks (``{check, reason, disposition}``)."""
    failures: list[dict[str, str]] = []
    if evidence_type == "coi":
        coverages = [str(item).lower() for item in fields.get("coverages") or []]
        positive = [item for item in coverages if not _NEGATION.search(item)]
        if not any("cyber" in coverage for coverage in positive):
            failures.append(
                _result(
                    "coi.cyber_liability_missing",
                    "Certificate of insurance does not list cyber-liability coverage.",
                    DISPOSITION_FAILED,
                )
            )
        expires = _parse_date(fields.get("expires_date"))
        if expires is None:
            failures.append(
                _result(
                    "coi.expiry_unknown",
                    "No readable policy expiration date was found on the certificate; "
                    "a human must verify it.",
                    DISPOSITION_MANUAL_REVIEW,
                )
            )
        elif expires < today:
            failures.append(
                _result(
                    "coi.expired",
                    f"Insurance policy expired {expires.isoformat()}.",
                    DISPOSITION_FAILED,
                )
            )
    elif evidence_type == "pentest":
        report = _parse_date(fields.get("report_date")) or _parse_date(fields.get("issued_date"))
        if report is None:
            failures.append(
                _result(
                    "pentest.date_unknown",
                    "No readable report date was found on the penetration test; "
                    "a human must verify it.",
                    DISPOSITION_MANUAL_REVIEW,
                )
            )
        elif (today - report).days > PENTEST_MAX_AGE_DAYS:
            failures.append(
                _result(
                    "pentest.stale",
                    f"Penetration test report dated {report.isoformat()} is older "
                    f"than one year.",
                    DISPOSITION_FAILED,
                )
            )
    elif evidence_type == "pci":
        # The authoritative PCI currency rule is pending from CSUB (issue #36
        # open question; blocked-external issue #52). Until it is cited, no
        # age threshold is executable: every PCI attestation routes to a human
        # instead of auto-passing or failing on invented policy.
        assessed = _parse_date(fields.get("assessment_date")) or _parse_date(
            fields.get("issued_date")
        )
        dated = (
            f"dated {assessed.isoformat()} " if assessed is not None else "with no readable date "
        )
        failures.append(
            _result(
                "pci.currency_unverified",
                f"PCI attestation of compliance {dated}requires human review: the "
                f"authoritative currency rule is TBD pending CSUB citation "
                f"(issue #36 open question; issue #52).",
                DISPOSITION_MANUAL_REVIEW,
            )
        )
    return failures


def validate_identity(
    *, fields: dict[str, Any], vendor_name: str, product_name: str
) -> list[dict[str, str]]:
    """Flag documents that name a different vendor or product (issue #36).

    A mismatched document is rejected from automatic coverage and routed to a
    human. Matching is deterministic: normalized names must overlap (one
    contains the other); a model never confirms identity (AGENTS.md).
    """
    failures: list[dict[str, str]] = []
    checks = (
        ("vendor", vendor_name, "evidence.vendor_mismatch"),
        ("product", product_name, "evidence.product_mismatch"),
    )
    for field_name, expected, check in checks:
        stated = fields.get(field_name)
        if not isinstance(stated, str) or not stated.strip():
            continue
        stated_norm = _NORMALIZE.sub("", stated.lower())
        expected_norm = _NORMALIZE.sub("", expected.lower())
        if not stated_norm or not expected_norm:
            continue
        if stated_norm in expected_norm or expected_norm in stated_norm:
            continue
        failures.append(
            _result(
                check,
                f"Document names {field_name} {stated.strip()!r} but this submission "
                f"is for {expected!r}; a human must confirm it applies.",
                DISPOSITION_MANUAL_REVIEW,
            )
        )
    return failures
