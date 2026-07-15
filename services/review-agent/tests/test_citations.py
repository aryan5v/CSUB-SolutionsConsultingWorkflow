"""Citation trust-boundary regression tests."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from review_agent.specialists.citations import check_citations


class CitationCheckTests(unittest.TestCase):
    def test_null_source_is_rejected_without_crashing(self) -> None:
        claim = {
            "claim": "A malformed model citation",
            "citations": [{"scope": "case_evidence", "source": None}],
        }

        result = check_citations(
            [claim], case_vendor="Example Vendor", case_product="Example Product"
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.rejected, [claim])
        self.assertIn("citation missing source_id", result.reasons)


if __name__ == "__main__":
    unittest.main()
