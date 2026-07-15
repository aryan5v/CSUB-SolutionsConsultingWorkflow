"""Mock ServiceNow connector behavior tests (FR-7)."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.servicenow import (
    ConnectorError,
    MockServiceNowConnector,
    StaleRecordError,
    UnapprovedWriteError,
)
from review_agent.contracts.servicenow import HumanDecision, ReviewAction


def _decision(action=ReviewAction.APPROVE, version=1, fields=None):
    return HumanDecision(
        case_id="CASE-1",
        decision_version=version,
        reviewer_id="rev@example.edu",
        action=action,
        decided_at="2026-07-14T12:00:00+00:00",
        approved_fields=fields if fields is not None else {"state": "approved"},
    )


class MockServiceNowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.c = MockServiceNowConnector()
        self.c.seed_record(record_id="R1", table="sc_req_item", fields={"state": "open"})
        self.c.configure_case(case_id="CASE-1", table="sc_req_item", record_id="R1")

    def test_preview_shows_before_after(self) -> None:
        self.c.stage_decision(_decision())
        preview = self.c.preview_update("CASE-1", 1)
        self.assertTrue(preview.simulated)
        self.assertEqual(preview.before["state"], "open")
        self.assertEqual(preview.after["state"], "approved")
        self.assertEqual(len(preview.field_changes), 1)

    def test_commit_updates_and_bumps_version(self) -> None:
        self.c.stage_decision(_decision())
        result = self.c.update_request("CASE-1", 1, expected_version=1)
        self.assertTrue(result.committed)
        self.assertEqual(result.record_version, 2)
        self.assertFalse(result.duplicate_suppressed)

    def test_commit_is_idempotent(self) -> None:
        self.c.stage_decision(_decision())
        first = self.c.update_request("CASE-1", 1, expected_version=1)
        replay = self.c.update_request("CASE-1", 1, expected_version=1)
        self.assertTrue(replay.duplicate_suppressed)
        self.assertEqual(replay.record_version, first.record_version)

    def test_stale_version_is_rejected(self) -> None:
        self.c.stage_decision(_decision())
        with self.assertRaises(StaleRecordError):
            self.c.update_request("CASE-1", 1, expected_version=99)

    def test_write_requires_approved_decision(self) -> None:
        with self.assertRaises(UnapprovedWriteError):
            self.c.update_request("CASE-1", 1, expected_version=1)

    def test_reject_decision_cannot_be_staged(self) -> None:
        with self.assertRaises(UnapprovedWriteError):
            self.c.stage_decision(_decision(action=ReviewAction.REJECT))

    def test_non_writable_field_is_rejected(self) -> None:
        self.c.stage_decision(_decision(fields={"sys_id": "hacked"}))
        with self.assertRaises(ConnectorError):
            self.c.preview_update("CASE-1", 1)

    def test_attach_packet_is_once(self) -> None:
        first = self.c.attach_packet("R1", "abc123")
        second = self.c.attach_packet("R1", "abc123")
        self.assertFalse(first.already_present)
        self.assertTrue(second.already_present)
        self.assertEqual(first.attachment_id, second.attachment_id)

    def test_verify_writeback_returns_result(self) -> None:
        self.c.stage_decision(_decision())
        self.c.update_request("CASE-1", 1, expected_version=1)
        self.assertIsNotNone(self.c.verify_writeback("CASE-1:1"))
        self.assertIsNone(self.c.verify_writeback("CASE-1:2"))

    def test_inspect_schema_is_deterministic_config(self) -> None:
        schema = self.c.inspect_schema("sc_req_item")
        self.assertIn("state", schema["writable_fields"])
        self.assertIn("sys_id", schema["read_only_fields"])


if __name__ == "__main__":
    unittest.main()
