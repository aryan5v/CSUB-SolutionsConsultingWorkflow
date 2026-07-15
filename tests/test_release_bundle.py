from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.deploy.package_release import archive
from scripts.deploy.verify_release import safe_extract, verify


class ReleaseBundleTests(unittest.TestCase):
    def test_archive_is_reproducible_for_same_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "index.html").write_text("VETTED\n", encoding="utf-8")
            first = root / "first.tar.gz"
            second = root / "second.tar.gz"
            self.assertEqual(archive(source, first, 1_721_000_000), archive(source, second, 1_721_000_000))
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_verifier_rejects_tampered_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            for name in ("cloud-assembly.tar.gz", "frontend.tar.gz"):
                (bundle / name).write_bytes(b"tampered")
            manifest = {
                "schema_version": 1,
                "release_sha": "a" * 40,
                "artifacts": {
                    name: {"sha256": "0" * 64}
                    for name in ("cloud-assembly.tar.gz", "frontend.tar.gz")
                },
            }
            (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                verify(bundle, "a" * 40)

    def test_safe_extract_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "unsafe.tar.gz"
            with tarfile.open(archive_path, "w:gz") as bundle:
                payload = b"escape"
                member = tarfile.TarInfo("../escape.txt")
                member.size = len(payload)
                bundle.addfile(member, io.BytesIO(payload))
            with self.assertRaisesRegex(ValueError, "unsafe archive member"):
                safe_extract(archive_path, root / "output")


if __name__ == "__main__":
    unittest.main()
