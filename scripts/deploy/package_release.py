#!/usr/bin/env python3
"""Create reproducible release archives and a checksum manifest."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import tarfile
from pathlib import Path


def archive(source: Path, destination: Path, epoch: int) -> str:
    with destination.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as tar:
                for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
                    relative = path.relative_to(source)
                    info = tar.gettarinfo(str(path), arcname=str(relative))
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = epoch
                    if path.is_file():
                        with path.open("rb") as handle:
                            tar.addfile(info, handle)
                    else:
                        tar.addfile(info)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", required=True)
    parser.add_argument("--epoch", type=int, required=True)
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(args.sha) != 40 or any(character not in "0123456789abcdef" for character in args.sha):
        raise SystemExit("--sha must be a full lowercase Git SHA")
    for source in (args.assembly, args.frontend):
        if not source.is_dir():
            raise SystemExit(f"missing release input: {source}")
    args.output.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for name, source in (("cloud-assembly.tar.gz", args.assembly), ("frontend.tar.gz", args.frontend)):
        artifacts[name] = {"sha256": archive(source, args.output / name, args.epoch)}
    manifest = {
        "schema_version": 1,
        "release_sha": args.sha,
        "source_date_epoch": args.epoch,
        "artifacts": artifacts,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
