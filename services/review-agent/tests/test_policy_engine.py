"""Deterministic policy boundary tests (FR-3)."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from review_agent.contracts.policy import RiskRoute
from review_agent.policy.conflicts import default_conflict_registry
from review_agent.policy.engine import evaluate
from review_agent.policy.rules import default_inputs, default_ruleset


class PolicyEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ruleset = default_ruleset()
        self.registry = default_conflict_registry()

    def _evaluate(self, **overrides):
        return evaluate(default_inputs(**overrides), self.ruleset, self.registry)

    def test_benign_case_is_low_risk(self) -> None:
        result = self._evaluate()
        self.assertEqual(result.risk_route, RiskRoute.LOW)
        self.assertFalse(result.escalated)

    def test_approved_software_fast_paths(self) -> None:
        result = self._evaluate(is_approved_software=True)
        self.assertEqual(result.risk_route, RiskRoute.APPROVED)
        self.assertIn("RC-APPROVED-REUSE", result.recommendation_clause_ids)

    def test_ai_use_is_medium(self) -> None:
        result = self._evaluate(uses_ai=True)
        self.assertEqual(result.risk_route, RiskRoute.MEDIUM)
        self.assertFalse(result.escalated)
        self.assertIn("hecvat", result.required_evidence)

    def test_protected_data_is_high_and_escalates(self) -> None:
        result = self._evaluate(data_classification="level1")
        self.assertEqual(result.risk_route, RiskRoute.HIGH)
        self.assertTrue(result.escalated)

    def test_unknown_classification_escalates(self) -> None:
        result = self._evaluate(data_classification="unknown")
        self.assertTrue(result.escalated)
        self.assertEqual(result.risk_route, RiskRoute.ESCALATE)

    def test_cost_above_band_is_medium_not_escalated(self) -> None:
        result = self._evaluate(estimated_cost_usd=60_000.0)
        self.assertEqual(result.risk_route, RiskRoute.MEDIUM)
        self.assertFalse(result.escalated)

    def test_cost_in_disputed_band_escalates_with_conflict(self) -> None:
        result = self._evaluate(estimated_cost_usd=30_000.0)
        self.assertTrue(result.escalated)
        topics = {c.topic for c in result.conflicts}
        self.assertIn("cost_review_threshold_usd", topics)

    def test_user_count_in_disputed_band_escalates(self) -> None:
        result = self._evaluate(expected_users=500)
        self.assertTrue(result.escalated)
        topics = {c.topic for c in result.conflicts}
        self.assertIn("user_count_review_threshold", topics)

    def test_every_trigger_has_a_citation(self) -> None:
        result = self._evaluate(uses_ai=True, uses_sso=True, classroom_or_public_use=True)
        self.assertTrue(result.triggers)
        for trigger in result.triggers:
            self.assertIsNotNone(trigger.citation)
            self.assertTrue(trigger.citation.source_id)

    def test_missing_inputs_escalate(self) -> None:
        result = self._evaluate(missing_required_inputs=("vendor_name",))
        self.assertTrue(result.escalated)


if __name__ == "__main__":
    unittest.main()
