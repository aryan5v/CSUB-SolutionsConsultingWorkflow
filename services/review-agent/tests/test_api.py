from __future__ import annotations

import copy
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import _bootstrap  # noqa: F401

from review_agent.api import LocalApiError, LocalReviewApi  # noqa: E402
from review_agent.contracts.schema import ContractValidationError, validate  # noqa: E402
from review_agent.server import create_server  # noqa: E402


class LocalReviewApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = LocalReviewApi()

    def test_seeded_queue_covers_match_review_and_safe_escalation(self) -> None:
        response = self.api.list_review_queue()
        self.assertTrue(response["simulated"])
        self.assertEqual(len(response["items"]), 3)
        by_id = {item["case_id"]: item for item in response["items"]}

        active = by_id["TR-260714-014"]
        self.assertEqual(active["state"]["status"], "awaiting_match_confirmation")
        self.assertEqual(active["state"]["software_candidates"][0]["match_method"], "fuzzy")
        self.assertTrue(active["state"]["software_candidates"][0]["requires_confirmation"])
        self.assertEqual(by_id["TR-260714-018"]["state"]["status"], "awaiting_review")
        self.assertEqual(by_id["TR-260714-011"]["state"]["status"], "escalated")

    def test_response_contract_rejects_malformed_nested_writeback_and_coerced_const(self) -> None:
        queue = self.api.list_review_queue()
        malformed = copy.deepcopy(queue)
        malformed["items"][0]["state"]["write_preview"] = {"unexpected": "not a preview"}
        with self.assertRaises(ContractValidationError):
            validate(malformed, "review-queue")

        coerced = copy.deepcopy(queue)
        coerced["simulated"] = 1
        with self.assertRaises(ContractValidationError):
            validate(coerced, "review-queue")

    def test_medium_case_resumes_then_previews_and_commits_once(self) -> None:
        waiting = self.api.analyze_case("TR-260714-014")
        candidate_id = waiting["state"]["software_candidates"][0]["record_id"]
        with self.assertRaises(LocalApiError) as unattributed:
            self.api.analyze_case("TR-260714-014", confirmed_match_id=candidate_id)
        self.assertEqual(unattributed.exception.code, "reviewer_required")
        analyzed = self.api.analyze_case(
            "TR-260714-014",
            confirmed_match_id=candidate_id,
            reviewer_id="alex.reviewer@example.edu",
        )
        self.assertEqual(analyzed["state"]["status"], "awaiting_review")
        self.assertEqual(analyzed["state"]["policy_result"]["risk_route"], "medium")
        self.assertEqual(analyzed["state"]["draft_packet"]["packet_type"], "medium_risk")

        reviewed = self.api.review_case(
            "TR-260714-014",
            {
                "case_id": "TR-260714-014",
                "decision_version": 2,
                "reviewer_id": "alex.reviewer@example.edu",
                "action": "approve",
                "decided_at": "2026-07-14T20:30:00+00:00",
                "edits": [
                    {
                        "section_key": "committee_routing",
                        "body": "Reviewer-edited committee recommendation.",
                    }
                ],
            },
        )
        self.assertEqual(reviewed["state"]["human_decision"]["action"], "approve")
        self.assertEqual(reviewed["state"]["human_decision"]["decision_version"], 2)
        self.assertEqual(reviewed["state"]["draft_packet"]["packet_version"], 2)
        self.assertEqual(reviewed["state"]["human_edits"][0]["section_key"], "committee_routing")
        committee = next(
            section
            for section in reviewed["state"]["draft_packet"]["sections"]
            if section["key"] == "committee_routing"
        )
        self.assertEqual(committee["body"], "Reviewer-edited committee recommendation.")
        confirmed_event = next(
            event for event in reviewed["audit_events"] if event["event_type"] == "match.confirmed"
        )
        self.assertEqual(confirmed_event["actor_id"], "alex.reviewer@example.edu")

        previewed = self.api.preview_servicenow("TR-260714-014")
        preview = previewed["state"]["write_preview"]
        self.assertTrue(preview["simulated"])
        self.assertEqual(preview["decision_version"], 2)
        self.assertEqual(preview["packet_version"], 2)
        self.assertEqual(preview["packet_sha256"], reviewed["state"]["draft_packet"]["sha256"])
        self.assertEqual(preview["expected_record_version"], 1)
        self.assertEqual(preview["record_id"], "RITM0012846")
        self.assertEqual(previewed["state"]["status"], "writeback")
        self.assertEqual(previewed["queue_item"]["stage"], "Write-back preview")
        preview_event = next(
            event for event in previewed["audit_events"] if event["event_type"] == "servicenow.previewed"
        )
        self.assertEqual(preview_event["actor_id"], "alex.reviewer@example.edu")
        self.assertEqual(preview_event["decision_version"], 2)

        packet = self.api._cases["TR-260714-014"].state.draft_packet
        assert packet is not None
        original_version = packet.packet_version
        original_body = packet.sections[-1].body
        original_hash = packet.sha256
        packet.packet_version += 1
        packet.sections[-1].body = "Changed after preview"
        packet.sha256 = packet.compute_sha256()
        with self.assertRaises(LocalApiError) as stale_packet:
            self.api.commit_servicenow(
                "TR-260714-014",
                {"second_confirmation": True, "expected_version": 1},
            )
        self.assertEqual(stale_packet.exception.status, 409)
        self.assertEqual(stale_packet.exception.code, "preview_mismatch")
        packet.packet_version = original_version
        packet.sections[-1].body = original_body
        packet.sha256 = original_hash

        with self.assertRaises(LocalApiError) as mismatched:
            self.api.commit_servicenow(
                "TR-260714-014",
                {"second_confirmation": True, "expected_version": 2},
            )
        self.assertEqual(mismatched.exception.status, 409)
        self.assertEqual(mismatched.exception.code, "preview_mismatch")

        with self.assertRaises(LocalApiError) as refused:
            self.api.commit_servicenow(
                "TR-260714-014",
                {"second_confirmation": False, "expected_version": 1},
            )
        self.assertEqual(refused.exception.status, 403)

        committed = self.api.commit_servicenow(
            "TR-260714-014",
            {"second_confirmation": True, "expected_version": 1},
        )
        result = committed["state"]["write_result"]
        self.assertTrue(result["committed"])
        self.assertFalse(result["duplicate_suppressed"])
        self.assertIsNotNone(result["attachment"])
        commit_event = next(
            event for event in committed["audit_events"] if event["event_type"] == "servicenow.committed"
        )
        self.assertEqual(commit_event["actor_id"], "alex.reviewer@example.edu")
        self.assertEqual(commit_event["decision_version"], 2)

        replay = self.api.commit_servicenow(
            "TR-260714-014",
            {"second_confirmation": True, "expected_version": 1},
        )
        self.assertTrue(replay["state"]["write_result"]["duplicate_suppressed"])

    def test_invalid_review_requests_are_atomic_and_cannot_spoof_edit_reviewer(self) -> None:
        before = self.api.get_packet("TR-260714-018")
        missing_reviewer = {
            "case_id": "TR-260714-018",
            "decision_version": 2,
            "action": "request_info",
            "decided_at": "2026-07-14T20:34:00+00:00",
            "edits": [{"section_key": "recommendation", "body": "UNATTRIBUTED MUTATION"}],
        }
        with self.assertRaises(LocalApiError) as invalid:
            self.api.review_case("TR-260714-018", missing_reviewer)
        self.assertEqual(invalid.exception.status, 400)
        self.assertEqual(self.api.get_packet("TR-260714-018"), before)
        self.assertEqual(self.api.get_state("TR-260714-018")["human_edits"], [])

        spoofed = {
            **missing_reviewer,
            "reviewer_id": "casey.reviewer@example.edu",
            "edits": [
                {
                    "section_key": "recommendation",
                    "body": "SPOOFED MUTATION",
                    "reviewer_id": "spoofed@example.edu",
                }
            ],
        }
        with self.assertRaises(LocalApiError) as spoof:
            self.api.review_case("TR-260714-018", spoofed)
        self.assertEqual(spoof.exception.status, 400)
        self.assertEqual(self.api.get_packet("TR-260714-018"), before)
        self.assertEqual(self.api.get_state("TR-260714-018")["human_edits"], [])

    def test_low_risk_recommendation_edit_is_versioned(self) -> None:
        reviewed = self.api.review_case(
            "TR-260714-018",
            {
                "case_id": "TR-260714-018",
                "decision_version": 2,
                "reviewer_id": "alex.reviewer@example.edu",
                "action": "request_info",
                "decided_at": "2026-07-14T20:35:00+00:00",
                "edits": [
                    {
                        "section_key": "recommendation",
                        "body": "Reviewer-edited low-risk recommendation.",
                    }
                ],
            },
        )
        packet = reviewed["state"]["draft_packet"]
        self.assertEqual(packet["packet_version"], 2)
        self.assertEqual(packet["sections"][0]["key"], "recommendation")
        self.assertEqual(packet["sections"][0]["body"], "Reviewer-edited low-risk recommendation.")

    def test_escalation_cannot_be_approved(self) -> None:
        with self.assertRaises(LocalApiError) as refused:
            self.api.review_case(
                "TR-260714-011",
                {
                    "case_id": "TR-260714-011",
                    "decision_version": 1,
                    "reviewer_id": "alex.reviewer@example.edu",
                    "action": "approve",
                    "decided_at": "2026-07-14T20:40:00+00:00",
                },
            )
        self.assertEqual(refused.exception.status, 403)
        self.assertEqual(refused.exception.code, "escalation_locked")

        requested = self.api.review_case(
            "TR-260714-011",
            {
                "case_id": "TR-260714-011",
                "decision_version": 1,
                "reviewer_id": "alex.reviewer@example.edu",
                "action": "request_info",
                "decided_at": "2026-07-14T20:41:00+00:00",
            },
        )
        self.assertEqual(requested["state"]["status"], "escalated")
        self.assertIsNone(requested["state"]["draft_packet"])
        self.assertEqual(requested["queue_item"]["status"], "Needs evidence")
        self.assertEqual(requested["queue_item"]["stage"], "Safe escalation")

    def test_case_intake_requires_explicit_fields(self) -> None:
        with self.assertRaises(LocalApiError) as invalid:
            self.api.create_case({"product_name": "Incomplete"})
        self.assertEqual(invalid.exception.status, 400)

        created = self.api.create_case(
            {
                "product_name": "Sanitized Calendar",
                "vendor_name": "Example Vendor",
                "requester": {
                    "name": "Sample Requester",
                    "email": "requester@example.edu",
                    "department": "Library",
                },
                "use_case": "Public event scheduling.",
                "expected_users": 12,
                "platform": ["web"],
                "data_classification": "public",
                "estimated_cost_usd": 0,
                "integrations": [],
                "uses_sso": False,
                "uses_ai": False,
                "classroom_or_public_use": True,
            }
        )
        unsafe = dict(created["state"]["case_input"])
        unsafe["estimated_cost_usd"] = float("nan")
        with self.assertRaises(LocalApiError) as nonfinite:
            self.api.create_case(unsafe)
        self.assertEqual(nonfinite.exception.status, 400)

        case_id = created["case_id"]
        analyzed = self.api.analyze_case(case_id)
        self.assertIn(analyzed["state"]["status"], {"awaiting_review", "escalated"})


class LocalHttpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = create_server(LocalReviewApi(), port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base = f"http://{host}:{port}/api"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
    ):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request_headers = dict(headers or {})
        if body:
            request_headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base}{path}",
            data=body,
            method=method,
            headers=request_headers,
        )
        with urlopen(request, timeout=2) as response:
            return response.status, response.headers, response.read().decode("utf-8")

    def test_queue_and_sse_routes(self) -> None:
        status, _, body = self.request("/review-queue")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["items"]), 3)

        status, headers, body = self.request("/cases/TR-260714-014/stream")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "text/event-stream")
        self.assertIn("event: state", body)
        self.assertIn('"awaiting_match_confirmation"', body)

    def test_nonfinite_json_number_is_rejected(self) -> None:
        payload = {
            "product_name": "Unsafe Number",
            "vendor_name": "Example Vendor",
            "requester": {"name": "Sample", "email": "sample@example.edu"},
            "use_case": "Sanitized test",
            "expected_users": 1,
            "platform": ["web"],
            "data_classification": "public",
            "estimated_cost_usd": float("nan"),
        }
        with self.assertRaises(HTTPError) as response:
            self.request("/cases", method="POST", payload=payload)
        error = response.exception
        body = json.loads(error.read().decode("utf-8"))
        error.close()
        self.assertEqual(error.code, 400)
        self.assertEqual(body["error"]["code"], "invalid_json")

    def test_errors_are_structured_without_internal_details(self) -> None:
        with self.assertRaises(HTTPError) as response:
            self.request("/cases/missing/packet")
        error = response.exception
        self.assertEqual(error.code, 404)
        payload = json.loads(error.read().decode("utf-8"))
        error.close()
        self.assertEqual(payload["error"]["code"], "case_not_found")

    def test_cors_only_echoes_allowlisted_origins_as_constants(self) -> None:
        _, allowed_headers, _ = self.request(
            "/review-queue", headers={"Origin": "http://localhost:5173"}
        )
        self.assertEqual(
            allowed_headers.get("Access-Control-Allow-Origin"),
            "http://localhost:5173",
        )

        _, rejected_headers, _ = self.request(
            "/review-queue", headers={"Origin": "https://attacker.example"}
        )
        self.assertIsNone(rejected_headers.get("Access-Control-Allow-Origin"))


if __name__ == "__main__":
    unittest.main()
