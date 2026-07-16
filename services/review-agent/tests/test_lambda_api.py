from __future__ import annotations

import contextlib
import datetime
import hashlib
import io
import json
import tempfile
import threading
import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.email import SimulatedEmailSender
from review_agent.api import LocalReviewApi
from review_agent.config import AppConfig
from review_agent.lambda_api import (
    DynamoWorkspaceStore,
    FileWorkspaceStore,
    InMemoryWorkspaceStore,
    create_handler,
    restore_api,
    seed_workspace,
    snapshot_api,
)
from review_agent.research import build_research_provider


class ConditionalCheckFailed(Exception):
    def __init__(self) -> None:
        super().__init__("conditional check failed")
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    def __init__(self, *key_fields: str) -> None:
        self.key_fields = key_fields
        self.items: dict[tuple[object, ...], dict] = {}
        self.update_calls: list[dict] = []

    def _key(self, value: dict) -> tuple[object, ...]:
        return tuple(value[field] for field in self.key_fields)

    def get_item(self, *, Key: dict, **_kwargs) -> dict:
        item = self.items.get(self._key(Key))
        return {"Item": json.loads(json.dumps(item))} if item is not None else {}

    def update_item(self, **kwargs) -> dict:
        self.update_calls.append(json.loads(json.dumps(kwargs)))
        key = kwargs["Key"]
        item_key = self._key(key)
        current = self.items.get(item_key)
        values = kwargs["ExpressionAttributeValues"]
        if ":max_attempts" in values:
            if current is not None and not (
                current.get("status") == values[":failed"]
                and int(current.get("attempts", 0)) < values[":max_attempts"]
            ):
                raise ConditionalCheckFailed()
            updated = dict(current or key)
            updated.update(
                {
                    "workspace_id": values[":workspace"],
                    "record_type": values[":record_type"],
                    "dedupe_key": values[":dedupe_key"],
                    "case_id": values[":case_id"],
                    "invite_id": values[":invite_id"],
                    "status": values[":pending"],
                    "attempts": int((current or {}).get("attempts", values[":zero"]))
                    + values[":one"],
                    "claimed_at": values[":claimed_at"],
                    "ttl": values[":ttl"],
                }
            )
        else:
            if not (
                current is not None
                and current.get("workspace_id") == values[":workspace"]
                and current.get("record_type") == values[":record_type"]
                and current.get("status") == values[":pending"]
                and int(current.get("attempts", 0)) == values[":attempts"]
            ):
                raise ConditionalCheckFailed()
            updated = {**current, "status": values[":status"]}
        self.items[item_key] = json.loads(json.dumps(updated))
        return {"Attributes": json.loads(json.dumps(updated))}

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


