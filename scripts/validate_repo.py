#!/usr/bin/env python3
"""Validate repository structure and documentation without third-party packages."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    ".github/workflows/ci.yml",
    "AGENTS.md",
    "CLAUDE.md",
    "PLAN.md",
    "README.md",
    "docs/PRD.md",
    "docs/decisions/0001-aws-agentic-review-architecture.md",
    "infra/README.md",
)
REQUIRED_PRD_TERMS = (
    "medium-risk",
    "HumanDecision",
    "MockServiceNowConnector",
    "LangGraph",
    "HECVAT",
    "S3 Vectors",
)
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def validate_required_files(errors: list[str]) -> None:
    for relative_path in REQUIRED_FILES:
        if not (ROOT / relative_path).is_file():
            errors.append(f"missing required file: {relative_path}")


def validate_markdown_links(errors: list[str]) -> None:
    for document in ROOT.rglob("*.md"):
        if any(part in document.parts for part in (".git", "node_modules", "dist", "build")):
            continue
        content = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(content):
            target = raw_target.strip().strip("<>")
            if target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            path_text = unquote(target.split("#", 1)[0])
            if not path_text:
                continue
            resolved = (document.parent / path_text).resolve()
            if not resolved.exists():
                relative_document = document.relative_to(ROOT)
                errors.append(
                    f"broken local link in {relative_document}: {raw_target}"
                )


def validate_prd_coverage(errors: list[str]) -> None:
    prd = (ROOT / "docs/PRD.md").read_text(encoding="utf-8")
    plan = (ROOT / "PLAN.md").read_text(encoding="utf-8")
    combined = f"{prd}\n{plan}"
    for term in REQUIRED_PRD_TERMS:
        if term not in combined:
            errors.append(f"PRD/plan coverage is missing required term: {term}")


def main() -> int:
    errors: list[str] = []
    validate_required_files(errors)
    if not errors:
        validate_markdown_links(errors)
        validate_prd_coverage(errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Repository structure, links, and plan coverage passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
