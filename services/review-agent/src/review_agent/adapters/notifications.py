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


# Module-level cache so warm Lambda invocations resolve the Secrets Manager
# webhook once per container rather than on every request. Keyed by secret ARN.
_SECRET_WEBHOOK_CACHE: dict[str, str] = {}


def _extract_webhook(secret_value: str) -> str | None:
    """Accept either a raw webhook URL or a JSON envelope ``{"webhook_url": ...}``."""
    text = secret_value.strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return None
        if isinstance(parsed, dict):
            candidate = parsed.get("webhook_url") or parsed.get("url")
            return candidate.strip() if isinstance(candidate, str) and candidate.strip() else None
        return None
    return text


def _resolve_secret_webhook(secret_arn: str, *, region: str | None) -> str | None:
    """Resolve a Slack webhook from Secrets Manager. Any failure returns ``None``.

    Never raises: a broken secret must degrade to the simulated fallback rather
    than crashing the request path. Successful resolutions are cached per ARN
    for warm-start reuse.
    """
    if secret_arn in _SECRET_WEBHOOK_CACHE:
        return _SECRET_WEBHOOK_CACHE[secret_arn]
    try:
        import boto3  # lazy: only needed when resolving a live AWS secret

        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_arn)
        raw = response.get("SecretString")
        if not raw:
            return None
        webhook = _extract_webhook(raw)
    except Exception:  # noqa: BLE001 - resolution failure degrades to simulated
        return None
    if webhook:
        _SECRET_WEBHOOK_CACHE[secret_arn] = webhook
    return webhook


def build_notifier(config: AppConfig, *, webhook_url: str | None = None) -> Notifier:
    """Live Slack when a webhook is configured; otherwise the simulated fallback.

    Resolution order for the webhook credential:

    1. an explicit ``webhook_url`` argument (tests / local live-ping demo),
    2. the ``SLACK_WEBHOOK_URL`` environment variable,
    3. a Secrets Manager secret named by ``SLACK_SECRET_ARN`` (the deployed
       path — the CDK stack injects this ARN and grants read access).

    Any failure to resolve the secret falls back to :class:`SimulatedNotifier`
    so a misconfigured or unreachable secret never crashes the request path.
    """
    import os

    channel = os.environ.get("SLACK_CHANNEL", "reviewers")
    url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL") or None
    if not url:
        secret_arn = os.environ.get("SLACK_SECRET_ARN") or None
        if secret_arn:
            region = getattr(getattr(config, "aws", None), "region", None)
            url = _resolve_secret_webhook(secret_arn, region=region)
    if url:
        return SlackWebhookNotifier(url, channel=channel)
    return SimulatedNotifier(channel=channel)
