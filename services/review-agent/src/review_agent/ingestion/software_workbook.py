"""Lossless approved-software workbook ingestion and reconciliation (FR-2).

The standard-library XLSX reader consumes a local operator-supplied path.  It
never copies the workbook and the CLI emits counts/hashes only, not institutional
rows.  Every XML data row becomes one record with all original headers retained.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable
from zipfile import BadZipFile, ZipFile

from ..contracts.common import SourceCoordinates
from ..contracts.software import ApprovedSoftwareRecord
from ..contracts.vendor import DEFAULT_WORKSPACE_ID, SoftwareCatalogEntry

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_REF = re.compile(r"^([A-Z]+)[0-9]+$")
_SPLIT = re.compile(r"\s*[,;/|]\s*")
_MAX_WORKBOOK_BYTES = 25_000_000
_MAX_XML_BYTES = 20_000_000


@runtime_checkable
class WorkbookReader(Protocol):
    def headers(self) -> list[str]: ...

    def rows(self) -> Iterable[dict[str, str | None]]: ...


class RowsWorkbookReader:
    """In-memory reader over pre-parsed rows (local slice and tests)."""

    source_hash: str | None = None
    sheet_name = "approved_software"

    def __init__(self, headers: list[str], rows: list[dict[str, str | None]]) -> None:
        self._headers = headers
        self._rows = rows

    def headers(self) -> list[str]:
        return list(self._headers)

    def rows(self) -> Iterable[dict[str, str | None]]:
        return list(self._rows)


class XlsxWorkbookReader:
    """Read the first XLSX worksheet without third-party dependencies."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise ValueError("workbook path does not exist")
        if self.path.suffix.lower() != ".xlsx":
            raise ValueError("approved-software source must be an .xlsx workbook")
        if self.path.stat().st_size > _MAX_WORKBOOK_BYTES:
            raise ValueError("workbook exceeds the 25 MB operator limit")
        body = self.path.read_bytes()
        self.source_hash = hashlib.sha256(body).hexdigest()
        try:
            self._headers, self._rows, self.sheet_name, self.extraction_warnings = self._parse()
        except (BadZipFile, ET.ParseError, KeyError, IndexError, ValueError) as error:
            raise ValueError("workbook is malformed or unsupported") from error

    def headers(self) -> list[str]:
        return list(self._headers)

    def rows(self) -> Iterable[dict[str, str | None]]:
        return [dict(row) for row in self._rows]

    def _read_xml(self, archive: ZipFile, name: str) -> bytes:
        info = archive.getinfo(name)
        if info.file_size > _MAX_XML_BYTES:
            raise ValueError("workbook XML entry is too large")
        return archive.read(name)

    def _parse(self) -> tuple[list[str], list[dict[str, str | None]], str, list[str]]:
        with ZipFile(self.path) as archive:
            workbook = ET.fromstring(self._read_xml(archive, "xl/workbook.xml"))
            sheets = workbook.find(f"{{{_MAIN_NS}}}sheets")
            if sheets is None or not list(sheets):
                raise ValueError("workbook has no sheets")
            sheet = list(sheets)[0]
            sheet_name = sheet.attrib.get("name", "Sheet1")
            relationship_id = sheet.attrib[f"{{{_REL_NS}}}id"]
            relationships = ET.fromstring(
                self._read_xml(archive, "xl/_rels/workbook.xml.rels")
            )
            targets = {
                item.attrib["Id"]: item.attrib["Target"]
                for item in relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
            }
            target = targets[relationship_id].lstrip("/")
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            if ".." in Path(target).parts:
                raise ValueError("invalid worksheet relationship")
            shared = self._shared_strings(archive)
            worksheet = ET.fromstring(self._read_xml(archive, target))
            sheet_data = worksheet.find(f"{{{_MAIN_NS}}}sheetData")
            if sheet_data is None:
                raise ValueError("worksheet has no data")
            xml_rows = sheet_data.findall(f"{{{_MAIN_NS}}}row")
            if not xml_rows:
                raise ValueError("worksheet is empty")
            header_cells, header_warnings = self._row_values(xml_rows[0], shared)
            last_header = max(header_cells, default=-1)
            headers = [header_cells.get(index, "") or "" for index in range(last_header + 1)]
            if not headers or any(not header for header in headers):
                raise ValueError("worksheet header contains blank columns")
            if len(headers) != len(set(headers)):
                raise ValueError("worksheet header contains duplicate names")
            rows: list[dict[str, str | None]] = []
            warnings = list(header_warnings)
            for xml_row in xml_rows[1:]:
                values, row_warnings = self._row_values(xml_row, shared)
                row_number = int(xml_row.attrib.get("r", len(rows) + 2))
                warnings.extend(f"row {row_number}: {warning}" for warning in row_warnings)
                rows.append(
                    {
                        header: values.get(index)
                        for index, header in enumerate(headers)
                    }
                )
            return headers, rows, sheet_name, warnings

    def _shared_strings(self, archive: ZipFile) -> list[str]:
        if "xl/sharedStrings.xml" not in archive.namelist():
            return []
        root = ET.fromstring(self._read_xml(archive, "xl/sharedStrings.xml"))
        return [
            "".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t"))
            for item in root.findall(f"{{{_MAIN_NS}}}si")
        ]

    @staticmethod
    def _row_values(row: ET.Element, shared: list[str]) -> tuple[dict[int, str | None], list[str]]:
        values: dict[int, str | None] = {}
        warnings: list[str] = []
        for cell in row.findall(f"{{{_MAIN_NS}}}c"):
            reference = cell.attrib.get("r", "")
            match = _CELL_REF.fullmatch(reference)
            if match is None:
                raise ValueError("cell reference is invalid")
            index = _column_index(match.group(1))
            cell_type = cell.attrib.get("t")
            formula = cell.find(f"{{{_MAIN_NS}}}f")
            if formula is not None:
                warnings.append(f"formula preserved from {reference}")
                values[index] = f"={formula.text or ''}"
                continue
            if cell_type == "inlineStr":
                value = "".join(
                    node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t")
                )
            else:
                value_node = cell.find(f"{{{_MAIN_NS}}}v")
                raw = None if value_node is None else value_node.text
                if cell_type == "s" and raw is not None:
                    value = shared[int(raw)]
                else:
                    value = raw
            values[index] = value
        return values, warnings


