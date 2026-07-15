from __future__ import annotations

import contextlib
import hashlib
import io
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

import _bootstrap  # noqa: F401

from review_agent.lambda_api import (
    DynamoWorkspaceStore,
    InMemoryWorkspaceStore,
    SnapshotConflictError,
    create_handler,
    seed_workspace,
)


class FakeAwsError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": "synthetic failure"}}


class FakeTableMeta:
    def __init__(self, client: FakeTransactionClient) -> None:
        self.client = client


class FakeTable:
    def __init__(self, name: str, *key_fields: str) -> None:
        self.name = name
        self.key_fields = key_fields
        self.items: dict[tuple[object, ...], dict] = {}
        self.put_calls: list[dict] = []
        self.next_put_error_code: str | None = None
        self.meta: FakeTableMeta

    def _key(self, value: dict) -> tuple[object, ...]:
        return tuple(value[field] for field in self.key_fields)

    def get_item(self, *, Key: dict, **_kwargs) -> dict:
        item = self.items.get(self._key(Key))
        return {"Item": json.loads(json.dumps(item))} if item is not None else {}

    def put_item(self, *, Item: dict, **kwargs) -> None:
        self.put_calls.append({"Item": json.loads(json.dumps(Item)), **kwargs})
        if self.next_put_error_code is not None:
            code = self.next_put_error_code
            self.next_put_error_code = None
            raise FakeAwsError(code)
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


class FakeTransactionClient:
    def __init__(self, tables: dict[str, FakeTable]) -> None:
        self.tables = {table.name: table for table in tables.values()}
        self.next_error_code: str | None = None
        self.calls: list[list[dict]] = []

    @staticmethod
    def _value(value: dict) -> object:
        if "S" in value:
            return value["S"]
        if "N" in value:
            return int(value["N"])
        if "BOOL" in value:
            return value["BOOL"]
        raise AssertionError(f"unsupported synthetic DynamoDB value: {value}")

    @classmethod
    def _item(cls, item: dict) -> dict:
        return {key: cls._value(value) for key, value in item.items()}

    def transact_write_items(self, *, TransactItems: list[dict]) -> None:
        self.calls.append(json.loads(json.dumps(TransactItems)))
        if self.next_error_code is not None:
            code = self.next_error_code
            self.next_error_code = None
            raise FakeAwsError(code)

        check = TransactItems[0]["ConditionCheck"]
        check_table = self.tables[check["TableName"]]
        check_key = self._item(check["Key"])
        expected_revision = self._value(check["ExpressionAttributeValues"][":revision"])
        snapshot = check_table.items.get(check_table._key(check_key))
        if snapshot is None or snapshot.get("revision") != expected_revision:
            raise FakeAwsError("TransactionCanceledException")

        mutations: list[tuple[str, FakeTable, dict]] = []
        for entry in TransactItems[1:]:
            action = "Put" if "Put" in entry else "Delete"
            mutation = entry[action]
            table = self.tables[mutation["TableName"]]
            value = self._item(mutation["Item"] if action == "Put" else mutation["Key"])
            existing = table.items.get(table._key(value))
            incoming_revision = self._value(
                mutation["ExpressionAttributeValues"][":projection_revision"]
            )
            if (
                existing is not None
                and "projection_revision" in existing
                and existing["projection_revision"] > incoming_revision
            ):
                raise FakeAwsError("TransactionCanceledException")
            mutations.append((action, table, value))

        for action, table, value in mutations:
            if action == "Put":
                table.items[table._key(value)] = json.loads(json.dumps(value))
            else:
                table.items.pop(table._key(value), None)


