"""Evidence gap analysis (PLAN: evidence specialist).

Compares the evidence a vendor dropped against what CSUB's deterministic policy
*requires* for the case. Both sides are structured facts, so the gap is a pure
set operation — not a model judgment. That placement is deliberate: a model may
help classify an uploaded file's type upstream, but what is required and whether
a requirement is met stays deterministic and human-confirmed (AGENTS.md: the
model must not confirm fuzzy matches or clear a case).
"""

from __future__ import annotations

import datetime

from ..contracts.evidence import EvidenceRecord
from ..contracts.policy import PolicyResult
from ..contracts.vendor import EvidenceGap, EvidenceGapReport


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def analyze_gaps(
    *,
    case_id: str,
    policy_result: PolicyResult,
    provided: list[EvidenceRecord],
    clock=_utc_now,
) -> EvidenceGapReport:
    """Deterministic required-vs-provided gap for one case.

    Evidence is filtered to ``case_id`` so nothing crosses a case boundary
    (FR-4). Required types come from ``policy_result.required_evidence`` and are
    de-duplicated while preserving first-seen order.
    """
    # Map required evidence type -> list of provided evidence ids for this case.
    provided_by_type: dict[str, list[str]] = {}
    for record in provided:
        if record.case_id != case_id:
            continue  # never count another case's evidence
        provided_by_type.setdefault(record.evidence_type.value, []).append(record.evidence_id)

    required: list[str] = []
    for item in policy_result.required_evidence:
        if item not in required:
            required.append(item)

    gaps: list[EvidenceGap] = []
    for req in required:
        ids = provided_by_type.get(req, [])
        gaps.append(
            EvidenceGap(
                evidence_type=req,
                satisfied=bool(ids),
                provided_evidence_ids=ids,
                note=(
                    f"{len(ids)} matching upload(s)"
                    if ids
                    else "no matching vendor evidence received"
                ),
            )
        )

    satisfied = [g.evidence_type for g in gaps if g.satisfied]
    missing = [g.evidence_type for g in gaps if not g.satisfied]
    return EvidenceGapReport(
        case_id=case_id,
        risk_route=policy_result.risk_route.value,
        policy_version=policy_result.policy_version,
        required=required,
        satisfied=satisfied,
        missing=missing,
        gaps=gaps,
        generated_at=clock(),
    )
