"""Truthful delivery-labeling tests for the vendor email adapter."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.email import (
    SesEmailSender,
    SimulatedEmailSender,
    build_email_sender,
)
from review_agent.config import AppConfig


class _StubSesClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict] = []

    def send_email(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"MessageId": "stub-message"}


class EmailAdapterTests(unittest.TestCase):
    def test_local_fakes_default_to_simulated_sender(self) -> None:
        sender = build_email_sender(AppConfig())
        self.assertIsInstance(sender, SimulatedEmailSender)
        delivery = sender.send(to="vendor@example.com", subject="s", body="b")
        self.assertEqual(delivery["delivery"], "simulated")
        self.assertTrue(delivery["simulated"])
        self.assertEqual(delivery["channel"], "email")

    def test_live_send_reports_live_delivery(self) -> None:
        client = _StubSesClient()
        sender = SesEmailSender(sender="no-reply@campus.example", region="us-west-2", client=client)
        delivery = sender.send(to="vendor@example.com", subject="Outcome", body="Body")
        self.assertEqual(delivery["delivery"], "live")
        self.assertFalse(delivery["simulated"])
        self.assertEqual(client.calls[0]["Destination"]["ToAddresses"], ["vendor@example.com"])

    def test_failed_live_send_is_surfaced_not_relabeled(self) -> None:
        sender = SesEmailSender(
            sender="no-reply@campus.example",
            region="us-west-2",
            client=_StubSesClient(error=RuntimeError("ses unavailable")),
        )
        delivery = sender.send(to="vendor@example.com", subject="Outcome", body="Body")
        self.assertEqual(delivery["delivery"], "failed")
        self.assertFalse(delivery["simulated"])
        self.assertIn("ses unavailable", delivery["error"])


if __name__ == "__main__":
    unittest.main()
