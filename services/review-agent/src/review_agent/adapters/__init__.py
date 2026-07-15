"""Provider adapters. Each AWS/external boundary is a small interface with a
local fake for the Tuesday slice and a documented seam for Wednesday's wiring."""

from __future__ import annotations

from .model import BedrockModelClient, DeterministicModelClient, ModelClient
from .notifications import Notifier, SimulatedNotifier, SlackWebhookNotifier, build_notifier
from .servicenow import (
    ConnectorError,
    MockServiceNowConnector,
    ServiceNowConnector,
    StaleRecordError,
    UnapprovedWriteError,
    UnknownRecordError,
)
from .storage import InMemoryStorage, S3Storage, StorageClient

__all__ = [
    "BedrockModelClient",
    "ConnectorError",
    "DeterministicModelClient",
    "InMemoryStorage",
    "MockServiceNowConnector",
    "ModelClient",
    "Notifier",
    "S3Storage",
    "ServiceNowConnector",
    "SimulatedNotifier",
    "SlackWebhookNotifier",
    "StaleRecordError",
    "StorageClient",
    "UnapprovedWriteError",
    "UnknownRecordError",
    "build_notifier",
]