def fake_dynamo_tables() -> dict[str, FakeTable]:
    keys = {
        "cases": ("case_id",),
        "vendor": ("vendor_id",),
        "product": ("product_id", "version"),
        "contact": ("contact_id",),
        "invite": ("token_hash",),
        "submission": ("submission_id", "case_id"),
        "review": ("case_id", "decision_version"),
        "profile": ("user_id", "version"),
        "integration": ("event_id", "occurred_at"),
        "audit": ("case_id", "sequence"),
        "idempotency": ("idempotency_key",),
    }
    tables = {name: FakeTable(name, *key_fields) for name, key_fields in keys.items()}
    client = FakeTransactionClient(tables)
    for table in tables.values():
        table.meta = FakeTableMeta(client)
    return tables


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

    def test_fresh_authenticated_records_issue_open_and_revoke_across_cold_start(self) -> None:
        _, vendor = self.call(
            "POST",
            "/vendors",
            body={"name": "Disposable Canary Vendor", "official_domain": "canary.example"},
        )
        _, product = self.call(
            "POST",
            "/vendor-products",
            body={"vendor_id": vendor["vendor_id"], "name": "Disposable Canary Product"},
        )
        _, contact = self.call(
            "POST",
            "/vendor-contacts",
            body={
                "vendor_id": vendor["vendor_id"],
                "name": "Sanitized Contact",
                "email": "vendor@example.edu",
            },
        )
        intake = {
            "product_name": product["name"],
            "vendor_name": vendor["name"],
            "requester": {
                "name": "Sanitized Requester",
                "email": "requester@example.edu",
                "department": "Library",
            },
            "use_case": "Disposable invitation reliability canary.",
            "expected_users": 1,
            "platform": ["web"],
            "data_classification": "public",
            "estimated_cost_usd": 0,
            "integrations": [],
            "uses_sso": False,
            "uses_ai": False,
            "classroom_or_public_use": False,
        }
        created_response, created = self.call("POST", "/cases", body=intake)
        self.assertEqual(created_response["statusCode"], 201)
        issue_response, issued = self.call(
            "POST",
            f"/cases/{created['case_id']}/invites",
            body={"contact_id": contact["contact_id"]},
        )
        self.assertEqual(issue_response["statusCode"], 201)
        token = issued["token"]
        self.assertNotIn(token, json.dumps(self.store.load_snapshot("csub-demo")))

        cold = create_handler(self.store, allowed_origins=[self.origin])
        opened = cold(
            self.event(
                "POST",
                "/vendor/invites/current/open",
                headers={"authorization": f"Bearer {token}"},
                authenticated=False,
                body={},
            ),
            None,
        )
        self.assertEqual(opened["statusCode"], 200)
        self.assertEqual(json.loads(opened["body"])["invite"]["status"], "opened")

        revoked_response, _ = self.call(
            "POST", f"/invites/{issued['invite']['invite_id']}/revoke", body={}
        )
        self.assertEqual(revoked_response["statusCode"], 200)
        terminal = cold(
            self.event(
                "GET",
                "/vendor/invites/current",
                headers={"authorization": f"Bearer {token}"},
                authenticated=False,
            ),
            None,
        )
        terminal_payload = json.loads(terminal["body"])
        self.assertEqual(terminal["statusCode"], 410)
        self.assertEqual(terminal_payload["error"]["code"], "invite_revoked")
        self.assertEqual(
            terminal_payload["error"]["correlation_id"],
            terminal["headers"]["X-Correlation-Id"],
        )

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

    def test_concurrent_rotation_persists_exactly_one_replacement(self) -> None:
        class RacingStore(InMemoryWorkspaceStore):
            barrier: threading.Barrier | None = None

            def load_snapshot(self, workspace_id: str):
                value = super().load_snapshot(workspace_id)
                barrier = self.barrier
                if barrier is not None:
                    barrier.wait(timeout=5)
                return value

        store = RacingStore()
        seed_workspace(store)
        handler_one = create_handler(store, allowed_origins=[self.origin])
        handler_two = create_handler(store, allowed_origins=[self.origin])

        def call(handler, method: str, path: str, *, body=None, headers=None, authenticated=True):
            response = handler(
                self.event(
                    method,
                    path,
                    body=body,
                    headers=headers,
                    authenticated=authenticated,
                ),
                None,
            )
            return response, json.loads(response["body"]) if response["body"] else None

        _, vendors = call(handler_one, "GET", "/vendors")
        vendor = next(item for item in vendors["items"] if item["name"] == "LabArchives, LLC")
        _, contact = call(
            handler_one,
            "POST",
            "/vendor-contacts",
            body={
                "vendor_id": vendor["vendor_id"],
                "name": "Concurrent Contact",
                "email": "concurrent@example.edu",
            },
        )
        _, issued = call(
            handler_one,
            "POST",
            "/cases/TR-260714-014/invites",
            body={"contact_id": contact["contact_id"]},
        )
        source_token = issued["token"]
        invite_id = issued["invite"]["invite_id"]
        store.barrier = threading.Barrier(2)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    call,
                    handler,
                    "POST",
                    f"/invites/{invite_id}/resend",
                    body={},
                )
                for handler in (handler_one, handler_two)
            ]
            results = [future.result() for future in futures]
        store.barrier = None

        self.assertEqual(sorted(response[0]["statusCode"] for response in results), [200, 409])
        conflict = next(payload for response, payload in results if response["statusCode"] == 409)
        self.assertEqual(conflict["error"]["code"], "concurrent_update")
        winner = next(payload for response, payload in results if response["statusCode"] == 200)
        replacement_token = winner["token"]

        terminal, payload = call(
            handler_one,
            "GET",
            "/vendor/invites/current",
            headers={"authorization": f"Bearer {source_token}"},
            authenticated=False,
        )
        self.assertEqual(terminal["statusCode"], 410)
        self.assertEqual(payload["error"]["code"], "invite_revoked")
        opened, payload = call(
            handler_two,
            "POST",
            "/vendor/invites/current/open",
            body={},
            headers={"authorization": f"Bearer {replacement_token}"},
            authenticated=False,
        )
        self.assertEqual(opened["statusCode"], 200)
        self.assertEqual(payload["invite"]["status"], "opened")
        snapshot = store.load_snapshot("csub-demo")
        replacements = [
            invite
            for invite in snapshot["repository"]["records"]["invite"]
            if invite.get("replaced_invite_id") == invite_id
        ]
        self.assertEqual(len(replacements), 1)

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

    def test_invite_listing_projects_expiry_without_bumping_revision(self) -> None:
        issued = self._issue_invite()
        snapshot = self.store.load_snapshot("csub-demo")
        revision = snapshot["persistence_revision"]
        invite = next(
            item
            for item in snapshot["repository"]["records"]["invite"]
            if item["invite_id"] == issued["invite"]["invite_id"]
        )
        invite["status"] = "issued"
        invite["expires_at"] = "2000-01-01T00:00:00+00:00"
        snapshot["persistence_revision"] = revision + 1
        self.store.save_snapshot(
            "csub-demo",
            snapshot,
            expected_revision=revision,
        )
        expected_revision = revision + 1

        first, payload = self.call("GET", "/cases/TR-260714-014/invites")
        self.assertEqual(first["statusCode"], 200)
        projected = next(
            item for item in payload["items"] if item["invite_id"] == invite["invite_id"]
        )
        self.assertEqual(projected["status"], "expired")
        self.assertEqual(
            self.store.load_snapshot("csub-demo")["persistence_revision"],
            expected_revision,
        )

        second, second_payload = self.call("GET", "/cases/TR-260714-014/invites")
        self.assertEqual(second["statusCode"], 200)
        self.assertEqual(second_payload, payload)
        self.assertEqual(
            self.store.load_snapshot("csub-demo")["persistence_revision"],
            expected_revision,
        )

    def test_dynamo_snapshot_write_always_sends_condition_and_maps_conflict(self) -> None:
        tables = fake_dynamo_tables()
        store = DynamoWorkspaceStore(tables)
        cases = tables["cases"]
        snapshot = {
            "persistence_revision": 1,
            "repository": {"records": {}},
            "cases": {},
            "connector": {},
        }

        def options(call: dict) -> dict:
            return {key: value for key, value in call.items() if key != "Item"}

        store.save_snapshot("csub-demo", snapshot, expected_revision=None)
        self.assertEqual(
            options(cases.put_calls[-1]),
            {
                "ConditionExpression": "attribute_not_exists(#case_id)",
                "ExpressionAttributeNames": {"#case_id": "case_id"},
            },
        )

        store.save_snapshot("csub-demo", snapshot, expected_revision=0)
        self.assertEqual(
            options(cases.put_calls[-1]),
            {
                "ConditionExpression": (
                    "attribute_exists(#case_id) AND "
                    "(attribute_not_exists(#revision) OR #revision = :expected_revision)"
                ),
                "ExpressionAttributeNames": {
                    "#case_id": "case_id",
                    "#revision": "revision",
                },
                "ExpressionAttributeValues": {":expected_revision": 0},
            },
        )

        snapshot["persistence_revision"] = 8
        store.save_snapshot("csub-demo", snapshot, expected_revision=7)
        self.assertEqual(
            options(cases.put_calls[-1]),
            {
                "ConditionExpression": "#revision = :expected_revision",
                "ExpressionAttributeNames": {"#revision": "revision"},
                "ExpressionAttributeValues": {":expected_revision": 7},
            },
        )

        cases.next_put_error_code = "ConditionalCheckFailedException"
        with self.assertRaises(SnapshotConflictError):
            store.save_snapshot("csub-demo", snapshot, expected_revision=7)

    def test_dynamo_projection_transactions_reject_stale_order_and_are_idempotent(self) -> None:
        tables = fake_dynamo_tables()
        store = DynamoWorkspaceStore(tables)
        older = {
            "persistence_revision": 1,
            "repository": {
                "records": {
                    "vendor": [
                        {"vendor_id": "vendor-kept", "name": "Old name"},
                        {"vendor_id": "vendor-removed", "name": "Removed later"},
                    ]
                }
            },
            "cases": {},
            "connector": {},
        }
        newer = {
            "persistence_revision": 2,
            "repository": {
                "records": {
                    "vendor": [{"vendor_id": "vendor-kept", "name": "New name"}]
                }
            },
            "cases": {},
            "connector": {},
        }

        store.save_snapshot("csub-demo", older, expected_revision=None)
        store.save_snapshot("csub-demo", newer, expected_revision=1)
        projected = {
            key: json.loads(json.dumps(value)) for key, value in tables["vendor"].items.items()
        }

        with self.assertRaises(FakeAwsError):
            store._write_projections("csub-demo", older)
        self.assertEqual(tables["vendor"].items, projected)
        self.assertNotIn(("csub-demo#vendor#vendor-removed",), tables["vendor"].items)
        kept = tables["vendor"].items[("csub-demo#vendor#vendor-kept",)]
        self.assertEqual(json.loads(kept["payload"])["name"], "New name")
        self.assertEqual(kept["projection_revision"], 2)

        store._write_projections("csub-demo", newer)
        self.assertEqual(tables["vendor"].items, projected)

    def test_dynamo_projection_failure_does_not_fail_committed_http_mutation(self) -> None:
        tables = fake_dynamo_tables()
        store = DynamoWorkspaceStore(tables)
        seed_workspace(store)
        handler = create_handler(store, allowed_origins=[self.origin])
        tables["cases"].meta.client.next_error_code = "InternalServerError"

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            response = handler(
                self.event(
                    "POST",
                    "/vendors",
                    body={"name": "Committed Vendor", "official_domain": "vendor.example"},
                ),
                None,
            )

        payload = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 201)
        snapshot = store.load_snapshot("csub-demo")
        vendors = snapshot["repository"]["records"]["vendor"]
        self.assertTrue(any(item["vendor_id"] == payload["vendor_id"] for item in vendors))
        projected_ids = {
            json.loads(item["payload"])["vendor_id"] for item in tables["vendor"].items.values()
        }
        self.assertNotIn(payload["vendor_id"], projected_ids)
        logs = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertIn(
            {
                "event_type": "projection_write_failed",
                "revision": snapshot["persistence_revision"],
                "status": 202,
            },
            logs,
        )

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
