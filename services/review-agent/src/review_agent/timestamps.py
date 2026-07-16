"""Timestamp parsing helpers for persistence and comparison boundaries."""

from __future__ import annotations

import datetime


def parse_utc_timestamp(value: str) -> datetime.datetime:
    """Parse ISO-8601 and interpret legacy naive values as UTC.

    Persisted timestamps predate strict timezone validation in a few fixtures.
    Treating those values as local machine time would make DynamoDB TTL/sort
    keys and reminder cadence environment-dependent, so naive means UTC.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO-8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def normalize_utc_timestamp(value: str) -> str:
    """Return a canonical aware UTC ISO-8601 timestamp."""

    return parse_utc_timestamp(value).isoformat()
