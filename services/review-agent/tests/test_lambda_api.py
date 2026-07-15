from __future__ import annotations

import contextlib
import hashlib
import io
import json
import unittest

import _bootstrap  # noqa: F401

from review_agent.api import LocalReviewApi
from review_agent.config import AppConfig
from review_agent.lambda_api import (
    DynamoWorkspaceStore,
    InMemoryWorkspaceStore,
    create_handler,
    restore_api,
    seed_workspace,
    snapshot_api,
)
from review_agent.research import build_research_provider


class FakeTable:
    def __init__(self, *key_fields: str) -> None:
        self.key_fields = key_fields
        self.items: dict[tuple[object, ...], dict] = {}

    def _key(self, value: dict) -> tuple[object, ...]:
        return tuple(value[field] for field in self.key_fields)

    def get_item(self, *, Key: dict, **_kwargs) -> dict:
        item = self.items.get(self._key(Key))
        return {"Item": json.loads(json.dumps(item))} if item is not None else {}

    def put_item(self, *, Item: dict) -> None:
        self.items[self._key(Item)] = json.loads(json.dumps(Item))

    def delete_item(self, *, Key: dict) -> None:
        self.items.pop(self._key(Key), None)

    def scan(self, **_kwargs) -> dict:
        return {"Items": [json.loads(json.dumps(item)) for item in self.items.values()]}

    def batch_writer(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


def fake_dynamo_tables() -> dict[str, FakeTable]:
    return {
        "cases": FakeTable("case_id"),
        "vendor": FakeTable("vendor_id"),
        "product": FakeTable("product_id", "version"),
        "contact": FakeTable("contact_id"),
        "invite": FakeTable("token_hash"),
        "submission": FakeTable("submission_id", "case_id"),
        "review": FakeTable("case_id", "decision_version"),
        "profile": FakeTable("user_id", "version"),
        "integration": FakeTable("event_id", "occurred_at"),
        "audit": FakeTable("case_id", "sequence"),
        "idempotency": FakeTable("idempotency_key"),
    }


class FakeEvidenceUploads:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str], dict] = {}

    def issue(self, **kwargs) -> dict:
        value = {
            **kwargs,
            "processing_state": "queued",
            "warnings": [],
            "model_use_allowed": False,
            "claim_token": "internal-claim-must-not-leak",
            "upload": {
                "url": "https://uploads.example/quarantine",
                "method": "POST",
                "fields": {"key": f"quarantine/{kwargs['workspace_id']}/{kwargs['case_id']}/{kwargs['artifact_id']}"},
            },
        }
        self.records[(kwargs["workspace_id"], kwargs["case_id"], kwargs["artifact_id"])] = value
        return value

    def statuses(self, *, workspace_id: str, case_id: str, artifact_ids: list[str]) -> list[dict]:
        return [
            self.records[(workspace_id, case_id, artifact_id)]
            for artifact_id in artifact_ids
            if (workspace_id, case_id, artifact_id) in self.records
        ]


class LambdaApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryWorkspaceStore()
        seed_workspace(self.store)
        self.origin = "https://demo.example"
        self.evidence_uploads = FakeEvidenceUploads()
        self.handler = create_handler(
            self.store,
            allowed_origins=[self.origin],
            evidence_uploads=self.evidence_uploads,
        )

    def event(
        self,
        method: str,
        path: str,
        *,
        body: dict | str | None = None,
        headers: dict[str, str] | None = None,
        query: str = "",
        workspace: str = "csub-demo",
        authenticated: bool = True,
    ) -> dict:
        event = {
            "version": "2.0",
            "routeKey": f"{method} {path}",
            "rawPath": path,
            "rawQueryString": query,
            "headers": dict(headers or {}),
            "requestContext": {"http": {"method": method, "path": path}},
            "isBase64Encoded": False,
        }
        if authenticated:
            event["requestContext"]["authorizer"] = {
                "jwt": {
                    "claims": {
                        "email": "reviewer@example.edu",
                        "custom:workspace_id": workspace,
                    }
                }
            }
        if body is not None:
            event["body"] = body if isinstance(body, str) else json.dumps(body)
            event["headers"]["content-type"] = "application/json"
        return event

    def call(self, method: str, path: str, **kwargs):
        response = self.handler(self.event(method, path, **kwargs), None)
        payload = json.loads(response["body"]) if response["body"] else None
        return response, payload

    def test_health_is_live_not_simulated_and_cors_is_allowlisted(self) -> None:
        response, payload = self.call(
            "GET",
            "/health",
            authenticated=False,
            headers={"origin": self.origin},
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(payload, {"live": True, "mode": "aws-lambda", "status": "ok"})
        self.assertNotIn("simulated", payload)
        self.assertEqual(response["headers"]["Access-Control-Allow-Origin"], self.origin)

        preflight, _ = self.call(
            "OPTIONS",
            "/intake",
            authenticated=False,
            headers={"origin": self.origin},
        )
        self.assertEqual(preflight["statusCode"], 204)
        self.assertIn("Authorization", preflight["headers"]["Access-Control-Allow-Headers"])

        rejected, _ = self.call(
            "GET",
            "/health",
            authenticated=False,
            headers={"origin": "https://attacker.example"},
        )
        self.assertNotIn("Access-Control-Allow-Origin", rejected["headers"])

    def test_reviewer_routes_require_cognito_claims_and_isolate_workspace(self) -> None:
        unauthenticated, payload = self.call(
            "GET", "/review-queue", authenticated=False
        )
        self.assertEqual(unauthenticated["statusCode"], 401)
        self.assertEqual(payload["error"]["code"], "reviewer_auth_required")

        forbidden, payload = self.call(
            "GET", "/review-queue", workspace="other-workspace"
        )
        self.assertEqual(forbidden["statusCode"], 403)
        self.assertEqual(payload["error"]["code"], "workspace_forbidden")

        allowed, payload = self.call("GET", "/review-queue")
        self.assertEqual(allowed["statusCode"], 200)
        self.assertEqual(len(payload["items"]), 3)

    def test_reviewer_research_route_requires_auth_and_isolates_case_and_workspace(self) -> None:
        unauthenticated, payload = self.call(
            "GET", "/cases/TR-260714-014/research", authenticated=False
        )
        self.assertEqual(unauthenticated["statusCode"], 401)
        self.assertEqual(payload["error"]["code"], "reviewer_auth_required")

        forbidden, payload = self.call(
            "GET", "/cases/TR-260714-014/research", workspace="other-workspace"
        )
        self.assertEqual(forbidden["statusCode"], 403)
        self.assertEqual(payload["error"]["code"], "workspace_forbidden")

        allowed, payload = self.call("GET", "/cases/TR-260714-014/research")
        self.assertEqual(allowed["statusCode"], 200)
        self.assertEqual(
            payload,
            {"case_id": "TR-260714-014", "research_performed": False, "research": None},
        )
        missing, payload = self.call("GET", "/cases/UNKNOWN/research")
        self.assertEqual(missing["statusCode"], 404)
        self.assertEqual(payload["error"]["code"], "case_not_found")

        invitation_secret = "must-never-appear-in-research-url-logs"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rejected, payload = self.call(
                "GET",
                "/cases/TR-260714-014/research",
                query=f"token={invitation_secret}",
            )
        self.assertEqual(rejected["statusCode"], 400)
        self.assertEqual(payload["error"]["code"], "token_in_url_forbidden")
        self.assertNotIn(invitation_secret, output.getvalue())

    def test_restore_preserves_research_provider_when_backend_is_rebuilt(self) -> None:
        provider = build_research_provider(AppConfig(use_local_fakes=False))
        assert provider is not None
        api = LocalReviewApi(research_provider=provider)
        snapshot = snapshot_api(api, workspace_id="csub-demo")
        catalog = self.store.load_catalog("csub-demo")
        from unittest.mock import patch

        with patch("review_agent.lambda_api.LocalReviewApi", return_value=api):
            restored = restore_api(snapshot, catalog, workspace_id="csub-demo")

        self.assertIs(restored.research_provider, provider)
        self.assertIs(restored._vendor.research_provider, provider)

    def test_blank_catalog_vendor_does_not_break_workspace_restore(self) -> None:
        catalog = self.store.load_catalog("csub-demo")
        catalog[0]["vendor"] = None
        self.store.replace_catalog("csub-demo", catalog)

        response, payload = self.call("GET", "/review-queue")

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(len(payload["items"]), 3)

    def test_case_state_survives_a_fresh_handler_cold_start(self) -> None:
        intake = {
            "product_name": "Synthetic Calendar",
            "vendor_name": "Example Vendor",
            "requester": {
                "name": "Sample Requester",
                "email": "requester@example.edu",
                "department": "Library",
            },
            "use_case": "Sanitized public event scheduling.",
            "expected_users": 12,
            "platform": ["web"],
            "data_classification": "public",
            "estimated_cost_usd": 0,
            "integrations": [],
            "uses_sso": False,
            "uses_ai": False,
            "classroom_or_public_use": True,
        }
        response, created = self.call("POST", "/cases", body=intake)
        self.assertEqual(response["statusCode"], 201)
        case_id = created["case_id"]

        cold_handler = create_handler(self.store, allowed_origins=[self.origin])
        response = cold_handler(self.event("GET", f"/cases/{case_id}"), None)
        state = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(state["case_id"], case_id)
        self.assertEqual(state["case_input"]["product_name"], "Synthetic Calendar")

    def _issue_invite(self):
        _, vendors = self.call("GET", "/vendors")
        vendor = next(item for item in vendors["items"] if item["name"] == "LabArchives, LLC")
        _, contact = self.call(
            "POST",
            "/vendor-contacts",
            body={
                "vendor_id": vendor["vendor_id"],
                "name": "Synthetic Vendor Contact",
                "email": "contact@example.edu",
            },
        )
        response, issued = self.call(
            "POST",
            "/cases/TR-260714-014/invites",
            body={"contact_id": contact["contact_id"]},
        )
        self.assertEqual(response["statusCode"], 201)
        return issued

    def test_bearer_invite_is_hashed_at_rest_token_free_and_lifecycle_persists(self) -> None:
        issued = self._issue_invite()
        token = issued["token"]
        self.assertNotIn("token_hash", issued["invite"])
        snapshot_text = json.dumps(self.store.load_snapshot("csub-demo"), sort_keys=True)
        self.assertNotIn(token, snapshot_text)
        self.assertIn(hashlib.sha256(token.encode()).hexdigest(), snapshot_text)

        headers = {"authorization": f"Bearer {token}"}
        opened, payload = self.call(
            "POST", "/intake", headers=headers, authenticated=False, body={}
        )
        self.assertEqual(opened["statusCode"], 200)
        self.assertEqual(payload["invite"]["status"], "opened")
        self.assertNotIn("reviewer_notes", payload)
        self.assertNotIn("policy", payload)

        leaked, payload = self.call(
            "GET",
            "/intake",
            headers=headers,
            query=f"token={token}",
            authenticated=False,
        )
        self.assertEqual(leaked["statusCode"], 400)
        self.assertEqual(payload["error"]["code"], "token_in_url_forbidden")

        self.call("POST", f"/invites/{issued['invite']['invite_id']}/revoke", body={})
        cold = create_handler(self.store)
        response = cold(
            self.event(
                "GET",
                "/intake",
                headers=headers,
                authenticated=False,
            ),
            None,
        )
        payload = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 410)
        self.assertEqual(payload["error"]["code"], "invite_revoked")

    def test_vendor_submission_and_review_runs_are_immutable_across_cold_starts(self) -> None:
        issued = self._issue_invite()
        headers = {"authorization": f"Bearer {issued['token']}"}
        current_response, current = self.call(
            "GET",
            "/vendor/invites/current",
            headers=headers,
            authenticated=False,
        )
        self.assertEqual(current_response["statusCode"], 200)
        self.assertEqual(current["invite"]["status"], "issued")
        self.call(
            "POST",
            "/vendor/invites/current/open",
            headers=headers,
            authenticated=False,
            body={},
        )
        evidence_response, artifact = self.call(
            "POST",
            "/vendor/invites/current/evidence",
            headers=headers,
            authenticated=False,
            body={
                "filename": "synthetic-security.pdf",
                "content_type": "application/pdf",
                "size_bytes": 128,
                "sha256": "a" * 64,
            },
        )
        self.assertEqual(evidence_response["statusCode"], 200)
        self.assertEqual(artifact["processing_state"], "queued")
        self.assertNotIn("claim_token", artifact)
        self.assertEqual(artifact["upload"]["method"], "POST")
        self.assertNotIn("authorization", artifact["upload"]["fields"])
        status_response, statuses = self.call(
            "GET",
            "/vendor/invites/current/evidence",
            headers=headers,
            authenticated=False,
        )
        self.assertEqual(status_response["statusCode"], 200)
        self.assertEqual([item["artifact_id"] for item in statuses["items"]], [artifact["artifact_id"]])
        self.assertNotIn("claim_token", json.dumps(statuses))
        reviewer_response, reviewer_statuses = self.call(
            "GET", "/cases/TR-260714-014/documents"
        )
        self.assertEqual(reviewer_response["statusCode"], 200)
        self.assertIn(artifact["artifact_id"], [item["artifact_id"] for item in reviewer_statuses["items"]])
        other_invite = self._issue_invite()
        other_response, other_statuses = self.call(
            "GET",
            "/vendor/invites/current/evidence",
            headers={"authorization": f"Bearer {other_invite['token']}"},
            authenticated=False,
        )
        self.assertEqual(other_response["statusCode"], 200)
        self.assertEqual(other_statuses["items"], [])
        trust_response, _ = self.call(
            "POST",
            "/vendor/invites/current/trust-center",
            headers=headers,
            authenticated=False,
            body={"trust_center_url": "https://trust.example.edu/security"},
        )
        self.assertEqual(trust_response["statusCode"], 200)
        # Staged intake: questions are empty until the deterministic analysis runs.
        _, pre_analysis = self.call(
            "GET",
            "/vendor/invites/current/questions",
            headers=headers,
            authenticated=False,
        )
        self.assertEqual(pre_analysis["items"], [])
        self.assertFalse(pre_analysis["intake_analysis_complete"])
        analyze_response, _ = self.call(
            "POST",
            "/vendor/invites/current/analyze",
            headers=headers,
            authenticated=False,
            body={},
        )
        self.assertEqual(analyze_response["statusCode"], 200)
        _, questions = self.call(
            "GET",
            "/vendor/invites/current/questions",
            headers=headers,
            authenticated=False,
        )
        self.assertTrue(questions["intake_analysis_complete"])
        del artifact
        answers = {
            item["requirement_id"]: "Sanitized deterministic answer."
            for item in questions["items"]
        }
        if answers:
            answers_response, _ = self.call(
                "POST",
                "/vendor/invites/current/answers",
                headers=headers,
                authenticated=False,
                body={"answers": answers},
            )
            self.assertEqual(answers_response["statusCode"], 200)
        finalized, payload = self.call(
            "POST",
            "/vendor/invites/current/finalize",
            headers=headers,
            authenticated=False,
            body={},
        )
        self.assertEqual(finalized["statusCode"], 200)
        self.assertEqual(payload["status"], "finalized")

        first, run_one = self.call(
            "POST", "/cases/TR-260714-014/review-runs", body={}
        )
        self.assertEqual(first["statusCode"], 201)
        cold = create_handler(self.store)
        second = cold(
            self.event("POST", "/cases/TR-260714-014/review-runs", body={}),
            None,
        )
        run_two = json.loads(second["body"])
        self.assertEqual(run_two["run_version"], 2)
        self.assertEqual(run_two["previous_run_id"], run_one["run_id"])
        _, runs = self.call("GET", "/cases/TR-260714-014/review-runs")
        historical = next(item for item in runs["items"] if item["run_version"] == 1)
        self.assertEqual(historical, run_one)
        self.assertFalse(run_two["decision_valid"])
        self.assertFalse(run_two["write_preview_valid"])

    def test_review_fuzzy_confirmation_and_two_step_idempotent_writeback_survive_cold_start(self) -> None:
        _, queue = self.call("GET", "/review-queue")
        case = next(item for item in queue["items"] if item["case_id"] == "TR-260714-014")
        candidate = case["state"]["software_candidates"][0]
        self.assertEqual(candidate["match_method"], "fuzzy")
        self.assertTrue(candidate["requires_confirmation"])

        analyzed, payload = self.call(
            "POST",
            "/cases/TR-260714-014/analyze",
            body={
                "confirmed_match_id": candidate["record_id"],
                "reviewer_id": "spoofed@example.edu",
            },
        )
        self.assertEqual(analyzed["statusCode"], 202)
        confirmed = next(
            event for event in payload["audit_events"] if event["event_type"] == "match.confirmed"
        )
        self.assertEqual(confirmed["actor_id"], "reviewer@example.edu")
        self.assertEqual(payload["state"]["policy_result"]["risk_route"], "medium")

        reviewed, payload = self.call(
            "POST",
            "/cases/TR-260714-014/review",
            body={
                "case_id": "WRONG",
                "decision_version": 1,
                "reviewer_id": "spoofed@example.edu",
                "action": "approve",
                "decided_at": "2026-07-15T08:00:00+00:00",
            },
        )
        self.assertEqual(reviewed["statusCode"], 200)
        self.assertEqual(payload["state"]["human_decision"]["reviewer_id"], "reviewer@example.edu")
        self.assertTrue(payload["simulated"])

        previewed, payload = self.call(
            "POST", "/cases/TR-260714-014/servicenow/preview", body={}
        )
        self.assertEqual(previewed["statusCode"], 200)
        preview = payload["state"]["write_preview"]
        self.assertTrue(preview["simulated"])

        refused, payload = self.call(
            "POST",
            "/cases/TR-260714-014/servicenow/commit",
            body={"second_confirmation": False, "expected_version": preview["expected_record_version"]},
        )
        self.assertEqual(refused["statusCode"], 403)

        committed, payload = self.call(
            "POST",
            "/cases/TR-260714-014/servicenow/commit",
            body={"second_confirmation": True, "expected_version": preview["expected_record_version"]},
        )
        self.assertEqual(committed["statusCode"], 200)
        result = payload["state"]["write_result"]
        self.assertTrue(result["committed"])
        self.assertFalse(result["duplicate_suppressed"])
        self.assertIsNotNone(result["attachment"])

        cold = create_handler(self.store)
        replay = cold(
            self.event(
                "POST",
                "/cases/TR-260714-014/servicenow/commit",
                body={"second_confirmation": True, "expected_version": preview["expected_record_version"]},
            ),
            None,
        )
        replay_payload = json.loads(replay["body"])
        self.assertEqual(replay["statusCode"], 200)
        self.assertTrue(replay_payload["state"]["write_result"]["duplicate_suppressed"])

    def test_structured_logs_never_contain_token_or_body(self) -> None:
        issued = self._issue_invite()
        token = issued["token"]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            response, _ = self.call(
                "GET",
                "/intake",
                headers={"authorization": f"Bearer {token}"},
                authenticated=False,
            )
        self.assertEqual(response["statusCode"], 200)
        logged = output.getvalue()
        self.assertNotIn(token, logged)
        record = json.loads(logged.strip())
        self.assertEqual(set(record), {"correlation_id", "event_type", "status"})

    def test_dynamo_store_projects_scoped_state_and_restores_with_a_fresh_instance(self) -> None:
        tables = fake_dynamo_tables()
        store = DynamoWorkspaceStore(tables)
        seeded = seed_workspace(store)
        self.assertEqual(seeded["seeded_cases"], 3)
        self.assertEqual(len(store.load_catalog("csub-demo")), 3)
        snapshot = store.load_snapshot("csub-demo")
        self.assertEqual(snapshot["workspace_id"], "csub-demo")
        self.assertTrue(
            any(item["record_type"] == "profile" for item in tables["profile"].items.values())
        )
        self.assertTrue(
            all(item["workspace_id"] == "csub-demo" for item in tables["vendor"].items.values())
        )

        live = create_handler(store)
        response = live(self.event("GET", "/review-queue"), None)
        self.assertEqual(response["statusCode"], 200)
        fresh_store = DynamoWorkspaceStore(tables)
        cold = create_handler(fresh_store)
        response = cold(self.event("GET", "/cases/TR-260714-018"), None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["case_id"], "TR-260714-018")


    def test_invalid_json_and_oversized_metadata_are_rejected(self) -> None:
        invalid, payload = self.call("POST", "/cases", body="{not-json")
        self.assertEqual(invalid["statusCode"], 400)
        self.assertEqual(payload["error"]["code"], "invalid_json")
        oversized, payload = self.call("POST", "/cases", body="x" * 1_048_577)
        self.assertEqual(oversized["statusCode"], 413)
        self.assertEqual(payload["error"]["code"], "payload_too_large")


if __name__ == "__main__":
    unittest.main()
