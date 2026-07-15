"""Notification adapter (Slack) with a truthful simulated fallback.

Truthfulness rule (issue #27): a notification is delivered to Slack **only** when
a webhook credential is configured. Otherwise the system persists a clearly
labeled *simulated* notification event and never claims a real delivery. The
delivery mode is reported back to the caller so it can be recorded on an
auditable integration event.

``urllib`` is used for the live POST so the local slice stays dependency-free.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import AppConfig


@runtime_checkable
class Notifier(Protocol):
    def notify(self, *, event_type: str, summary: str, detail: dict | None = None) -> dict:
        """Send/record a notification and return delivery metadata."""
        ...


class SimulatedNotifier:
    """Records a labeled simulated notification; performs no network I/O."""

    def __init__(self, channel: str = "reviewers") -> None:
        self._channel = channel

    def notify(self, *, event_type: str, summary: str, detail: dict | None = None) -> dict:
        return {
            "delivery": "simulated",
            "simulated": True,
            "channel": self._channel,
            "event_type": event_type,
            "summary": summary,
        }


class SlackWebhookNotifier:
    """Posts to a Slack incoming webhook. Live delivery only.

    A failed live send is surfaced (``delivery == "failed"``) rather than being
    relabeled as a success or silently downgraded to simulated.
    """

    def __init__(self, webhook_url: str, *, channel: str = "reviewers", timeout: float = 3.0) -> None:
        self._webhook_url = webhook_url
        self._channel = channel
        self._timeout = timeout
        self._opener = urllib.request.urlopen

    def notify(self, *, event_type: str, summary: str, detail: dict | None = None) -> dict:
        payload = json.dumps({"text": f"[{event_type}] {summary}"}).encode("utf-8")
        request = urllib.request.Request(
            self._webhook_url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                status = getattr(response, "status", 200)
            return {
                "delivery": "live",
                "simulated": False,
                "channel": self._channel,
                "event_type": event_type,
                "summary": summary,
                "status": status,
            }
        except (urllib.error.URLError, OSError) as error:
            return {
                "delivery": "failed",
                "simulated": False,
                "channel": self._channel,
                "event_type": event_type,
                "summary": summary,
                "error": str(error),
            }


def build_notifier(config: AppConfig, *, webhook_url: str | None = None) -> Notifier:
    """Live Slack when a webhook is configured; otherwise the simulated fallback."""
    import os

    url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL") or None
    channel = os.environ.get("SLACK_CHANNEL", "reviewers")
    if url:
        return SlackWebhookNotifier(url, channel=channel)
    return SimulatedNotifier(channel=channel)
