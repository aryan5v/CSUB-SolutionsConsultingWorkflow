"""Security specialist node (FR-5).

Runs after deterministic routing. Produces a schema-shaped structured result
with citations and disclosed uncertainty. It may summarize and compare evidence
but must not alter the risk route or required-evidence list computed by the
policy engine.
"""

from __future__ import annotations

from ..adapters.model import ModelClient
from ..contracts.case import CaseIntake
from ..contracts.common import Citation, CitationScope
from ..contracts.policy import PolicyResult

SPECIALIST_NAME = "security"


def run_security(case: CaseIntake, policy: PolicyResult, model: ModelClient) -> dict:
    raw = model.complete_json(
        system="You are a security review specialist. Summarize and compare only; "
        "do not set risk tiers or required documents.",
        prompt=f"Summarize the security posture questions for {case.product_name}.",
        context={"task": "security_analysis", "product": case.product_name},
    )
    # Ground the specialist output in the deterministic policy citations so every
    # claim traces to a source; the model's free text is advisory only.
    citations = [
        Citation(
            claim=f"Required security evidence: {evidence}",
            source=_policy_source(policy),
            scope=CitationScope.POLICY,
            verified=True,
        )
        for evidence in policy.required_evidence
        if evidence in {"hecvat", "soc2", "pci", "pentest"}
    ]
    return {
        "specialist": SPECIALIST_NAME,
        "summary": raw.get("summary", ""),
        "required_evidence": [
            e for e in policy.required_evidence if e in {"hecvat", "soc2", "pci", "pentest"}
        ],
        "findings": raw.get("findings", []),
        "citations": [c.to_dict() for c in citations],
        "uncertainty": raw.get("uncertainty", ""),
    }


def _policy_source(policy: PolicyResult):
    if policy.citations:
        return policy.citations[0].source
    from ..contracts.common import SourceCoordinates

    return SourceCoordinates(source_id="src:risk-review-process")
