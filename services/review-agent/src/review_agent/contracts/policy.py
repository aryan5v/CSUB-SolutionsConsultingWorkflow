"""Deterministic policy contracts (FR-3).

A ``PolicyRule`` is only executable when traced to a flowchart, policy,
decision tree, or confirmed override. Model output may explain a result but
must never alter it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from .common import Citation, Conflict, SourceCoordinates


class RiskRoute(str, Enum):
    APPROVED = "approved"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    ESCALATE = "escalate"
    UNKNOWN = "unknown"


class SourcePrecedence(int, Enum):
    """FR-3 source precedence. Lower number wins."""

    PARTNER_OVERRIDE = 1
    FORMAL_POLICY = 2
    DECISION_TREE_DRAFT = 3
    DISCOVERY_STATEMENT = 4
    MODEL_INFERENCE = 5


@dataclass(frozen=True, slots=True)
class PolicyTrigger:
    rule_id: str
    description: str
    citation: SourceCoordinates | None = None

    def to_dict(self) -> dict:
        out: dict = {"rule_id": self.rule_id, "description": self.description}
        if self.citation is not None:
            out["citation"] = self.citation.to_dict()
        return out


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """A single versioned, source-cited rule.

    ``predicate`` returns True when the rule fires for a given case. Rules are
    pure functions of structured inputs only; they never call a model.
    """

    rule_id: str
    description: str
    route: RiskRoute
    citation: SourceCoordinates
    precedence: SourcePrecedence
    required_evidence: tuple[str, ...] = ()
    recommendation_clause_ids: tuple[str, ...] = ()
    predicate: Callable[["PolicyInputs"], bool] = field(default=lambda _inputs: False)


@dataclass(frozen=True, slots=True)
class PolicyInputs:
    """Normalized, deterministic inputs to policy evaluation.

    Deliberately a small explicit surface so boundary tests are exhaustive.
    """

    expected_users: int
    estimated_cost_usd: float
    data_classification: str
    uses_ai: bool
    uses_sso: bool
    integrations_count: int
    classroom_or_public_use: bool
    is_approved_software: bool
    missing_required_inputs: tuple[str, ...] = ()


@dataclass(slots=True)
class PolicyRuleSet:
    version: str
    rules: list[PolicyRule] = field(default_factory=list)


@dataclass(slots=True)
class PolicyResult:
    policy_version: str
    risk_route: RiskRoute
    triggers: list[PolicyTrigger] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    recommendation_clause_ids: list[str] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    escalated: bool = False
    escalation_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "policy_version": self.policy_version,
            "risk_route": self.risk_route.value,
            "triggers": [t.to_dict() for t in self.triggers],
            "required_evidence": list(self.required_evidence),
            "recommendation_clause_ids": list(self.recommendation_clause_ids),
            "conflicts": [c.to_dict() for c in self.conflicts],
            "citations": [c.to_dict() for c in self.citations],
            "escalated": self.escalated,
            "escalation_reasons": list(self.escalation_reasons),
        }
