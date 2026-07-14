from __future__ import annotations

import unittest
from pathlib import Path

from scripts import scan_secrets, validate_repo


class SecretScanTests(unittest.TestCase):
    def test_detects_aws_key_shape(self) -> None:
        candidate = "A" + "KIA" + ("A" * 16)
        findings = scan_secrets.findings_for_text(Path("fixture.txt"), candidate)
        self.assertEqual(findings, ["fixture.txt:1: possible AWS access key"])

    def test_detects_github_pat_shape(self) -> None:
        candidate = "github_pat_" + ("A" * 20)
        findings = scan_secrets.findings_for_text(Path("fixture.txt"), candidate)
        self.assertEqual(findings, ["fixture.txt:1: possible GitHub fine-grained token"])

    def test_ignores_normal_text(self) -> None:
        self.assertEqual(
            scan_secrets.findings_for_text(Path("fixture.txt"), "ordinary text"),
            [],
        )


class RepositoryValidationTests(unittest.TestCase):
    def test_required_foundation_files_exist(self) -> None:
        errors: list[str] = []
        validate_repo.validate_required_files(errors)
        self.assertEqual(errors, [])

    def test_prd_coverage_is_present(self) -> None:
        errors: list[str] = []
        validate_repo.validate_prd_coverage(errors)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
