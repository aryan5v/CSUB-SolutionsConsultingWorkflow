from __future__ import annotations

import importlib.util
import io
import pathlib
import unittest
import urllib.error
from unittest.mock import patch

SCRIPT_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "canary_vendor_invitation.py"
SPEC = importlib.util.spec_from_file_location("canary_vendor_invitation", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load invitation canary")
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)


class CanaryVendorInvitationTests(unittest.TestCase):
    def test_http_errors_preserve_status_without_exposing_non_json_bodies_or_token(self) -> None:
        scenarios = (
            (502, b"", "empty response"),
            (503, b"<html>private upstream details</html>", "non-JSON response"),
            (500, b'{"error":', "malformed JSON response"),
        )
        vendor_token = "opaque-vendor-token-must-not-be-logged"

        for status, response_body, expected_detail in scenarios:
            with self.subTest(status=status, detail=expected_detail):
                error = urllib.error.HTTPError(
                    "https://api.example/vendor/invites/current",
                    status,
                    "synthetic error",
                    {"X-Correlation-Id": "server-reference"},
                    io.BytesIO(response_body),
                )
                with patch.object(canary.urllib.request, "urlopen", side_effect=error):
                    with self.assertRaises(canary.CanaryFailure) as raised:
                        canary.request_json(
                            "https://api.example",
                            "reviewer-token",
                            "GET",
                            "/vendor/invites/current",
                            vendor_token=vendor_token,
                            expected_status=200,
                        )

                message = str(raised.exception)
                self.assertIn(f"HTTP {status}", message)
                self.assertIn(expected_detail, message)
                self.assertIn("reference server-reference", message)
                self.assertNotIn(vendor_token, message)
                self.assertNotIn("private upstream details", message)
                if response_body:
                    self.assertNotIn(response_body.decode("utf-8", errors="ignore"), message)

    def test_expected_status_with_malformed_json_reports_status_and_bounded_detail(self) -> None:
        class Response:
            status = 200
            headers = {"X-Correlation-Id": "server-reference"}

            @staticmethod
            def read(_limit: int) -> bytes:
                return b"not-json-and-not-for-logs"

            @staticmethod
            def close() -> None:
                return None

        with patch.object(canary.urllib.request, "urlopen", return_value=Response()):
            with self.assertRaises(canary.CanaryFailure) as raised:
                canary.request_json(
                    "https://api.example",
                    "reviewer-token",
                    "GET",
                    "/health",
                    expected_status=200,
                )

        message = str(raised.exception)
        self.assertIn("HTTP 200", message)
        self.assertIn("malformed JSON response", message)
        self.assertNotIn("not-json-and-not-for-logs", message)


if __name__ == "__main__":
    unittest.main()
