"""Focused tests for the issue #27 golden-path backend.

Covers: catalog reconciliation/seed count, real PDF evidence packet bytes and
artifact metadata, protected Lambda ``GET /cases/{id}/packet/pdf`` and
``GET /catalog`` pagination/search, one-rerun limit and custom instructions,
persisted lifecycle transitions, truthful Slack notifications, the structured
model invoker (one repair then explicit failure), and live Bedrock model
injection into the research/security/accessibility path.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from review_agent.adapters.model import (
    BedrockModelClient,
    DeterministicModelClient,
    ModelStructureError,
    invoke_structured,
)
from review_agent.api import LocalReviewApi
from review_agent.config import AppConfig, ModelConfig
from review_agent.contracts.common import Citation, CitationScope, SourceCoordinates
from review_agent.contracts.packet import Packet, PacketSection, PacketType
from review_agent.contracts.vendor import DEFAULT_WORKSPACE_ID
from review_agent.ingestion.software_workbook import RowsWorkbookReader, normalize_workbook
from review_agent.lambda_api import (
    FileWorkspaceStore,
    InMemoryWorkspaceStore,
    create_handler,
    seed_workspace,
)
from review_agent.packet.pdf import render_packet_pdf
from review_agent.profiles.service import ReviewProfileService
from review_agent.samples import low_risk_case, medium_risk_case
from review_agent.vendor.repository import InMemoryVendorRepository
from review_agent.vendor.service import VendorBackend, VendorBackendError

APPROVE = "approve"


class _ScriptedModel:
    """A ModelClient stub returning queued replies for invoke_structured tests."""

    def __init__(self, replies: list[dict]) -> None:
        self._replies = list(replies)
        self.calls = 0

    def complete_json(self, *, system: str, prompt: str, context: dict) -> dict:
        self.calls += 1
        return self._replies.pop(0)


class _FakeConverse:
    def __init__(self, reply_text: str) -> None:
        self.reply_text = reply_text
        self.calls = 0

    def converse(self, **_kwargs):
        self.calls += 1
        return {"output": {"message": {"content": [{"text": self.reply_text}]}}}


class _StubNotifier:
    def __init__(self, delivery: dict) -> None:
        self._delivery = delivery
        self.calls: list[str] = []

    def notify(self, *, event_type: str, summary: str, detail=None) -> dict:
        self.calls.append(event_type)
        return dict(self._delivery)


def _wide_workbook(rows: int, columns: int) -> RowsWorkbookReader:
    base = [
        "Identity",
        "Vendor",
        "Short Name",
        "Availiable to",
        "Platform",
        "Department",
        "Assignment Group",
        "Support",
        "Location",
        "License Type",
        "Supported Software",
        "Campus license",
    ]
    headers = base + [f"Extra {i}" for i in range(columns - len(base))]
    data = []
    for i in range(rows):
        row = {header: f"{header}-{i}" for header in headers}
        row["Identity"] = f"Synthetic Product {i:04d}"
        row["Vendor"] = f"Vendor {i % 25}"
        data.append(row)
    return RowsWorkbookReader(headers, data)


class CatalogSeedReconciliationTests(unittest.TestCase):
    def test_982_rows_reconcile_and_seed_three_demo_cases(self) -> None:
        reader = _wide_workbook(rows=982, columns=18)
        normalized = normalize_workbook(reader, source_id="operator:test", workspace_id=DEFAULT_WORKSPACE_ID)
        report = normalized.reconciliation
        self.assertTrue(report.rows_reconcile)
        self.assertTrue(report.columns_reconcile)
        self.assertEqual(report.output_rows, 982)
        self.assertEqual(report.preserved_columns, 18)
        entries = normalized.catalog_entries()
        self.assertEqual(len(entries), 982)

        store = InMemoryWorkspaceStore()
        result = seed_workspace(store, catalog_entries=entries)
        self.assertEqual(result["catalog_records"], 982)
        self.assertEqual(result["seeded_cases"], 3)
        self.assertFalse(result["catalog_membership_is_approval"])
        self.assertEqual(len(store.load_catalog(DEFAULT_WORKSPACE_ID)), 982)

    def test_file_workspace_store_seeds_without_boto3(self) -> None:
        reader = _wide_workbook(rows=982, columns=18)
        entries = normalize_workbook(
            reader, source_id="operator:test", workspace_id=DEFAULT_WORKSPACE_ID
        ).catalog_entries()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workspace.json"
            store = FileWorkspaceStore(path)
            result = seed_workspace(store, catalog_entries=entries)
            self.assertEqual(result["catalog_records"], 982)
            # A fresh instance restores the same persisted state (durable file).
            reopened = FileWorkspaceStore(path)
            self.assertEqual(len(reopened.load_catalog(DEFAULT_WORKSPACE_ID)), 982)
            self.assertIsNotNone(reopened.load_snapshot(DEFAULT_WORKSPACE_ID))


class PacketPdfTests(unittest.TestCase):
    def test_render_packet_pdf_is_valid_signature_and_eof(self) -> None:
        api = LocalReviewApi(seed_demo=True)
        packet = api._cases["TR-260714-018"].state.draft_packet
        self.assertIsNotNone(packet)
        pdf = render_packet_pdf(packet, title="VETTED Evidence Packet — Sticky Notes Widget")
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"VETTED Evidence Packet", pdf)
        self.assertIn(b"Material citations", pdf)
        self.assertIn(b"Sticky Notes Widget", pdf)

    def test_render_packet_pdf_embeds_material_citations(self) -> None:
        citation = Citation(
            claim="Encryption in transit and at rest is required",
            source=SourceCoordinates(source_id="policy:sec-1", filename="security-profile"),
            scope=CitationScope.POLICY,
            verified=True,
        )
        packet = Packet(
            packet_id="CASE-CIT-packet",
            case_id="CASE-CIT",
            packet_version=1,
            packet_type=PacketType.MEDIUM_RISK,
            sections=[
                PacketSection(
                    key="security_summary",
                    title="Security summary",
                    body="Vendor provides SOC 2 evidence.",
                    citations=[citation],
                )
            ],
            citations=[citation],
        )
        packet.sha256 = packet.compute_sha256()
        pdf = render_packet_pdf(packet)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertIn(b"policy:sec-1", pdf)
        self.assertIn(b"Encryption in transit", pdf)

    def test_get_packet_pdf_stores_bytes_and_returns_metadata(self) -> None:
        api = LocalReviewApi(seed_demo=True)
        meta = api.get_packet_pdf("TR-260714-018")
        self.assertEqual(meta["case_id"], "TR-260714-018")
        self.assertTrue(meta["view_url"].startswith("/generated/"))
        self.assertGreater(meta["size_bytes"], 0)
        self.assertEqual(len(meta["pdf_sha256"]), 64)
        self.assertIsInstance(meta["citations"], list)
        self.assertTrue(meta["simulated_storage"])
        stored = api._packet_storage.get_object(key=meta["key"])
        self.assertTrue(stored.startswith(b"%PDF-"))
        self.assertEqual(len(stored), meta["size_bytes"])


class LambdaRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryWorkspaceStore()
        seed_workspace(self.store)
        self.handler = create_handler(self.store)

    def _event(self, method: str, path: str, *, query: str = "", authenticated: bool = True) -> dict:
        event = {
            "version": "2.0",
            "routeKey": f"{method} {path}",
            "rawPath": path,
            "rawQueryString": query,
            "headers": {},
            "requestContext": {"http": {"method": method, "path": path}},
            "isBase64Encoded": False,
        }
        if authenticated:
            event["requestContext"]["authorizer"] = {
                "jwt": {"claims": {"email": "reviewer@example.edu", "custom:workspace_id": "csub-demo"}}
            }
        return event

    def _call(self, method: str, path: str, **kwargs):
        response = self.handler(self._event(method, path, **kwargs), None)
        payload = json.loads(response["body"]) if response["body"] else None
        return response, payload

    def test_packet_pdf_route_requires_auth_and_returns_pdf_metadata(self) -> None:
        unauth, _ = self._call("GET", "/cases/TR-260714-018/packet/pdf", authenticated=False)
        self.assertEqual(unauth["statusCode"], 401)

        response, payload = self._call("GET", "/cases/TR-260714-018/packet/pdf")
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(len(payload["pdf_sha256"]), 64)
        self.assertTrue(payload["view_url"].startswith("/generated/"))
        self.assertEqual(payload["content_type"], "application/pdf")
        self.assertGreater(payload["size_bytes"], 0)

    def test_catalog_listing_pagination_and_search(self) -> None:
        response, payload = self._call("GET", "/catalog", query="limit=2&offset=0")
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(payload["limit"], 2)
        self.assertEqual(payload["offset"], 0)
        self.assertFalse(payload["catalog_membership_is_approval"])
        self.assertLessEqual(len(payload["items"]), 2)
        total = payload["total"]
        self.assertGreaterEqual(total, 1)
        # Every catalog field is preserved on each item.
        self.assertIn("raw_values", payload["items"][0])
        self.assertIn("supported_software", payload["items"][0])

        # Offset paging does not exceed the total.
        page2, page2_payload = self._call("GET", "/catalog", query=f"limit=2&offset={total}")
        self.assertEqual(page2["statusCode"], 200)
        self.assertEqual(page2_payload["items"], [])

        # Optional q filter narrows results and never requires a query.
        filtered_response, filtered = self._call("GET", "/catalog", query="q=LabArchives")
        self.assertEqual(filtered_response["statusCode"], 200)
        self.assertTrue(all("labarchives" in item["canonical_name"].lower() for item in filtered["items"]))

    def test_catalog_listing_rejects_bad_pagination(self) -> None:
        bad, payload = self._call("GET", "/catalog", query="limit=0")
        self.assertEqual(bad["statusCode"], 400)
        self.assertEqual(payload["error"]["code"], "validation_error")


class ReRunLimitTests(unittest.TestCase):
    def _backend(self) -> tuple[VendorBackend, str]:
        repository = InMemoryVendorRepository()
        profiles = ReviewProfileService(repository)
        criteria = [
            {
                "requirement_id": "SEC.DATA.001",
                "question": "Describe encryption.",
                "source_citation": {"source_id": "policy:security"},
                "expected_evidence": ["SOC 2"],
                "output_fields": ["security_summary"],
                "remediation_guidance": "Provide evidence.",
            }
        ]
        profile = profiles.create_draft("security", criteria)
        profiles.fixture_test(profile.profile_version_id)
        profiles.activate(profile.profile_version_id)
        tokens = iter([f"{chr(65 + i)}" * 43 for i in range(6)])
        backend = VendorBackend(repository, profiles, token_factory=lambda: next(tokens))
        vendor = backend.create_vendor("Example Vendor", "vendor.example")
        product = backend.create_product(vendor.vendor_id, "Example Product")
        contact = backend.create_contact(vendor.vendor_id, "Contact", "c@vendor.example")
        backend.register_case("CASE-1", product.product_id, "use", "scope")
        issued = backend.issue_invite("CASE-1", contact.contact_id)
        backend.finalize_submission(issued["token"])
        return backend, "CASE-1"

    def test_one_rerun_limit_with_instructions_and_invalidation(self) -> None:
        backend, case_id = self._backend()
        run_one = backend.create_review_run(case_id)
        self.assertEqual(run_one.run_version, 1)
        run_two = backend.create_review_run(case_id, "Re-check accessibility with the new VPAT.")
        self.assertEqual(run_two.run_version, 2)
        self.assertEqual(run_two.previous_run_id, run_one.run_id)
        self.assertEqual(run_two.instructions, "Re-check accessibility with the new VPAT.")
        self.assertFalse(run_two.decision_valid)
        self.assertFalse(run_two.write_preview_valid)
        # Version 3 accommodates the request-changes resubmission loop
        # (issue #64); the bound still exists and rejects a fourth run.
        run_three = backend.create_review_run(case_id, "Post-resubmission rerun.")
        self.assertEqual(run_three.run_version, 3)
        with self.assertRaises(VendorBackendError) as limited:
            backend.create_review_run(case_id, "fourth run should be rejected")
        self.assertEqual(limited.exception.code, "rerun_limit_reached")


class LifecycleTransitionTests(unittest.TestCase):
    def _approve_payload(self, case_id: str, version: int = 1) -> dict:
        return {
            "case_id": case_id,
            "decision_version": version,
            "reviewer_id": "reviewer@example.edu",
            "action": APPROVE,
            "decided_at": "2026-07-15T08:00:00+00:00",
        }

    def test_needs_review_approved_and_writeback_complete(self) -> None:
        api = LocalReviewApi(seed_demo=True)
        api.analyze_case("TR-260714-018")
        self.assertEqual(api._vendor.get_case_lifecycle("TR-260714-018"), "needs_review")

        api.review_case("TR-260714-018", self._approve_payload("TR-260714-018"))
        self.assertEqual(api._vendor.get_case_lifecycle("TR-260714-018"), "approved")

        previewed = api.preview_servicenow("TR-260714-018")
        expected_version = previewed["state"]["write_preview"]["expected_record_version"]
        api.commit_servicenow(
            "TR-260714-018", {"second_confirmation": True, "expected_version": expected_version}
        )
        self.assertEqual(api._vendor.get_case_lifecycle("TR-260714-018"), "writeback_complete")

    def test_decline_and_request_changes(self) -> None:
        api = LocalReviewApi(seed_demo=True)
        api._add_case("DEC-1", low_risk_case())
        api.analyze_case("DEC-1")
        api.review_case(
            "DEC-1",
            {
                "case_id": "DEC-1",
                "decision_version": 1,
                "reviewer_id": "reviewer@example.edu",
                "action": "reject",
                "decided_at": "2026-07-15T08:00:00+00:00",
                "comments": "Out of scope for the pilot.",
            },
        )
        self.assertEqual(api._vendor.get_case_lifecycle("DEC-1"), "declined")

        api._add_case("CHG-1", low_risk_case())
        api.analyze_case("CHG-1")
        api.review_case(
            "CHG-1",
            {
                "case_id": "CHG-1",
                "decision_version": 1,
                "reviewer_id": "reviewer@example.edu",
                "action": "request_info",
                "decided_at": "2026-07-15T08:00:00+00:00",
                "comments": "Please attach the current VPAT.",
            },
        )
        self.assertEqual(api._vendor.get_case_lifecycle("CHG-1"), "changes_requested")


class SlackTruthfulnessTests(unittest.TestCase):
    def _slack_events(self, api: LocalReviewApi) -> list[dict]:
        return [
            event
            for event in api.integration_events()["items"]
            if event["event_type"] == "slack.notification"
        ]

    def test_default_notifications_are_labeled_simulated(self) -> None:
        api = LocalReviewApi(seed_demo=True)
        api.analyze_case("TR-260714-018")
        events = self._slack_events(api)
        self.assertTrue(events)
        self.assertTrue(all(event["detail"]["simulated"] for event in events))
        self.assertTrue(all(event["detail"]["delivery"] == "simulated" for event in events))

    def test_live_notifier_records_truthful_live_delivery(self) -> None:
        notifier = _StubNotifier({"delivery": "live", "simulated": False, "channel": "reviewers"})
        api = LocalReviewApi(seed_demo=True, notifier=notifier)
        api.analyze_case("TR-260714-018")
        events = self._slack_events(api)
        self.assertTrue(events)
        self.assertFalse(events[-1]["detail"]["simulated"])
        self.assertEqual(events[-1]["detail"]["delivery"], "live")
        self.assertTrue(notifier.calls)


class StructuredInvokerTests(unittest.TestCase):
    def test_valid_structure_passes_without_repair_and_labels_simulated(self) -> None:
        model = DeterministicModelClient()
        out = invoke_structured(
            model, system="s", prompt="p", context={"task": "security_analysis"}
        )
        self.assertEqual(out["_model"]["repair_passes"], 0)
        self.assertTrue(out["_model"]["simulated"])
        self.assertEqual(out["_model"]["model"], "simulated-deterministic")

    def test_one_repair_pass_then_success(self) -> None:
        model = _ScriptedModel(
            [
                {"summary": "partial"},  # missing findings/citations/uncertainty
                {"summary": "ok", "findings": [], "citations": [], "uncertainty": ""},
            ]
        )
        out = invoke_structured(model, system="s", prompt="p", context={})
        self.assertEqual(model.calls, 2)
        self.assertEqual(out["_model"]["repair_passes"], 1)

    def test_explicit_failure_after_one_repair_no_silent_fallback(self) -> None:
        model = _ScriptedModel([{"bad": 1}, {"still": "bad"}])
        with self.assertRaises(ModelStructureError):
            invoke_structured(model, system="s", prompt="p", context={})
        self.assertEqual(model.calls, 2)


class LiveModelInjectionTests(unittest.TestCase):
    def test_config_builds_bedrock_client_in_live_mode(self) -> None:
        config = AppConfig(use_local_fakes=False, model=ModelConfig())
        api = LocalReviewApi(seed_demo=False, config=config)
        self.assertIsInstance(api._model_client, BedrockModelClient)
        self.assertEqual(api._model_client.model_id, "us.anthropic.claude-sonnet-5")

    def test_injected_live_model_is_used_by_specialists(self) -> None:
        fake = _FakeConverse('{"summary": "live", "findings": [], "citations": [], "uncertainty": ""}')
        live = BedrockModelClient(model_id="us.anthropic.claude-sonnet-5", region="us-west-2", client=fake)
        api = LocalReviewApi(seed_demo=False, model_client=live)
        api._add_case("LIVE-1", medium_risk_case())
        api.analyze_case("LIVE-1")
        security = api._cases["LIVE-1"].state.specialist_results["security"]
        self.assertFalse(security["metadata"]["simulated"])
        self.assertEqual(security["metadata"]["model"], "us.anthropic.claude-sonnet-5")
        self.assertGreater(fake.calls, 0)

    def test_live_model_failure_surfaces_and_is_not_silently_faked(self) -> None:
        fake = _FakeConverse("not json at all")
        live = BedrockModelClient(model_id="us.anthropic.claude-sonnet-5", region="us-west-2", client=fake)
        api = LocalReviewApi(seed_demo=False, model_client=live)
        api._add_case("LIVE-FAIL", medium_risk_case())
        with self.assertRaises(ModelStructureError):
            api.analyze_case("LIVE-FAIL")


if __name__ == "__main__":
    unittest.main()