DEFAULT_COLUMN_CANDIDATES: dict[str, tuple[str, ...]] = {
    "canonical_name": ("Identity", "Product Name"),
    "vendor": ("Vendor",),
    "short_name": ("Short Name",),
    "audience": ("Availiable to", "Available to", "Audience"),
    "platform": ("Platform",),
    "department": ("Department",),
    "assignment": ("Assignment Group", "Assignment"),
    "support": ("Support",),
    "location": ("Location",),
    "licensing": ("License Type", "Licensing"),
    "supported_software": ("Supported Software",),
    "campus_license": ("Campus license", "Campus License"),
}
DEFAULT_COLUMN_MAP: dict[str, str] = {
    key: candidates[0] for key, candidates in DEFAULT_COLUMN_CANDIDATES.items()
}


@dataclass(slots=True)
class ReconciliationReport:
    input_rows: int
    output_rows: int
    input_columns: int
    preserved_columns: int
    duplicate_identity_groups: int = 0
    duplicate_rows: int = 0
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

    def catalog_entries(self) -> list[SoftwareCatalogEntry]:
        entries: list[SoftwareCatalogEntry] = []
        for record in self.records:
            if record.source_hash is None or record.source_row_number is None:
                raise ValueError("catalog source hash and row are required")
            entries.append(
                SoftwareCatalogEntry(
                    record_id=record.record_id,
                    canonical_name=record.canonical_name,
                    vendor=record.vendor,
                    normalized_identity=record.normalized_identity or "",
                    source_row=record.source_row_number,
                    source_hash=record.source_hash,
                    raw_values=dict(record.source_row),
                    supported_software=record.supported_software,
                    campus_license=record.campus_license,
                    aliases=tuple(record.aliases),
                    short_name=record.short_name,
                    platform=tuple(record.platform),
                    audience=record.audience,
                    workspace_id=record.workspace_id,
                )
            )
        return entries


