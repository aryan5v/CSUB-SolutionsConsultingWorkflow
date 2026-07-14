#!/usr/bin/env python3
"""Detect common committed secret patterns without external dependencies."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 1_000_000
PATTERNS = (
    ("AWS access key", re.compile("A" + "KIA" + r"[0-9A-Z]{16}")),
    ("GitHub token", re.compile("g" + r"h[pousr]_[A-Za-z0-9_]{20,}")),
    ("GitHub fine-grained token", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    (
        "private key",
        re.compile(
            "-" * 5
            + r"BEGIN (?:(?:RSA|EC|OPENSSH) )?PRIVATE KEY"
            + "-" * 5
        ),
    ),
)


def git_paths(staged: bool) -> list[Path]:
    command = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
    if not staged:
        command = ["git", "ls-files", "-z"]
    output = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return [Path(item.decode("utf-8")) for item in output.split(b"\0") if item]


def read_content(path: Path, staged: bool) -> str | None:
    if staged:
        result = subprocess.run(
            ["git", "show", f":{path.as_posix()}"],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0 or len(result.stdout) > MAX_FILE_BYTES:
            return None
        data = result.stdout
    else:
        absolute_path = ROOT / path
        if not absolute_path.is_file() or absolute_path.stat().st_size > MAX_FILE_BYTES:
            return None
        data = absolute_path.read_bytes()

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def findings_for_text(path: Path, content: str) -> list[str]:
    findings: list[str] = []
    for label, pattern in PATTERNS:
        for match in pattern.finditer(content):
            line = content.count("\n", 0, match.start()) + 1
            findings.append(f"{path}:{line}: possible {label}")
    return findings


def scan(staged: bool) -> list[str]:
    findings: list[str] = []
    for path in git_paths(staged):
        content = read_content(path, staged)
        if content is not None:
            findings.extend(findings_for_text(path, content))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all", action="store_true", help="scan every tracked file")
    scope.add_argument("--staged", action="store_true", help="scan the staged snapshot")
    args = parser.parse_args()

    findings = scan(staged=args.staged)
    if findings:
        print("Secret-pattern scan failed:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1

    target = "staged" if args.staged else "tracked"
    print(f"Secret-pattern scan passed for {target} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
