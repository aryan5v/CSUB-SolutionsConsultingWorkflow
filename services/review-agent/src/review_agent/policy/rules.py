"""Versioned deterministic rule set (FR-3).

Every rule is traced to an institutional source via a ``SourceCoordinates``
citation and carries a ``SourcePrecedence``. The thresholds encoded here are
labeled ASSUMPTION: they stand in for the disputed values in the PRD open
questions and must be reconciled against the partner-confirmed decision tree
before the demo. Disputed *bands* live in ``conflicts.py`` and escalate rather
than resolve.
"""

from __future__ import annotations

from ..contracts.policy import (
    PolicyInputs,
    PolicyRule,
    PolicyRuleSet,
    RiskRoute,
    SourcePrecedence,
)
from ..contracts.common import SourceCoordinates

POLICY_VERSION = "2026.07.14-draft"

# ASSUMPTION thresholds (placeholders pending partner confirmation). Unambiguous
# bounds only; the genuinely disputed middle bands are handled by the conflict
# registry, not here.
COST_CLEARLY_HIGH_USD = 50_000.0
USERS_CLEARLY_LARGE = 1_000


def _cite(source_id: str, note: str) -> SourceCoordinates:
    return SourceCoordinates(source_id=source_id, filename=note, version=POLICY_VERSION)


def default_ruleset() -> PolicyRuleSet:
    rules = [
        PolicyRule(
            rule_id="R-APPROVED",
            description="Product already present in the approved-software export.",
            route=RiskRoute.APPROVED,
            citation=_cite("src:approved-software-export", "SNOW approved software database"),
            precedence=SourcePrecedence.FORMAL_POLICY,
            recommendation_clause_ids=("RC-APPROVED-REUSE",),
            predicate=lambda i: i.is_approved_software,
        ),
        PolicyRule(
            rule_id="R-DATA-PROTECTED",
            description="Touches confidential/Level 1 protected data; security review required.",
            route=RiskRoute.HIGH,
            citation=_cite("src:data-classification-guidance", "Data classification guidance"),
            precedence=SourcePrecedence.FORMAL_POLICY,
            required_evidence=("hecvat", "soc2"),
            recommendation_clause_ids=("RC-SEC-PROTECTED-DATA",),
            predicate=lambda i: i.data_classification in {"confidential", "level1"},
        ),
        PolicyRule(
            rule_id="R-AI",
            description="Uses AI features; bounded AI/security review required.",
            route=RiskRoute.MEDIUM,
            citation=_cite("src:risk-review-process", "Risk Review Process"),
            precedence=SourcePrecedence.FORMAL_POLICY,
            required_evidence=("hecvat",),
            recommendation_clause_ids=("RC-AI-REVIEW",),
            predicate=lambda i: i.uses_ai,
        ),
        PolicyRule(
            rule_id="R-COST-HIGH",
            description="Estimated cost clearly above review threshold; procurement review.",
            route=RiskRoute.MEDIUM,
            citation=_cite("src:risk-review-process", "Risk Review Process"),
            precedence=SourcePrecedence.FORMAL_POLICY,
            required_evidence=("soc2",),
            recommendation_clause_ids=("RC-PROCUREMENT",),
            predicate=lambda i: i.estimated_cost_usd >= COST_CLEARLY_HIGH_USD,
        ),
        PolicyRule(
            rule_id="R-USERS-LARGE",
            description="Large expected user base; broader security and accessibility review.",
            route=RiskRoute.MEDIUM,
            citation=_cite("src:decision-tree", "Solution acquisition decision tree"),
            precedence=SourcePrecedence.DECISION_TREE_DRAFT,
            recommendation_clause_ids=("RC-SCALE-REVIEW",),
            predicate=lambda i: i.expected_users >= USERS_CLEARLY_LARGE,
        ),
        PolicyRule(
            rule_id="R-INTEGRATIONS-SSO",
            description="SSO or system integrations present; security review of connections.",
            route=RiskRoute.MEDIUM,
            citation=_cite("src:risk-review-process", "Risk Review Process"),
            precedence=SourcePrecedence.FORMAL_POLICY,
            required_evidence=("soc2",),
            recommendation_clause_ids=("RC-INTEGRATION-SEC",),
            predicate=lambda i: i.uses_sso or i.integrations_count > 0,
        ),
        PolicyRule(
            rule_id="R-CLASSROOM-PUBLIC",
            description="Classroom or public-facing use; accessibility (ATI/VPAT) review.",
            route=RiskRoute.MEDIUM,
            citation=_cite("src:decision-tree", "Solution acquisition decision tree"),
            precedence=SourcePrecedence.DECISION_TREE_DRAFT,
            required_evidence=("vpat_acr",),
            recommendation_clause_ids=("RC-ACCESSIBILITY",),
            predicate=lambda i: i.classroom_or_public_use,
        ),
    ]
    return PolicyRuleSet(version=POLICY_VERSION, rules=rules)


def default_inputs(**overrides: object) -> PolicyInputs:
    """Build PolicyInputs with safe defaults for tests and the demo."""
    base = {
        "expected_users": 0,
        "estimated_cost_usd": 0.0,
        "data_classification": "public",
        "uses_ai": False,
        "uses_sso": False,
        "integrations_count": 0,
        "classroom_or_public_use": False,
        "is_approved_software": False,
        "missing_required_inputs": (),
    }
    base.update(overrides)
    return PolicyInputs(**base)  # type: ignore[arg-type]
