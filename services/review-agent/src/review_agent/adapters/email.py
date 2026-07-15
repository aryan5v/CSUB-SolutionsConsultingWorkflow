"""Vendor email adapter (Amazon SES) with a truthful simulated fallback.

Mirrors the Slack notifier contract: an email is delivered **only** when live
AWS use is enabled and a verified sender address is configured. Otherwise the
system records a clearly labeled *simulated* send and never claims a real
delivery. The delivery mode is returned to the caller so it can be persisted on
an auditable integration event.

``boto3`` is imported lazily so the deterministic local slice stays
dependency-free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import AppConfig

_DEFAULT_SENDER = "no-reply@vetted.invalid"


@runtime_checkable
class EmailSender(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> dict:
        """Send/record one email and return delivery metadata."""
        ...


class SimulatedEmailSender:
    """Records labeled simulated sends; performs no network I/O."""

    def __init__(self, sender: str = _DEFAULT_SENDER) -> None:
        self._sender = sender
        self.sent: list[dict] = []

    def send(self, *, to: str, subject: str, body: str) -> dict:
        delivery = {
            "delivery": "simulated",
            "simulated": True,
            "channel": "email",
            "sender": self._sender,
            "to": to,
            "subject": subject,
            "body": body,
        }
        self.sent.append(delivery)
        return delivery


class SesEmailSender:
    """Amazon SES v2 implementation. Live delivery only.

    A failed live send is surfaced (``delivery == "failed"``) rather than being
    relabeled as a success or silently downgraded to simulated.
    """

    def __init__(self, *, sender: str, region: str, client: object | None = None) -> None:
        self._sender = sender
        self._region = region
        self._client = client

    def _ses(self):
        if self._client is None:
            import boto3  # lazy: only needed when talking to live AWS

            self._client = boto3.client("sesv2", region_name=self._region)
        return self._client

    def send(self, *, to: str, subject: str, body: str) -> dict:
        try:
            self._ses().send_email(
                FromEmailAddress=self._sender,
                Destination={"ToAddresses": [to]},
                Content={
                    "Simple": {
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                    }
                },
            )
            return {
                "delivery": "live",
                "simulated": False,
                "channel": "email",
                "sender": self._sender,
                "to": to,
                "subject": subject,
            }
        except Exception as error:  # noqa: BLE001 - delivery failure is data, not a crash
            return {
                "delivery": "failed",
                "simulated": False,
                "channel": "email",
                "sender": self._sender,
                "to": to,
                "subject": subject,
                "error": str(error),
            }


def build_email_sender(config: AppConfig, *, sender_address: str | None = None) -> EmailSender:
    """Live SES only with AWS enabled and a configured sender; else simulated."""
    import os

    sender = sender_address or os.environ.get("VENDOR_EMAIL_SENDER") or None
    if sender and not config.use_local_fakes:
        return SesEmailSender(sender=sender, region=config.aws.region)
    return SimulatedEmailSender(sender=sender or _DEFAULT_SENDER)
