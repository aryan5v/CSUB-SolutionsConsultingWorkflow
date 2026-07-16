"""Structured metrics emission (issue #50)."""

from __future__ import annotations

import json
import logging
import unittest

import _bootstrap  # noqa: F401

from review_agent.observability.metrics import (
    EmbeddedMetricsEmitter,
    InMemoryMetricsSink,
    NullMetricsEmitter,
)


class InMemoryMetricsSinkTests(unittest.TestCase):
    def test_records_name_value_dimensions_and_properties(self) -> None:
        sink = InMemoryMetricsSink()
        sink.emit(
            "model.invoke.latency_ms",
            123.4,
            unit="Milliseconds",
            dimensions={"step": "security"},
            properties={"case_id": "CASE-1", "run_id": "run-1"},
        )
        self.assertEqual(sink.values_for("model.invoke.latency_ms"), [123.4])
        record = sink.records[0]
        self.assertEqual(record["dimensions"], {"step": "security"})
        self.assertEqual(record["properties"]["case_id"], "CASE-1")

    def test_rejects_sensitive_properties(self) -> None:
        sink = InMemoryMetricsSink()
        with self.assertRaises(ValueError):
            sink.emit("x", 1, properties={"prompt": "do not log this"})


class EmbeddedMetricsEmitterTests(unittest.TestCase):
    def test_emits_valid_emf_document(self) -> None:
        emitter = EmbeddedMetricsEmitter(namespace="ReviewAgentTest", clock=lambda: 1_700_000_000.0)
        with self.assertLogs("review_agent.metrics", level="INFO") as captured:
            emitter.emit(
                "citations.rejected_count",
                2,
                unit="Count",
                dimensions={"workflow_version": "0.1.0"},
                properties={"run_id": "run-abc", "case_id": "CASE-1", "ok": False},
            )
        document = json.loads(captured.records[0].getMessage())
        self.assertEqual(document["_aws"]["Timestamp"], 1_700_000_000_000)
        metric_block = document["_aws"]["CloudWatchMetrics"][0]
        self.assertEqual(metric_block["Namespace"], "ReviewAgentTest")
        self.assertEqual(metric_block["Dimensions"], [["workflow_version"]])
        self.assertEqual(metric_block["Metrics"], [{"Name": "citations.rejected_count", "Unit": "Count"}])
        self.assertEqual(document["workflow_version"], "0.1.0")
        self.assertEqual(document["citations.rejected_count"], 2)
        self.assertEqual(document["run_id"], "run-abc")

    def test_rejects_sensitive_properties(self) -> None:
        emitter = EmbeddedMetricsEmitter()
        with self.assertRaises(ValueError):
            emitter.emit("x", 1, properties={"document_body": "..."})


class NullMetricsEmitterTests(unittest.TestCase):
    def test_is_a_no_op(self) -> None:
        NullMetricsEmitter().emit("anything", 1)


if __name__ == "__main__":
    unittest.main()
