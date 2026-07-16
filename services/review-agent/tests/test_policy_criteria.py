from __future__ import annotations

import json
import unittest

import _bootstrap  # noqa: F401

from review_agent.api import LocalApiError, LocalReviewApi
from review_agent.contracts.vendor import PolicyCriteria
from review_agent.lambda_api import (
    InMemoryWorkspaceStore,
    create_handler,
    restore_api,
    seed_workspace,
    snapshot_api,
)


class PolicyCriteriaServiceTests(unittest.TestCase):
    """Reviewer-editable evidence policy criteria (issue #52)."""

    def setUp(self) -> None:
        self.api = LocalReviewApi()

    def test_default_is_provisional_and_defers_pci_to_manual_review(self) -> None:
        criteria = self.api.get_policy_criteria()
        self.assertEqual(criteria["version"], 0)
        self.assertTrue(criteria["provisional"])
        # pentest freshness is the one-year check confirmed in issue #36 feedback.
        self.assertEqual(criteria["pentest_max_age_days"], 365)
        # PCI currency stays TBD (None) until CSUB confirms it (issue #52); never
        # an agent-invented threshold.
        self.assertIsNone(criteria["pci_attestation_max_age_days"])
        self.assertEqual(criteria["coi_required_coverages"], ["cyber"])

    def test_update_versions_and_attributes_the_editor(self) -> None:
        first = self.api.update_policy_criteria(
            {
                "pentest_max_age_days": 180,
                "pci_attestation_max_age_days": 365,
                "coi_required_coverages": ["Cyber", "Privacy"],
                "evidence_expiry_days": 400,
            },
            reviewer_id="reviewer-a@example.edu",
        )
        self.assertEqual(first["version"], 1)
        self.assertEqual(first["updated_by"], "reviewer-a@example.edu")
        self.assertEqual(first["pentest_max_age_days"], 180)
        self.assertEqual(first["pci_attestation_max_age_days"], 365)
        # Coverage keywords are normalized to lowercase and de-duplicated.
        self.assertEqual(first["coi_required_coverages"], ["cyber", "privacy"])

        second = self.api.update_policy_criteria(
            {"pentest_max_age_days": 200, "coi_required_coverages": ["cyber"]},
            reviewer_id="reviewer-b@example.edu",
        )
        self.assertEqual(second["version"], 2)
        # get_policy_criteria returns the highest version.
        self.assertEqual(self.api.get_policy_criteria()["version"], 2)

    def test_null_threshold_is_accepted_as_tbd(self) -> None:
        result = self.api.update_policy_criteria(
            {
                "pentest_max_age_days": None,
                "pci_attestation_max_age_days": None,
                "coi_required_coverages": ["cyber"],
                "evidence_expiry_days": None,
            },
            reviewer_id="reviewer",
        )
        self.assertIsNone(result["pentest_max_age_days"])
        self.assertIsNone(result["evidence_expiry_days"])

    def test_non_positive_threshold_is_rejected(self) -> None:
        for bad in (0, -5, True):
            with self.subTest(bad=bad):
                with self.assertRaises(LocalApiError) as raised:
                    self.api.update_policy_criteria(
                        {"pentest_max_age_days": bad, "coi_required_coverages": ["cyber"]},
                        reviewer_id="reviewer",
                    )
                self.assertEqual(raised.exception.status, 400)

    def test_update_records_an_audit_event(self) -> None:
        self.api.update_policy_criteria(
            {"coi_required_coverages": ["cyber"]}, reviewer_id="reviewer-z"
        )
        events = self.api.integration_events()["items"]
        updated = [e for e in events if e["event_type"] == "policy.criteria_updated"]
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["detail"]["updated_by"], "reviewer-z")

    def test_criteria_survive_snapshot_restore(self) -> None:
        self.api.update_policy_criteria(
            {"pentest_max_age_days": 90, "coi_required_coverages": ["cyber"]},
            reviewer_id="reviewer",
        )
        snapshot = snapshot_api(self.api, workspace_id="csub-demo")
        restored = restore_api(snapshot, [], workspace_id="csub-demo")
        self.assertEqual(restored.get_policy_criteria()["pentest_max_age_days"], 90)
        self.assertEqual(restored.get_policy_criteria()["version"], 1)

    def test_from_dict_rejects_non_integer_threshold(self) -> None:
        with self.assertRaises(ValueError):
            PolicyCriteria.from_dict(
                {
                    "criteria_version_id": "policy-criteria-csub-demo-001",
                    "version": 1,
                    "pentest_max_age_days": "soon",
                }
            )


class PolicyCriteriaHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryWorkspaceStore()
        seed_workspace(self.store)
        self.handler = create_handler(self.store)

    def event(self, method: str, path: str, *, body=None, authenticated: bool = True) -> dict:
        event = {
            "version": "2.0",
            "rawPath": path,
            "rawQueryString": "",
            "headers": {},
            "requestContext": {"http": {"method": method, "path": path}},
            "isBase64Encoded": False,
        }
        if authenticated:
            event["requestContext"]["authorizer"] = {
                "jwt": {"claims": {"email": "reviewer@example.edu", "custom:workspace_id": "csub-demo"}}
            }
        if body is not None:
            event["body"] = json.dumps(body)
            event["headers"]["content-type"] = "application/json"
        return event

    def call(self, method: str, path: str, **kwargs):
        response = self.handler(self.event(method, path, **kwargs), None)
        return response, (json.loads(response["body"]) if response["body"] else None)

    def test_reviewer_can_read_and_edit_criteria_and_it_persists(self) -> None:
        get_response, criteria = self.call("GET", "/policy-criteria")
        self.assertEqual(get_response["statusCode"], 200)
        self.assertEqual(criteria["version"], 0)

        put_response, updated = self.call(
            "PUT",
            "/policy-criteria",
            body={
                "pentest_max_age_days": 270,
                "pci_attestation_max_age_days": 365,
                "coi_required_coverages": ["cyber"],
                "evidence_expiry_days": 365,
                "provisional": False,
            },
        )
        self.assertEqual(put_response["statusCode"], 200)
        self.assertEqual(updated["version"], 1)
        self.assertFalse(updated["provisional"])
        self.assertEqual(updated["updated_by"], "reviewer@example.edu")

        # Persisted across a cold handler backed by the same store.
        cold = create_handler(self.store)
        cold_response = cold(self.event("GET", "/policy-criteria"), None)
        self.assertEqual(json.loads(cold_response["body"])["pentest_max_age_days"], 270)

    def test_editing_criteria_requires_reviewer_auth(self) -> None:
        response, _ = self.call(
            "PUT", "/policy-criteria", body={"coi_required_coverages": ["cyber"]}, authenticated=False
        )
        self.assertEqual(response["statusCode"], 401)


if __name__ == "__main__":
    unittest.main()
