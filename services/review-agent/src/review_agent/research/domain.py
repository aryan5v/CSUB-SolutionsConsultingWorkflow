"""Fail-closed host allowlist for official-domain research (issue #44).

The approved research boundary is the **exact reviewer/vendor-confirmed host**
taken from the official (trust-center) URL, plus that host's own subdomains, plus
any explicitly configured standards authorities. There is deliberately **no**
registrable-domain / public-suffix guessing: guessing "last two labels" is unsafe
for multi-tenant public suffixes such as ``github.io`` or ``appspot.com``, where
``attacker.github.io`` and ``vendor.github.io`` share a "registrable domain" but
belong to different tenants.

Consequences of the exact-host model:

* ``trust.vendor.com`` allows ``trust.vendor.com`` and ``*.trust.vendor.com``.
* A *sibling* host (``docs.vendor.com`` when the confirmed host is
  ``trust.vendor.com``) and the parent apex (``vendor.com``) are **not**
  auto-allowed; they are treated as off-domain and quarantined for explicit
  human confirmation.
* ``vendor.github.io`` never allows ``attacker.github.io``.

This is fail-closed: an unrecognized host is refused, never guessed. Widening the
boundary to a parent domain or sibling host is a human decision, not a parsing
heuristic. A full Public Suffix List is intentionally not adopted here; it would
break the dependency-free local slice (see docs/ENGINEERING.md dependency
policy) and is unnecessary once the boundary is the exact confirmed host.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit


class DomainError(ValueError):
    """Raised when a host/URL cannot yield a usable confirmed host."""


def is_ip_literal_like(host: str) -> bool:
    """Return ``True`` if ``host`` could be interpreted as a numeric IP address.

    Catches standard dotted IPv4/IPv6 plus the alternate forms attackers use to
    dodge naive string checks: decimal (``2130706433``), hex (``0x7f000001``),
    octal (``017700000001``), and short dotted (``127.1``).
    """

    value = host.strip().strip("[]")
    if not value:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    if value.isdigit():
        return True
    labels = value.split(".")
    for label in labels:
        lowered = label.lower()
        if lowered.startswith("0x"):
            return True
        if len(lowered) > 1 and lowered.startswith("0") and lowered.isdigit():
            return True
    return bool(labels) and all(label.isdigit() for label in labels)


def _normalize_host(host: str) -> str:
    value = (host or "").strip().lower().rstrip(".")
    if not value:
        raise DomainError("empty host")
    return value


def validate_public_dns_host(host: str) -> str:
    """Normalize and validate a public DNS host, or raise :class:`DomainError`.

    Rejects IP literals (any numeric form), single-label hosts, and hosts with
    malformed labels. This is the confirmed host the allowlist is built from.
    """

    value = _normalize_host(host)
    if is_ip_literal_like(value):
        raise DomainError(f"host {host!r} is an IP literal, not a DNS name")
    labels = value.split(".")
    if len(labels) < 2:
        raise DomainError(f"host {host!r} must be a multi-label DNS name")
    for label in labels:
        if (
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not all(char.isalnum() or char == "-" for char in label)
        ):
            raise DomainError(f"host {host!r} has an invalid DNS label {label!r}")
    return value


def confirmed_host_from_url(url: str) -> str:
    """Return the validated confirmed host for an HTTPS official/trust-center URL."""

    parsed = urlsplit((url or "").strip())
    host = parsed.hostname
    if not host:
        raise DomainError(f"URL {url!r} has no host")
    return validate_public_dns_host(host)


def _host_in_zone(host: str, zone: str) -> bool:
    return host == zone or host.endswith("." + zone)


@dataclass(frozen=True, slots=True)
class DomainAllowlist:
    """The set of host zones the research tool may fetch.

    ``confirmed_host`` is the exact reviewer/vendor-confirmed host; its subdomains
    are included. ``standards_authorities`` are explicitly configured recognized
    standards hosts (empty by default), each also matched as host + subdomains.
    """

    confirmed_host: str
    standards_authorities: tuple[str, ...] = ()

    @classmethod
    def derive(
        cls, official_url: str, standards_authorities: tuple[str, ...] = ()
    ) -> DomainAllowlist:
        confirmed_host = confirmed_host_from_url(official_url)
        cleaned = tuple(
            sorted(
                {
                    validate_public_dns_host(host)
                    for host in standards_authorities
                    if host and host.strip()
                }
            )
        )
        return cls(confirmed_host=confirmed_host, standards_authorities=cleaned)

    def is_allowed(self, host: str) -> bool:
        try:
            candidate = _normalize_host(host)
        except DomainError:
            return False
        if _host_in_zone(candidate, self.confirmed_host):
            return True
        return any(_host_in_zone(candidate, zone) for zone in self.standards_authorities)

    def scope_of(self, host: str) -> str | None:
        """Return ``"official_vendor"`` / ``"standards"`` / ``None`` for ``host``."""

        try:
            candidate = _normalize_host(host)
        except DomainError:
            return None
        if _host_in_zone(candidate, self.confirmed_host):
            return "official_vendor"
        if any(_host_in_zone(candidate, zone) for zone in self.standards_authorities):
            return "standards"
        return None
