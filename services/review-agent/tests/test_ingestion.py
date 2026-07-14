"""Workbook ingestion and reconciliation tests (FR-2 acceptance: 100%)."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from review_agent.ingestion.manifest import build_manifest_entry, sha256_bytes
from review_agent.ingestion.software_workbook import (
    RowsWorkbookReader,
    normalize_workbook,
)
from review_agent.samples import sample_workbook_reader


class IngestionTests(unittest.TestCase):
    def test_row_and_column_counts_reconcile(self) -> None:
        result = normalize_workbook(sample_workbook_reader(), source_id="src:x")
        report = result.reconciliation
        self.assertTrue(report.rows_reconcile)
        self.assertTrue(report.columns_reconcile)
        self.assertEqual(report.output_rows, 2)

    def test_source_row_is_lossless(self) -> None:
        reader = sample_workbook_reader()
        result = normalize_workbook(reader, source_id="src:x")
        headers = set(reader.headers())
        for record in result.records:
            self.assertEqual(set(record.source_row.keys()), headers)

    def test_blank_product_name_becomes_warning_not_drop(self) -> None:
        reader = RowsWorkbookReader(
            ["Product Name", "Vendor"],
            [{"Product Name": "", "Vendor": "Acme"}],
        )
        result = normalize_workbook(reader, source_id="src:x")
        self.assertEqual(len(result.records), 1)
        self.assertIn("blank product name", result.records[0].extraction_warnings)

    def test_missing_expected_column_warns(self) -> None:
        reader = RowsWorkbookReader(["Vendor"], [{"Vendor": "Acme"}])
        result = normalize_workbook(reader, source_id="src:x")
        self.assertTrue(
            any("Product Name" in w for w in result.reconciliation.warnings)
        )

    def test_manifest_entry_hashes_body(self) -> None:
        body = b"hello world"
        entry = build_manifest_entry(
            source_id="box:1",
            filename="x.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            body=body,
            category="approved_software",
            version="1",
            ingested_at="2026-07-14T12:00:00+00:00",
        )
        self.assertEqual(entry.sha256, sha256_bytes(body))
        self.assertEqual(entry.extraction_state, "ingested")


if __name__ == "__main__":
    unittest.main()
