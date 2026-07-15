"""HTTP routing smoke test for the complete issue #19 API surface."""

from __future__ import annotations

import json
import threading
import unittest
from typing import Any, cast
from urllib.parse import quote
from urllib.request import Request, urlopen

import _bootstrap  # noqa: F401

from review_agent.api import LocalReviewApi
from review_agent.server import create_server


class VendorHttpRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = LocalReviewApi(seed_demo=False)
        created = self.api.create_case(
            {
                "product_name": "Route Product",
                "vendor_name": "Route Vendor",
                "requester": {"name": "Requester", "email": "requester@example.edu"},
                "use_case": "Sanitized route test",
                "expected_users": 1,
                "platform": ["web"],
                "data_classification": "public",
                "estimated_cost_usd": 0,
            }
        )
        self.case_id = created["case_id"]
        vendor_id = self.api.list_vendors()["items"][0]["vendor_id"]
        contact = self.api.create_vendor_contact(
            {"vendor_id": vendor_id, "name": "Contact", "email": "contact@route.example"}
        )
        self.contact_id = contact["contact_id"]
        self.server = create_server(self.api, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base = f"http://{host}:{port}/api"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path: str, method: str = "GET", payload: dict | None = None):
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        with urlopen(
            Request(self.base + path, data=body, method=method, headers=headers),
            timeout=2,
        ) as response:
            return response.status, json.loads(response.read())

    def test_complete_vendor_and_operator_route_surface(self) -> None:
        status, invite = self.request(
            f"/cases/{self.case_id}/invites",
            "POST",
            {"contact_id": self.contact_id},
        )
        self.assertEqual(status, 201)
        token = quote(invite["token"], safe="")
        self.assertNotIn("token_hash", invite["invite"])
        # A brand-new invite is not yet due a reminder; the sweep and the
        # reviewer reminder controls are reachable over HTTP.
        sweep_status, sweep = self.request("/reminders/run", "POST", {})
        self.assertEqual(sweep_status, 200)
        self.assertEqual(sweep["count"], 0)
        history_status, history = self.request(f"/cases/{self.case_id}/reminders")
        self.assertEqual(history_status, 200)
        self.assertEqual(history, {"case_id": self.case_id, "paused": False, "items": []})
        self.assertEqual(
            self.request(f"/cases/{self.case_id}/reminders/pause", "POST", {})[1]["paused"],
            True,
        )
        self.assertEqual(
            self.request(f"/cases/{self.case_id}/reminders/resume", "POST", {})[1]["paused"],
            False,
        )
        self.assertEqual(self.request(f"/vendor/invites/{token}")[0], 200)
        self.assertEqual(self.request(f"/vendor/invites/{token}/open", "POST", {})[0], 200)
        self.assertEqual(
            self.request(
                f"/vendor/invites/{token}/evidence",
                "POST",
                {
                    "filename": "vpat-report.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 100,
                    "sha256": "a" * 64,
                },
            )[0],
            200,
        )
        self.assertEqual(
            self.request(
                f"/vendor/invites/{token}/trust-center",
                "POST",
                {"trust_center_url": "https://trust.route.example"},
            )[0],
            200,
        )
        # Staged intake: analysis must run before questions/answers are exposed.
        self.assertEqual(self.request(f"/vendor/invites/{token}/analyze", "POST", {})[0], 200)
        _, questions = self.request(f"/vendor/invites/{token}/questions")
        self.assertTrue(questions["intake_analysis_complete"])
        # Content-validation findings routes (issue #36): none for this clean upload.
        findings_status, findings = self.request(f"/vendor/invites/{token}/findings")
        self.assertEqual(findings_status, 200)
        self.assertEqual(findings["items"], [])
        case_findings_status, case_findings = self.request(f"/cases/{self.case_id}/evidence-findings")
        self.assertEqual(case_findings_status, 200)
        self.assertEqual(case_findings["items"], [])
        answers = {item["requirement_id"]: "Sanitized answer" for item in questions["items"]}
        if answers:
            self.assertEqual(
                self.request(f"/vendor/invites/{token}/answers", "POST", {"answers": answers})[0],
                200,
            )
        status_code, review_status = self.request(f"/vendor/invites/{token}/status")
        self.assertEqual(status_code, 200)
        self.assertIn(review_status["review_stage"], {"collecting_evidence", "under_review"})
        self.assertTrue(review_status["checklist"])
        self.assertEqual(self.request(f"/vendor/invites/{token}/finalize", "POST", {})[0], 200)
        # The status projection stays readable after the submission is finalized.
        status_code, submitted_status = self.request(f"/vendor/invites/{token}/status")
        self.assertEqual(status_code, 200)
        self.assertEqual(submitted_status["submission_status"], "finalized")
        self.assertEqual(submitted_status["review_stage"], "under_review")
        state = self.api._cases[self.case_id].state
        state.human_decision = cast(Any, object())
        state.write_preview = cast(Any, object())
        state.write_result = cast(Any, object())
        state.idempotency_key = "stale"
        self.assertEqual(self.request(f"/cases/{self.case_id}/review-runs", "POST", {})[0], 201)
        self.assertIsNone(state.human_decision)
        self.assertIsNone(state.write_preview)
        self.assertIsNone(state.write_result)
        self.assertIsNone(state.idempotency_key)
        self.assertEqual(self.request(f"/cases/{self.case_id}/review-runs")[0], 200)
        self.assertEqual(self.request(f"/cases/{self.case_id}/invites")[0], 200)
        self.assertEqual(self.request("/review-profiles")[0], 200)
        profile_payload = {
            "profile_key": "route-profile",
            "criteria": [
                {
                    "requirement_id": "ROUTE.REQ.001",
                    "question": "Provide route evidence.",
                    "source_citation": {"source_id": "fixture:route"},
                    "expected_evidence": ["document"],
                    "output_fields": ["summary"],
                    "remediation_guidance": "Provide the document.",
                }
            ],
        }
        status, profile = self.request("/review-profiles", "POST", profile_payload)
        self.assertEqual(status, 201)
        profile_id = profile["profile_version_id"]
        self.assertEqual(
            self.request(
                f"/review-profiles/{profile_id}/fixture-test",
                "POST",
                {"fixtures": [{}]},
            )[0],
            200,
        )
        self.assertEqual(
            self.request(f"/review-profiles/{profile_id}/activate", "POST", {})[0],
            200,
        )
        self.assertEqual(
            self.request(f"/review-profiles/{profile_id}/rollback", "POST", {})[0],
            200,
        )
        self.assertEqual(self.request("/catalog/search?q=Zoom%20Workplace")[0], 200)
        self.assertEqual(self.request("/servicenow/imports/RITM0098200/preview")[0], 200)
        self.assertEqual(self.request("/integration-events")[0], 200)

        status, vendor = self.request(
            "/vendors", "POST", {"name": "Disposable Vendor", "official_domain": "dispose.example"}
        )
        self.assertEqual(status, 201)
        self.assertEqual(self.request(f"/vendors/{vendor['vendor_id']}")[0], 200)
        self.assertEqual(
            self.request(
                f"/vendors/{vendor['vendor_id']}",
                "PATCH",
                {"name": "Renamed Vendor"},
            )[0],
            200,
        )
        self.assertEqual(self.request(f"/vendors/{vendor['vendor_id']}", "DELETE")[0], 200)


if __name__ == "__main__":
    unittest.main()
