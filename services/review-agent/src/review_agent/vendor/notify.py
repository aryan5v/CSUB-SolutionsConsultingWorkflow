"""Vendor and committee notifications when the upload link is sent.

Like the ServiceNow write-back, notifications are simulated and labeled until a
real channel (SES/SNS) is approved: the mock records what *would* be sent so the
flow and audit trail are exercised without emailing anyone. A real SES/SNS
notifier must satisfy the same ``Notifier`` protocol and keep credentials in
Secrets Manager.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..contracts.vendor import NotificationReceipt, VendorInvite, VendorPortalLink


@runtime_checkable
class Notifier(Protocol):
    def notify_vendor(
        self, invite: VendorInvite, link: VendorPortalLink
    ) -> NotificationReceipt: ...

    def notify_committee(
        self, invite: VendorInvite, link: VendorPortalLink
    ) -> list[NotificationReceipt]: ...


class MockNotifier:
    """In-memory notifier: records simulated notifications for tests/demo."""

    def __init__(self) -> None:
        self.sent: list[NotificationReceipt] = []

    def notify_vendor(self, invite: VendorInvite, link: VendorPortalLink) -> NotificationReceipt:
        receipt = NotificationReceipt(
            audience="vendor",
            channel="email",
            recipient=invite.vendor_recipient,
            subject=(
                f"CSUB Solutions Consulting: submit compliance evidence for "
                f"{invite.product}"
            ),
            reference=invite.token,
        )
        self.sent.append(receipt)
        return receipt

    def notify_committee(
        self, invite: VendorInvite, link: VendorPortalLink
    ) -> list[NotificationReceipt]:
        receipts = [
            NotificationReceipt(
                audience="committee",
                channel="email",
                recipient=recipient,
                subject=(
                    f"Vendor evidence requested: {invite.vendor} / {invite.product} "
                    f"(case {invite.case_id})"
                ),
                reference=invite.token,
            )
            for recipient in invite.committee_recipients
        ]
        self.sent.extend(receipts)
        return receipts
