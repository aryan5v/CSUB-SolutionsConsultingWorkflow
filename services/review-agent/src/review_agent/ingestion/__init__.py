"""Ingestion: source manifest and lossless workbook normalization."""

from __future__ import annotations

from .manifest import build_manifest_entry, sha256_bytes
from .software_workbook import (
    DEFAULT_COLUMN_MAP,
    NormalizationResult,
    ReconciliationReport,
    RowsWorkbookReader,
    WorkbookReader,
    normalize_workbook,
)

__all__ = [
    "DEFAULT_COLUMN_MAP",
    "NormalizationResult",
    "ReconciliationReport",
    "RowsWorkbookReader",
    "WorkbookReader",
    "build_manifest_entry",
    "normalize_workbook",
    "sha256_bytes",
]
