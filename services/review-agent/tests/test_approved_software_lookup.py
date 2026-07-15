"""Approved-software lookup tier tests (FR-2)."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from review_agent.contracts.software import MatchMethod
from review_agent.lookup.approved_software import ApprovedSoftwareIndex
from review_agent.samples import sample_records


class LookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = ApprovedSoftwareIndex(sample_records())

    def test_exact_match(self) -> None:
        result = self.index.lookup("Zoom Workplace")
        self.assertTrue(result.matches)
        top = result.matches[0]
        self.assertEqual(top.match_method, MatchMethod.EXACT)
        self.assertFalse(top.requires_confirmation)
        self.assertEqual(top.score, 1.0)

    def test_alias_match(self) -> None:
        result = self.index.lookup("Acrobat")
        self.assertEqual(result.matches[0].match_method, MatchMethod.ALIAS)
        self.assertFalse(result.matches[0].requires_confirmation)

    def test_vendor_product_match(self) -> None:
        result = self.index.lookup("Workplace Meetings", vendor_name="Zoom")
        self.assertTrue(result.matches)
        self.assertEqual(result.matches[0].match_method, MatchMethod.VENDOR_PRODUCT)

    def test_fuzzy_requires_confirmation(self) -> None:
        result = self.index.lookup("Zoom Workplac")  # typo
        self.assertTrue(result.matches)
        self.assertEqual(result.matches[0].match_method, MatchMethod.FUZZY)
        self.assertTrue(result.matches[0].requires_confirmation)

    def test_semantic_disclosed_when_no_provider(self) -> None:
        result = self.index.lookup("Completely Unrelated Thing")
        self.assertEqual(result.matches, [])
        self.assertTrue(any("semantic search skipped" in d for d in result.disclosures))

    def test_source_row_reference_present(self) -> None:
        result = self.index.lookup("Zoom Workplace")
        self.assertTrue(result.matches[0].source_row_ref.source_id)


if __name__ == "__main__":
    unittest.main()
