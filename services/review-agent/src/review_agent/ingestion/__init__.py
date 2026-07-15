"""Ingestion package with lazy compatibility exports.

Keeping workbook symbols lazy avoids preloading the CLI module when it is run
with ``python -m`` while preserving the original package import surface.
"""

from __future__ import annotations

from .manifest import build_manifest_entry, sha256_bytes

_WORKBOOK_EXPORTS = {
    "DEFAULT_COLUMN_MAP",
    "NormalizationResult",
    "ReconciliationReport",
    "RowsWorkbookReader",
    "WorkbookReader",
    "XlsxWorkbookReader",
    "normalize_workbook",
    "normalized_identity",
}

__all__ = [
    *_WORKBOOK_EXPORTS,
    "build_manifest_entry",
    "sha256_bytes",
]


def __getattr__(name: str):
    if name in _WORKBOOK_EXPORTS:
        from . import software_workbook

        return getattr(software_workbook, name)
    raise AttributeError(name)
