"""Deterministic tool-safety limits for official-domain vendor research.

These are *operational* limits on a fetch tool (how many bytes, how many
redirects, which ports and content types are acceptable), not campus policy
thresholds or risk tiers. They live in configuration, outside any model prompt,
so a model can never widen them (AGENTS.md AI trust boundaries; PRD sec 7).

Every value is env-overridable so an administrator can tune the boundary for the
approved environment without code changes. Standards authorities default to an
**empty** list: the agent researches only the vendor's own registrable domain
until an administrator explicitly configures recognized standards sites. This
avoids inventing an allowlist of external domains (AGENTS.md: do not invent
policy or data sources).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

# Content types acceptable as vendor trust-center evidence. Anything else is a
# gap for manual review rather than an accepted, hashed source.
_DEFAULT_CONTENT_TYPES: tuple[str, ...] = (
    "application/pdf",
    "text/html",
    "application/xhtml+xml",
    "text/plain",
)

# Only the HTTPS port. HTTP and every alternate/administrative port are refused.
_DEFAULT_PORTS: tuple[int, ...] = (443,)

# Default tool-safety limits, defined once so both the dataclass defaults and
# ``from_env`` reference the same values without touching class attributes.
_DEFAULT_MAX_REDIRECTS = 3
_DEFAULT_MAX_RESPONSE_BYTES = 5_000_000
_DEFAULT_MAX_DOWNLOADS = 10
_DEFAULT_TOTAL_DEADLINE_SECONDS = 30.0
_DEFAULT_PER_REQUEST_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True, slots=True)
class ResearchPolicy:
    """Immutable fetch-safety limits.

    ``allow_agentcore_browser`` stays ``False`` until the approved account is
    confirmed to permit it; the same SSRF/redirect/provenance boundary is
    enforced regardless of which provider transport is used (issue #44).
    """

    max_redirects: int = _DEFAULT_MAX_REDIRECTS
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES
    max_downloads: int = _DEFAULT_MAX_DOWNLOADS
    total_deadline_seconds: float = _DEFAULT_TOTAL_DEADLINE_SECONDS
    per_request_timeout_seconds: float = _DEFAULT_PER_REQUEST_TIMEOUT_SECONDS
    allowed_ports: tuple[int, ...] = _DEFAULT_PORTS
    allowed_content_types: tuple[str, ...] = _DEFAULT_CONTENT_TYPES
    standards_authorities: tuple[str, ...] = ()
    allow_agentcore_browser: bool = False

    def with_standards_authorities(self, hosts: tuple[str, ...]) -> ResearchPolicy:
        return replace(self, standards_authorities=hosts)

    @classmethod
    def from_env(cls) -> ResearchPolicy:
        return cls(
            max_redirects=_non_negative_int_env(
                "RESEARCH_MAX_REDIRECTS", _DEFAULT_MAX_REDIRECTS
            ),
            max_response_bytes=_positive_int_env(
                "RESEARCH_MAX_RESPONSE_BYTES", _DEFAULT_MAX_RESPONSE_BYTES
            ),
            max_downloads=_positive_int_env("RESEARCH_MAX_DOWNLOADS", _DEFAULT_MAX_DOWNLOADS),
            total_deadline_seconds=_positive_float_env(
                "RESEARCH_TOTAL_DEADLINE_SECONDS", _DEFAULT_TOTAL_DEADLINE_SECONDS
            ),
            per_request_timeout_seconds=_positive_float_env(
                "RESEARCH_PER_REQUEST_TIMEOUT_SECONDS", _DEFAULT_PER_REQUEST_TIMEOUT_SECONDS
            ),
            allowed_ports=_int_tuple_env("RESEARCH_ALLOWED_PORTS", _DEFAULT_PORTS),
            allowed_content_types=_str_tuple_env(
                "RESEARCH_ALLOWED_CONTENT_TYPES", _DEFAULT_CONTENT_TYPES
            ),
            standards_authorities=_host_tuple_env("RESEARCH_STANDARDS_AUTHORITIES", ()),
            allow_agentcore_browser=os.environ.get(
                "RESEARCH_ALLOW_AGENTCORE_BROWSER", "false"
            ).lower()
            == "true",
        )


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _non_negative_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _int_tuple_env(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    raw = os.environ.get(name)
    if not raw:
        return default
    values: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError:
            continue
    return tuple(values) or default


def _str_tuple_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if not raw:
        return default
    values = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    return values or default


def _host_tuple_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if not raw:
        return default
    values = tuple(part.strip().lower().rstrip(".") for part in raw.split(",") if part.strip())
    return values or default
