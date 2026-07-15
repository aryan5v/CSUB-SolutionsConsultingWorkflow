"""Development-only walker over a local institutional corpus directory.

Points at a local Box corpus folder (git-ignored) and prints a metadata-only
summary: the classification breakdown, which sources are activatable, which are
draft/unconfirmed, and any untrusted-content findings. It never prints document
bodies, and by default it persists nothing. This is a developer aid for the
normalization slice, not a runtime component.

Usage:

    PYTHONPATH=src python3 -m review_agent.institutional \\
        "/path/to/Solutions Consulting"

Text is extracted from ``.txt``, ``.md``, and Office Open XML zips (``.docx``,
``.xlsx``, ``.pptx``) with the standard library only so the untrusted scan can
run. Binary formats such as PDF and ``.msg`` are classified but not scanned.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

from .normalize import (
    CorpusNormalizationResult,
    InstitutionalSourceRecord,
    normalize_source,
)

_XML_TAG_RE = re.compile(r"<[^>]+>")
_MAX_TEXT_BYTES = 8 * 1024 * 1024
_ZIP_TEXT_EXTS = {".docx", ".xlsx", ".pptx"}
_PLAIN_TEXT_EXTS = {".txt", ".md"}
_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".msg": "application/vnd.ms-outlook",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def _extract_text(path: Path) -> str | None:
    ext = path.suffix.lower()
    try:
        if ext in _PLAIN_TEXT_EXTS:
            return path.read_text(encoding="utf-8", errors="replace")[:_MAX_TEXT_BYTES]
        if ext in _ZIP_TEXT_EXTS:
            chunks: list[str] = []
            total = 0
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if not name.lower().endswith(".xml"):
                        continue
                    with zf.open(name) as handle:
                        raw = handle.read(max(0, _MAX_TEXT_BYTES - total))
                    chunks.append(_XML_TAG_RE.sub(" ", raw.decode("utf-8", "replace")))
                    total += len(raw)
                    if total >= _MAX_TEXT_BYTES:
                        break
            return " ".join(chunks)
    except (OSError, zipfile.BadZipFile):
        return None
    return None


def _walk(root: Path) -> list[InstitutionalSourceRecord]:
    records: list[InstitutionalSourceRecord] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        relative = path.relative_to(root.parent).as_posix()
        text = _extract_text(path)
        record = normalize_source(
            source_id=f"local:{relative}",
            relative_path=relative,
            mime_type=_MIME.get(path.suffix.lower(), "application/octet-stream"),
            text=text,
        )
        if text is None and path.suffix.lower() not in _PLAIN_TEXT_EXTS:
            record.extraction_warnings.append(
                f"text extraction not implemented for '{path.suffix}'; untrusted scan skipped"
            )
        records.append(record)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Institutional corpus normalization (dev-only).")
    parser.add_argument("corpus", help="Path to a local corpus directory (git-ignored).")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit metadata records (no document bodies) instead of the summary.",
    )
    args = parser.parse_args(argv)

    root = Path(args.corpus).expanduser()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    result = CorpusNormalizationResult(records=_walk(root))
    result.assert_scope_separation()

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(json.dumps(result.summary(), indent=2))
        for record in result.flagged():
            for finding in record.untrusted_findings:
                print(
                    f"  flag [{record.filename}] {finding.kind}: {finding.detail}",
                    file=sys.stderr,
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
