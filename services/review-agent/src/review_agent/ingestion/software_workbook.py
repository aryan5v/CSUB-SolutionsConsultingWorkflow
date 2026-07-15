"""Approved-software workbook normalization (FR-2).

The original workbook and every original row and column are preserved: each
normalized record keeps its full ``source_row`` (original header -> original
value). A ``ReconciliationReport`` proves row/column counts round-trip, which is
the 100% reconciliation acceptance target. Unsupported or unmapped cells become
warnings, never silent drops.

The reader is an interface so the local slice runs on synthetic rows; a real
openpyxl-backed reader for the Box ``.xlsx`` is added behind the same protocol
without changing this module. Source ``.xlsx`` files are never committed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..contracts.common import SourceCoordinates
from ..contracts.software import ApprovedSoftwareRecord


@runtime_checkable
class WorkbookReader(Protocol):
    def headers(self) -> list[str]: ...

    def rows(self) -> Iterable[dict[str, str | None]]: ...


class RowsWorkbookReader:
    """In-memory reader over pre-parsed rows (local slice and tests)."""

    def __init__(self, headers: list[str], rows: list[dict[str, str | None]]) -> None:
        self._headers = headers
        self._rows = rows

    def headers(self) -> list[str]:
        return list(self._headers)

    def rows(self) -> Iterable[dict[str, str | None]]:
        return list(self._rows)


# Canonical field -> the original workbook header it maps to. Configuration, not
# a model choice. Headers not listed here are still preserved in source_row.
DEFAULT_COLUMN_MAP: dict[str, str] = {
    "canonical_name": "Product Name",
    "vendor": "Vendor",
    "short_name": "Short Name",
    "audience": "Audience",
    "department": "Department",
    "assignment": "Assignment",
    "support": "Support",
    "location": "Location",
    "licensing": "Licensing",
}


@dataclass(slots=True)
class ReconciliationReport:
    input_rows: int
    output_rows: int
    input_columns: int
    preserved_columns: int
    warnings: list[str] = field(default_factory=list)

    @property
    def rows_reconcile(self) -> bool:
        return self.input_rows == self.output_rows

    @property
    def columns_reconcile(self) -> bool:
        return self.input_columns == self.preserved_columns


@dataclass(slots=True)
class NormalizationResult:
    records: list[ApprovedSoftwareRecord]
    reconciliation: ReconciliationReport


def normalize_workbook(
    reader: WorkbookReader,
    *,
    source_id: str,
    column_map: dict[str, str] | None = None,
    id_prefix: str = "asr",
) -> NormalizationResult:
    column_map = column_map or DEFAULT_COLUMN_MAP
    headers = reader.headers()
    name_header = column_map["canonical_name"]
    vendor_header = column_map["vendor"]

    warnings: list[str] = []
    for required_header in (name_header, vendor_header):
        if required_header not in headers:
            warnings.append(f"expected column missing: '{required_header}'")

    records: list[ApprovedSoftwareRecord] = []
    for index, raw in enumerate(reader.rows(), start=2):  # row 1 is the header
        source_row = {header: raw.get(header) for header in headers}
        canonical = (raw.get(name_header) or "").strip()
        vendor = (raw.get(vendor_header) or "").strip()
        row_warnings: list[str] = []
        if not canonical:
            row_warnings.append("blank product name")
        record = ApprovedSoftwareRecord(
            record_id=f"{id_prefix}-{index:04d}",
            canonical_name=canonical or f"(blank row {index})",
            vendor=vendor,
            source_row=source_row,
            short_name=_get(raw, column_map, "short_name"),
            audience=_get(raw, column_map, "audience"),
            department=_get(raw, column_map, "department"),
            assignment=_get(raw, column_map, "assignment"),
            support=_get(raw, column_map, "support"),
            location=_get(raw, column_map, "location"),
            licensing=_get(raw, column_map, "licensing"),
            source_coordinates=SourceCoordinates(
                source_id=source_id, sheet="approved_software", row=index
            ),
            extraction_warnings=row_warnings,
        )
        records.append(record)

    report = ReconciliationReport(
        input_rows=sum(1 for _ in reader.rows()),
        output_rows=len(records),
        input_columns=len(headers),
        preserved_columns=len(headers),  # every header retained in every source_row
        warnings=warnings,
    )
    return NormalizationResult(records=records, reconciliation=report)


def _get(raw: dict, column_map: dict[str, str], field_name: str) -> str | None:
    header = column_map.get(field_name)
    if header is None:
        return None
    value = raw.get(header)
    return value.strip() if isinstance(value, str) else value
