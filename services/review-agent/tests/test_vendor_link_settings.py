"""Resolution tests for vendor intake-link settings (base URL and sealed-link key)."""

from __future__ import annotations

import unittest
from unittest import mock

import _bootstrap  # noqa: F401

import review_agent.api as api_module
from review_agent.api import vendor_link_settings


class _StubSecretsClient:
    def __init__(self, secret_string: str | None = None, error: Exception | None = None) -> None:
        self._secret_string = secret_string
        self._error = error
        self.calls: list[dict] = []

    def get_secret_value(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"SecretString": self._secret_string}


class _StubBoto3:
    def __init__(self, client: _StubSecretsClient) -> None:
        self._client = client
        self.client_calls: list[tuple] = []

    def client(self, service_name, region_name=None):
        self.client_calls.append((service_name, region_name))
        return self._client


class VendorLinkSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        api_module._LINK_SECRET_CACHE.clear()
        self.addCleanup(api_module._LINK_SECRET_CACHE.clear)

    def test_defaults_use_simulated_base_url_and_no_secret(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            settings = vendor_link_settings()
        self.assertEqual(settings["intake_base_url"], "https://vetted.invalid/intake")
        self.assertIsNone(settings["link_secret"])

    def test_env_secret_wins_over_secret_arn(self) -> None:
        stub = _StubBoto3(_StubSecretsClient(secret_string="from-secrets-manager"))
        with mock.patch.dict(
            "os.environ",
            {
                "VENDOR_LINK_SECRET": "from-env",
                "VENDOR_LINK_SECRET_ARN": "arn:aws:...:secret:link",
            },
            clear=True,
        ), mock.patch.dict("sys.modules", {"boto3": stub}):
            settings = vendor_link_settings()
        self.assertEqual(settings["link_secret"], b"from-env")
        self.assertEqual(stub.client_calls, [])

    def test_secret_arn_resolves_and_caches_across_calls(self) -> None:
        client = _StubSecretsClient(secret_string="sealed-key")
        stub = _StubBoto3(client)
        env = {
            "VENDOR_LINK_SECRET_ARN": "arn:aws:...:secret:link",
            "VENDOR_INTAKE_BASE_URL": "https://d123.cloudfront.net/intake",
        }
        with mock.patch.dict("os.environ", env, clear=True), mock.patch.dict(
            "sys.modules", {"boto3": stub}
        ):
            first = vendor_link_settings()
            second = vendor_link_settings()
        self.assertEqual(first["link_secret"], b"sealed-key")
        self.assertEqual(second["link_secret"], b"sealed-key")
        self.assertEqual(first["intake_base_url"], "https://d123.cloudfront.net/intake")
        self.assertEqual(len(client.calls), 1)

    def test_secret_resolution_failure_degrades_to_process_local(self) -> None:
        stub = _StubBoto3(_StubSecretsClient(error=RuntimeError("boom")))
        with mock.patch.dict(
            "os.environ", {"VENDOR_LINK_SECRET_ARN": "arn:aws:...:secret:link"}, clear=True
        ), mock.patch.dict("sys.modules", {"boto3": stub}):
            settings = vendor_link_settings()
        self.assertIsNone(settings["link_secret"])

    def test_empty_secret_string_degrades_to_process_local(self) -> None:
        stub = _StubBoto3(_StubSecretsClient(secret_string=""))
        with mock.patch.dict(
            "os.environ", {"VENDOR_LINK_SECRET_ARN": "arn:aws:...:secret:link"}, clear=True
        ), mock.patch.dict("sys.modules", {"boto3": stub}):
            settings = vendor_link_settings()
        self.assertIsNone(settings["link_secret"])


if __name__ == "__main__":
    unittest.main()