class BlockingEmailSender:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.sent: list[str] = []

    def send(self, *, to: str, subject: str, body: str) -> dict:
        del subject, body
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test did not release sender")
        self.sent.append(to)
        return {
            "delivery": "simulated",
            "simulated": True,
            "channel": "email",
            "to": to,
        }


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

        unauthenticated, payload = self.call(
            "POST", "/reminders/run", authenticated=False, body={}
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

    def _make_invite_due(
        self, invite_id: str, now: datetime.datetime
    ) -> None:
        snapshot = self.store.load_snapshot("csub-demo")
        assert snapshot is not None
        invites = snapshot["repository"]["records"]["invite"]
        invite = next(item for item in invites if item["invite_id"] == invite_id)
        invite["issued_at"] = (now - datetime.timedelta(days=8)).isoformat()
        invite["expires_at"] = (now + datetime.timedelta(days=30)).isoformat()
        self.store.save_snapshot("csub-demo", snapshot)

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

    def test_vendor_public_status_survives_lambda_cold_start(self) -> None:
        issued = self._issue_invite()
        token = issued["token"]
        _, queue = self.call("GET", "/review-queue")
        case = next(
            item for item in queue["items"] if item["case_id"] == "TR-260714-014"
        )
        candidate = case["state"]["software_candidates"][0]
        analyzed, _ = self.call(
            "POST",
            "/cases/TR-260714-014/analyze",
            body={"confirmed_match_id": candidate["record_id"]},
        )
        self.assertEqual(analyzed["statusCode"], 202)
        reviewed, _ = self.call(
            "POST",
            "/cases/TR-260714-014/review",
            body={
                "case_id": "TR-260714-014",
                "decision_version": 1,
                "action": "request_info",
                "decided_at": "2026-07-15T08:00:00+00:00",
                "comments": "Internal finding that must stay private.",
                "vendor_visible_comment": "Please provide the requested updates.",
                "vendor_next_actions": ["Upload the current product-specific ACR."],
            },
        )
        self.assertEqual(reviewed["statusCode"], 200)

        snapshot = self.store.load_snapshot("csub-demo")
        vendor_case = next(
            item
            for item in snapshot["repository"]["records"]["case"]
            if item["case_id"] == "TR-260714-014"
        )
        self.assertEqual(
            vendor_case["vendor_visible_comment"],
            "Please provide the requested updates.",
        )
        self.assertEqual(
            vendor_case["vendor_next_actions"],
            ["Upload the current product-specific ACR."],
        )

        cold = create_handler(self.store, allowed_origins=[self.origin])
        response = cold(
            self.event(
                "GET",
                "/vendor/invites/current/status",
                headers={"authorization": f"Bearer {token}"},
                authenticated=False,
            ),
            None,
        )
        status = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(status["review_stage"], "changes_requested")
        self.assertEqual(
            status["vendor_visible_comment"],
            "Please provide the requested updates.",
        )
        self.assertEqual(
            status["next_actions"],
            ["Upload the current product-specific ACR."],
        )
        self.assertNotIn("comments", status)
        self.assertNotIn("Internal finding", json.dumps(status))

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


    def test_scheduled_reminder_runs_without_jwt_and_persists(self) -> None:
        issued = self._issue_invite()
        now = datetime.datetime(2026, 7, 23, 12, tzinfo=datetime.timezone.utc)
        self._make_invite_due(issued["invite"]["invite_id"], now)
        sender = SimulatedEmailSender()
        scheduled = create_handler(self.store, email_sender=sender, clock=lambda: now)

        result = scheduled({"scheduled_task": "reminders_run"}, None)

        self.assertEqual(result["scheduled_task"], "reminders_run")
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(sender.sent), 1)
        snapshot = self.store.load_snapshot("csub-demo")
        assert snapshot is not None
        reminders = [
            event
            for event in snapshot["repository"]["records"]["event"]
            if event["event_type"] == "email.reminder"
        ]
        self.assertEqual(len(reminders), 1)
        self.assertIn("recipient_sha256", reminders[0]["detail"])
        self.assertNotIn(sender.sent[0]["to"], json.dumps(reminders))

    def test_two_independent_restores_send_once_and_loser_does_not_save(self) -> None:
        issued = self._issue_invite()
        now = datetime.datetime(2026, 7, 23, 12, tzinfo=datetime.timezone.utc)
        self._make_invite_due(issued["invite"]["invite_id"], now)
        sender = BlockingEmailSender()
        first = create_handler(self.store, email_sender=sender, clock=lambda: now)
        second = create_handler(self.store, email_sender=sender, clock=lambda: now)
        save_calls: list[dict] = []
        original_save = self.store.save_snapshot

        def tracked_save(workspace_id: str, snapshot: dict) -> None:
            save_calls.append(json.loads(json.dumps(snapshot)))
            original_save(workspace_id, snapshot)

        self.store.save_snapshot = tracked_save  # type: ignore[method-assign]
        winner_responses: list[dict] = []
        thread = threading.Thread(
            target=lambda: winner_responses.append(
                first(self.event("POST", "/reminders/run", body={}), None)
            )
        )
        thread.start()
        self.assertTrue(sender.entered.wait(timeout=5))
        try:
            losing = second(self.event("POST", "/reminders/run", body={}), None)
            losing_payload = json.loads(losing["body"])
            self.assertEqual(losing_payload["count"], 0)
            self.assertEqual(save_calls, [])
        finally:
            sender.release.set()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(winner_responses), 1)
        self.assertEqual(json.loads(winner_responses[0]["body"])["count"], 1)
        self.assertEqual(sender.sent, ["contact@example.edu"])
        self.assertEqual(len(save_calls), 1)
        snapshot = self.store.load_snapshot("csub-demo")
        assert snapshot is not None
        reminders = [
            event
            for event in snapshot["repository"]["records"]["event"]
            if event["event_type"] == "email.reminder"
        ]
        self.assertEqual(len(reminders), 1)

    def test_file_delivery_claims_persist_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/workspace.json"
            first = FileWorkspaceStore(path)
            claim = first.claim(
                workspace_id="csub-demo",
                dedupe_key="reminder:CASE-1:1",
                case_id="CASE-1",
                invite_id="invite-1",
                claimed_at="2026-07-21T12:00:00+00:00",
                max_attempts=3,
            )
            assert claim is not None
            second = FileWorkspaceStore(path)
            self.assertIsNone(
                second.claim(
                    workspace_id="csub-demo",
                    dedupe_key="reminder:CASE-1:1",
                    case_id="CASE-1",
                    invite_id="invite-1",
                    claimed_at="2026-07-21T12:01:00+00:00",
                    max_attempts=3,
                )
            )
            self.assertTrue(
                second.settle(
                    workspace_id="csub-demo",
                    dedupe_key="reminder:CASE-1:1",
                    attempts=1,
                    status="failed",
                )
            )
            retry = first.claim(
                workspace_id="csub-demo",
                dedupe_key="reminder:CASE-1:1",
                case_id="CASE-1",
                invite_id="invite-1",
                claimed_at="2026-07-21T12:02:00+00:00",
                max_attempts=3,
            )
            assert retry is not None
            self.assertEqual(retry.attempts, 2)

    def test_dynamo_delivery_claims_use_conditional_atomic_updates(self) -> None:
        tables = fake_dynamo_tables()
        store = DynamoWorkspaceStore(tables)
        dedupe_key = "reminder:CASE-1:1"
        for attempt in range(1, 4):
            claim = store.claim(
                workspace_id="csub-demo",
                dedupe_key=dedupe_key,
                case_id="CASE-1",
                invite_id="invite-1",
                claimed_at=f"2026-07-2{attempt}T12:00:00",
                max_attempts=3,
            )
            assert claim is not None
            self.assertEqual(claim.attempts, attempt)
            self.assertTrue(
                store.settle(
                    workspace_id="csub-demo",
                    dedupe_key=dedupe_key,
                    attempts=attempt,
                    status="failed",
                )
            )
        self.assertIsNone(
            store.claim(
                workspace_id="csub-demo",
                dedupe_key=dedupe_key,
                case_id="CASE-1",
                invite_id="invite-1",
                claimed_at="2026-07-24T12:00:00+00:00",
                max_attempts=3,
            )
        )
        calls = tables["idempotency"].update_calls
        claim_calls = [call for call in calls if ":max_attempts" in call["ExpressionAttributeValues"]]
        settle_calls = [call for call in calls if ":status" in call["ExpressionAttributeValues"]]
        self.assertEqual(
            claim_calls[0]["Key"]["idempotency_key"],
            "csub-demo#delivery#reminder:CASE-1:1",
        )
        self.assertIn("attribute_not_exists(idempotency_key)", claim_calls[0]["ConditionExpression"])
        self.assertIn("attempts < :max_attempts", claim_calls[0]["ConditionExpression"])
        self.assertEqual(claim_calls[0]["ReturnValues"], "ALL_NEW")
        self.assertIn("#status = :pending", settle_calls[0]["ConditionExpression"])
        self.assertIn("attempts = :attempts", settle_calls[0]["ConditionExpression"])
        self.assertEqual(settle_calls[0]["ReturnValues"], "ALL_NEW")

    def test_naive_invite_and_event_timestamps_restore_and_project_as_utc(self) -> None:
        issued = self._issue_invite()
        snapshot = self.store.load_snapshot("csub-demo")
        assert snapshot is not None
        invite = next(
            item
            for item in snapshot["repository"]["records"]["invite"]
            if item["invite_id"] == issued["invite"]["invite_id"]
        )
        invite["issued_at"] = "2026-07-01T12:00:00"
        invite["expires_at"] = "2026-07-31T12:00:00"
        event = snapshot["repository"]["records"]["event"][0]
        event["occurred_at"] = "2026-07-02T12:00:00"
        restored = restore_api(
            snapshot,
            self.store.load_catalog("csub-demo"),
            workspace_id="csub-demo",
        )
        restored_invite = next(
            item
            for item in restored._vendor.list_invites()
            if item.invite_id == invite["invite_id"]
        )
        restored_event = restored._vendor_repository.get(
            "event", event["event_id"], workspace_id="csub-demo"
        )
        self.assertEqual(restored_invite.issued_at, "2026-07-01T12:00:00+00:00")
        self.assertEqual(restored_invite.expires_at, "2026-07-31T12:00:00+00:00")
        self.assertEqual(restored_event.occurred_at, "2026-07-02T12:00:00+00:00")

        tables = fake_dynamo_tables()
        DynamoWorkspaceStore(tables).save_snapshot("csub-demo", snapshot)
        projected_invite = next(iter(tables["invite"].items.values()))
        self.assertEqual(
            projected_invite["expires_at"],
            int(
                datetime.datetime(
                    2026, 7, 31, 12, tzinfo=datetime.timezone.utc
                ).timestamp()
            ),
        )
        projected_event = next(iter(tables["integration"].items.values()))
        self.assertEqual(
            projected_event["occurred_at"],
            int(
                datetime.datetime(
                    2026, 7, 2, 12, tzinfo=datetime.timezone.utc
                ).timestamp()
                * 1_000_000
            ),
        )

    def test_invalid_json_and_oversized_metadata_are_rejected(self) -> None:
        invalid, payload = self.call("POST", "/cases", body="{not-json")
        self.assertEqual(invalid["statusCode"], 400)
        self.assertEqual(payload["error"]["code"], "invalid_json")
        oversized, payload = self.call("POST", "/cases", body="x" * 1_048_577)
        self.assertEqual(oversized["statusCode"], 413)
        self.assertEqual(payload["error"]["code"], "payload_too_large")


if __name__ == "__main__":
    unittest.main()
