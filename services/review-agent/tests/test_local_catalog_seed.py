"""Seeding the full approved-software catalog from the local export (issue #67)."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import _bootstrap  # noqa: F401

from review_agent.api import LocalReviewApi, _local_catalog_records

_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_REL = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _cell(reference: str, text: str) -> str:
    return f'<c r="{reference}" t="inlineStr"><is><t>{text}</t></is></c>'


def _write_workbook(path: Path, product_rows: list[tuple[str, str]]) -> None:
    header = f'<row r="1">{_cell("A1", "Product Name")}{_cell("B1", "Vendor")}</row>'
    body = "".join(
        f'<row r="{index}">{_cell(f"A{index}", name)}{_cell(f"B{index}", vendor)}</row>'
        for index, (name, vendor) in enumerate(product_rows, start=2)
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook {_NS} {_REL}><sheets>'
            '<sheet name="approved_software" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f"<worksheet {_NS}><sheetData>{header}{body}</sheetData></worksheet>",
        )


class LocalCatalogSeedTests(unittest.TestCase):
    def test_missing_workbook_falls_back_to_empty(self) -> None:
        with mock.patch.dict(
            "os.environ", {"APPROVED_SOFTWARE_XLSX": "/nonexistent/export.xlsx"}
        ):
            self.assertEqual(_local_catalog_records(), [])

    def test_local_export_seeds_the_full_catalog(self) -> None:
        rows = [("Canvas LMS", "Instructure"), ("Zoom Workplace", "Zoom")]
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "SNOW Export_approved_software_database.xlsx"
            _write_workbook(workbook, rows)
            with mock.patch.dict("os.environ", {"APPROVED_SOFTWARE_XLSX": str(workbook)}):
                records = _local_catalog_records()
                self.assertEqual(
                    [record.canonical_name for record in records],
                    ["Canvas LMS", "Zoom Workplace"],
                )
                # The API seeds its lookup index and catalog from the export.
                api = LocalReviewApi(seed_demo=False)
                catalog = api.list_catalog()
                self.assertEqual(catalog["total"], 2)

    def test_malformed_workbook_falls_back_to_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "export.xlsx"
            workbook.write_bytes(b"not a zip archive")
            with mock.patch.dict("os.environ", {"APPROVED_SOFTWARE_XLSX": str(workbook)}):
                self.assertEqual(_local_catalog_records(), [])


if __name__ == "__main__":
    unittest.main()
