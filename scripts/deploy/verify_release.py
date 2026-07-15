#!/usr/bin/env python3
"""Verify a sealed release bundle and optionally extract it safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path


ARTIFACTS = {
    "cloud-assembly.tar.gz": "cloud-assembly",
    "frontend.tar.gz": "frontend",
}


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            resolved = (root / member.name).resolve()
            if root != resolved and root not in resolved.parents:
                raise ValueError(f"unsafe archive member: {member.name}")
            if member.isdev() or member.isfifo():
                raise ValueError(f"unsupported archive member: {member.name}")
        bundle.extractall(destination, filter="data")


def verify(bundle: Path, sha: str, extract_to: Path | None = None) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("release SHA must be 40 lowercase hexadecimal characters")
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("release_sha") != sha:
        raise ValueError("release manifest identity does not match")
    if set(manifest.get("artifacts", {})) != set(ARTIFACTS):
        raise ValueError("release manifest has an unexpected artifact set")
    for artifact, directory in ARTIFACTS.items():
        path = bundle / artifact
        expected = manifest["artifacts"][artifact].get("sha256", "")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", expected) or actual != expected:
            raise ValueError(f"release artifact checksum mismatch: {artifact}")
        if extract_to is not None:
            safe_extract(path, extract_to / directory)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--extract-to", type=Path)
    args = parser.parse_args()
    verify(args.bundle, args.sha, args.extract_to)
    print("VERIFIED_RELEASE_BUNDLE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
