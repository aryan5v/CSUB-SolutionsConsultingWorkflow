"""Deterministic policy evaluation (FR-3).

Pure function of structured inputs. No model call, no I/O. Model output can
explain a result downstream but must never change these values. Safety default
is to escalate: missing inputs, unknown data classification, high-risk triggers,
and disputed thresholds all route to human review rather than a guess.
"""

from __future__ import annotations

from dataclasses import asdict

from ..contracts.case import CaseIntake
from ..contracts.common import Citation, CitationScope
from ..contracts.policy import (
    PolicyInputs,
    PolicyResult,
    PolicyRuleSet,
    PolicyTrigger,
    RiskRoute,
)
from .conflicts import ConflictRegistry

# Routes that mean "stop and escalate to a human" rather than "produce a packet".
_ESCALATION_ROUTES = frozenset({RiskRoute.HIGH, RiskRoute.ESCALATE, RiskRoute.UNKNOWN})

REQUIRED_INTAKE_FIELDS = (
    "product_name",
    "vendor_name",
    "use_case",
    "data_classification",
)


def build_inputs(
    case: CaseIntake,
    *,
    is_approved_software: bool = False,
    missing_required_inputs: tuple[str, ...] = (),
) -> PolicyInputs:
    """Project a CaseIntake into the deterministic policy input surface."""
    return PolicyInputs(
        expected_users=case.expected_users,
        estimated_cost_usd=case.estimated_cost_usd,
        data_classification=case.data_classification.value,
        uses_ai=case.uses_ai,
        uses_sso=case.uses_sso,
        integrations_count=len(case.integrations),
        classroom_or_public_use=case.classroom_or_public_use,
        is_approved_software=is_approved_software,
        missing_required_inputs=missing_required_inputs,
    )


def evaluate(
    inputs: PolicyInputs,
    ruleset: PolicyRuleSet,
    registry: ConflictRegistry,
) -> PolicyResult:
    triggers: list[PolicyTrigger] = []
    citations: list[Citation] = []
    required_evidence: list[str] = []
    clause_ids: list[str] = []
    reasons: list[str] = []

    if inputs.missing_required_inputs:
        reasons.append(
            "missing required inputs: " + ", ".join(inputs.missing_required_inputs)
        )
    if inputs.data_classification == "unknown":
        reasons.append("data classification is unknown; cannot route safely")

    fired = [rule for rule in ruleset.rules if rule.predicate(inputs)]
    routes_fired: set[RiskRoute] = set()
    for rule in fired:
        routes_fired.add(rule.route)
        triggers.append(
            PolicyTrigger(
                rule_id=rule.rule_id,
                description=rule.description,
                citation=rule.citation,
            )
        )
        citations.append(
            Citation(
                claim=rule.description,
                source=rule.citation,
                scope=CitationScope.POLICY,
                verified=True,
            )
        )
        for evidence in rule.required_evidence:
            if evidence not in required_evidence:
                required_evidence.append(evidence)
        for clause in rule.recommendation_clause_ids:
            if clause not in clause_ids:
                clause_ids.append(clause)

    conflicts = registry.disputes_for(asdict(inputs))
    for conflict in conflicts:
        reasons.append(f"disputed threshold pending confirmation: {conflict.topic}")

    escalated = bool(reasons) or bool(_ESCALATION_ROUTES & routes_fired)
    route = _select_route(routes_fired, escalated=escalated)

    return PolicyResult(
        policy_version=ruleset.version,
        risk_route=route,
        triggers=triggers,
        required_evidence=required_evidence,
        recommendation_clause_ids=clause_ids,
        conflicts=conflicts,
        citations=citations,
        escalated=escalated,
        escalation_reasons=reasons,
    )


def _select_route(routes_fired: set[RiskRoute], *, escalated: bool) -> RiskRoute:
    if RiskRoute.HIGH in routes_fired:
        return RiskRoute.HIGH
    if escalated:
        return RiskRoute.ESCALATE
    if RiskRoute.MEDIUM in routes_fired:
        return RiskRoute.MEDIUM
    if RiskRoute.APPROVED in routes_fired:
        return RiskRoute.APPROVED
    # Nothing risky fired and no escalation condition -> low-risk summary path.
    return RiskRoute.LOW
