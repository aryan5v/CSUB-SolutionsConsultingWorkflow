"""Truthful delivery-labeling and secret-resolution tests for the Slack notifier."""

from __future__ import annotations

import json
import unittest
from unittest import mock

import _bootstrap  # noqa: F401

from review_agent.adapters import notifications
from review_agent.adapters.notifications import (
    SimulatedNotifier,
    SlackWebhookNotifier,
    build_notifier,
)
from review_agent.config import AppConfig


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


class NotifierResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        notifications._SECRET_WEBHOOK_CACHE.clear()
        self.addCleanup(notifications._SECRET_WEBHOOK_CACHE.clear)

    def test_no_credential_defaults_to_simulated(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            notifier = build_notifier(AppConfig())
        self.assertIsInstance(notifier, SimulatedNotifier)

    def test_explicit_webhook_argument_wins(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            notifier = build_notifier(AppConfig(), webhook_url="https://hooks.slack.com/x")
        self.assertIsInstance(notifier, SlackWebhookNotifier)

    def test_env_webhook_used(self) -> None:
        with mock.patch.dict(
            "os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/env"}, clear=True
        ):
            notifier = build_notifier(AppConfig())
        self.assertIsInstance(notifier, SlackWebhookNotifier)

    def test_secret_arn_raw_url_resolves_to_live(self) -> None:
        stub = _StubBoto3(_StubSecretsClient(secret_string="https://hooks.slack.com/secret"))
        with mock.patch.dict(
            "os.environ", {"SLACK_SECRET_ARN": "arn:aws:...:secret:slack"}, clear=True
        ), mock.patch.dict("sys.modules", {"boto3": stub}):
            notifier = build_notifier(AppConfig())
        self.assertIsInstance(notifier, SlackWebhookNotifier)
        self.assertEqual(stub.client_calls[0][0], "secretsmanager")

    def test_secret_arn_json_envelope_resolves_to_live(self) -> None:
        secret = json.dumps({"webhook_url": "https://hooks.slack.com/json"})
        stub = _StubBoto3(_StubSecretsClient(secret_string=secret))
        with mock.patch.dict(
            "os.environ", {"SLACK_SECRET_ARN": "arn:aws:...:secret:slack"}, clear=True
        ), mock.patch.dict("sys.modules", {"boto3": stub}):
            notifier = build_notifier(AppConfig())
        self.assertIsInstance(notifier, SlackWebhookNotifier)

    def test_secret_resolution_failure_degrades_to_simulated(self) -> None:
        stub = _StubBoto3(_StubSecretsClient(error=RuntimeError("boom")))
        with mock.patch.dict(
            "os.environ", {"SLACK_SECRET_ARN": "arn:aws:...:secret:slack"}, clear=True
        ), mock.patch.dict("sys.modules", {"boto3": stub}):
            notifier = build_notifier(AppConfig())
        self.assertIsInstance(notifier, SimulatedNotifier)

    def test_empty_secret_degrades_to_simulated(self) -> None:
        stub = _StubBoto3(_StubSecretsClient(secret_string=""))
        with mock.patch.dict(
            "os.environ", {"SLACK_SECRET_ARN": "arn:aws:...:secret:slack"}, clear=True
        ), mock.patch.dict("sys.modules", {"boto3": stub}):
            notifier = build_notifier(AppConfig())
        self.assertIsInstance(notifier, SimulatedNotifier)

    def test_warm_start_cache_resolves_secret_once(self) -> None:
        client = _StubSecretsClient(secret_string="https://hooks.slack.com/cached")
        stub = _StubBoto3(client)
        with mock.patch.dict(
            "os.environ", {"SLACK_SECRET_ARN": "arn:aws:...:secret:slack"}, clear=True
        ), mock.patch.dict("sys.modules", {"boto3": stub}):
            first = build_notifier(AppConfig())
            second = build_notifier(AppConfig())
        self.assertIsInstance(first, SlackWebhookNotifier)
        self.assertIsInstance(second, SlackWebhookNotifier)
        self.assertEqual(len(client.calls), 1)

    def test_env_webhook_takes_precedence_over_secret(self) -> None:
        stub = _StubBoto3(_StubSecretsClient(secret_string="https://hooks.slack.com/secret"))
        with mock.patch.dict(
            "os.environ",
            {
                "SLACK_WEBHOOK_URL": "https://hooks.slack.com/env",
                "SLACK_SECRET_ARN": "arn:aws:...:secret:slack",
            },
            clear=True,
        ), mock.patch.dict("sys.modules", {"boto3": stub}):
            build_notifier(AppConfig())
        self.assertEqual(stub.client_calls, [])


if __name__ == "__main__":
    unittest.main()