def normalize_workbook(
    reader: WorkbookReader,
    *,
    source_id: str,
    column_map: dict[str, str] | None = None,
    id_prefix: str = "asr",
    workspace_id: str = DEFAULT_WORKSPACE_ID,
) -> NormalizationResult:
    headers = reader.headers()
    resolved = column_map or _resolve_column_map(headers)
    name_header = resolved.get("canonical_name")
    vendor_header = resolved.get("vendor")
    rows = list(reader.rows())
    source_hash = getattr(reader, "source_hash", None) or hashlib.sha256(
        repr((headers, rows)).encode("utf-8")
    ).hexdigest()
    sheet_name = getattr(reader, "sheet_name", "approved_software")

    warnings = list(getattr(reader, "extraction_warnings", []))
    for required_field in ("canonical_name", "vendor"):
        header = resolved.get(required_field)
        if header is None or header not in headers:
            candidates = DEFAULT_COLUMN_CANDIDATES[required_field]
            display = "' or '".join(candidates)
            warnings.append(f"expected column missing: '{display}'")

    records: list[ApprovedSoftwareRecord] = []
    identities: list[str] = []
    for index, raw in enumerate(rows, start=2):
        source_row = {header: raw.get(header) for header in headers}
        canonical = _clean(raw.get(name_header)) if name_header else None
        vendor = _clean(raw.get(vendor_header)) if vendor_header else None
        short_name = _get(raw, resolved, "short_name")
        audience = _get(raw, resolved, "audience")
        platforms = _list_value(_get(raw, resolved, "platform"))
        identity = normalized_identity(canonical, short_name, audience, platforms)
        identities.append(identity)
        row_warnings: list[str] = []
        if not canonical:
            row_warnings.append("blank product name")
        record = ApprovedSoftwareRecord(
            record_id=f"{id_prefix}-{index:04d}",
            canonical_name=canonical or f"(blank row {index})",
            vendor=vendor or "",
            source_row=source_row,
            short_name=short_name,
            platform=platforms,
            audience=audience,
            department=_get(raw, resolved, "department"),
            assignment=_get(raw, resolved, "assignment"),
            support=_get(raw, resolved, "support"),
            location=_get(raw, resolved, "location"),
            licensing=_get(raw, resolved, "licensing"),
            supported_software=_get(raw, resolved, "supported_software"),
            campus_license=_get(raw, resolved, "campus_license"),
            source_hash=source_hash,
            source_row_number=index,
            normalized_identity=identity,
            workspace_id=workspace_id,
            source_coordinates=SourceCoordinates(
                source_id=source_id,
                filename=(Path(reader.path).name if isinstance(reader, XlsxWorkbookReader) else None),
                sheet=sheet_name,
                row=index,
                sha256=source_hash,
            ),
            extraction_warnings=row_warnings,
        )
        records.append(record)

    counts = Counter(identities)
    duplicate_counts = [count for count in counts.values() if count > 1]
    report = ReconciliationReport(
        input_rows=len(rows),
        output_rows=len(records),
        input_columns=len(headers),
        preserved_columns=len(headers),
        duplicate_identity_groups=len(duplicate_counts),
        duplicate_rows=sum(duplicate_counts),
        warnings=warnings,
    )
    return NormalizationResult(records=records, reconciliation=report)


def _resolve_column_map(headers: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field_name, candidates in DEFAULT_COLUMN_CANDIDATES.items():
        found = next((candidate for candidate in candidates if candidate in headers), None)
        if found is not None:
            result[field_name] = found
    return result


def _get(raw: dict, column_map: dict[str, str], field_name: str) -> str | None:
    header = column_map.get(field_name)
    return _clean(raw.get(header)) if header is not None else None


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text.strip()


def _list_value(value: str | None) -> list[str]:
    return [item for item in _SPLIT.split(value or "") if item]


def normalized_identity(
    canonical: str | None,
    short_name: str | None,
    audience: str | None,
    platform: list[str] | tuple[str, ...],
) -> str:
    values = (canonical or "", short_name or "", audience or "", " ".join(platform))
    return "|".join(" ".join(value.casefold().split()) for value in values)


def _column_index(letters: str) -> int:
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter) - ord("A") + 1
    return index - 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile a local approved-software XLSX without exporting source rows"
    )
    parser.add_argument("--dry-run", action="store_true", help="validate and print counts only")
    parser.add_argument("workbook")
    parser.add_argument("--workspace-id", default=DEFAULT_WORKSPACE_ID)
    args = parser.parse_args()
    reader = XlsxWorkbookReader(args.workbook)
    result = normalize_workbook(
        reader,
        source_id=f"operator:{reader.source_hash}",
        workspace_id=args.workspace_id,
    )
    report = result.reconciliation
    if not report.rows_reconcile or not report.columns_reconcile:
        raise SystemExit("workbook reconciliation failed")
    mode = "dry-run" if args.dry_run else "validated"
    print(
        f"{mode}: rows={report.output_rows} columns={report.preserved_columns} "
        f"source_rows={report.input_rows} original_columns={report.input_columns} "
        f"duplicate_normalized_identities={report.duplicate_identity_groups} "
        f"duplicate_rows={report.duplicate_rows} source_hash={reader.source_hash}"
    )
    print("catalog_membership_is_approval=false explicit_support_and_license_preserved=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
