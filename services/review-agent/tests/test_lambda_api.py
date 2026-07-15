from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import unittest

import _bootstrap  # noqa: F401

from review_agent.lambda_api import (
    DynamoWorkspaceStore,
    InMemoryWorkspaceStore,
    create_handler,
    seed_workspace,
)


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


class LambdaApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryWorkspaceStore()
        seed_workspace(self.store)
        self.origin = "https://demo.example"
        self.handler = create_handler(self.store, allowed_origins=[self.origin])

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

    def test_evidence_findings_survive_restore_and_validate_stored_bytes(self) -> None:
        # Regression (issue #36 follow-up): inline evidence bytes reach the
        # storage seam, the restored VendorBackend can read them during a later
        # request, and a workspace snapshot containing a persisted finding
        # restores instead of failing on an unsupported record kind.
        issued = self._issue_invite()
        headers = {"authorization": f"Bearer {issued['token']}"}
        self.call("POST", "/intake", headers=headers, authenticated=False, body={})
        body = (
            "CERTIFICATE OF INSURANCE\n"
            "coverage: cyber liability, general liability\n"
            "expires_date: 2026-06-30\n"
        ).encode("utf-8")
        upload, _ = self.call(
            "POST",
            "/vendor/invites/current/evidence",
            headers=headers,
            authenticated=False,
            body={
                "filename": "coi-acme.txt",
                "content_type": "text/plain",
                "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "content_base64": base64.b64encode(body).decode("ascii"),
            },
        )
        self.assertEqual(upload["statusCode"], 200)
        self.call(
            "POST",
            "/vendor/invites/current/trust-center",
            headers=headers,
            authenticated=False,
            body={"trust_center_url": "https://trust.example.edu/security"},
        )
        # The analyze request restores the API from the snapshot; the restored
        # backend must still see the stored bytes to produce the finding.
        analyze, _ = self.call(
            "POST",
            "/vendor/invites/current/analyze",
            headers=headers,
            authenticated=False,
            body={},
        )
        self.assertEqual(analyze["statusCode"], 200)
        # A cold start restores a workspace whose snapshot now contains a
        # persisted finding record.
        cold = create_handler(self.store)
        response = cold(
            self.event(
                "GET",
                "/vendor/invites/current/findings",
                headers=headers,
                authenticated=False,
            ),
            None,
        )
        self.assertEqual(response["statusCode"], 200)
        findings = json.loads(response["body"])["items"]
        self.assertEqual([item["check"] for item in findings], ["coi.expired"])
        self.assertEqual(findings[0]["disposition"], "failed")

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
