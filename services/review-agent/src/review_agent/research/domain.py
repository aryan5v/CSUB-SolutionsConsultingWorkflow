"""Registrable-domain derivation and the research host allowlist (issue #44).

The approved research boundary is derived from the reviewer/vendor-confirmed
official (trust-center) URL: the agent may fetch only that URL's registrable
domain (and its subdomains) plus explicitly configured standards authorities. A
candidate host is on-domain only when it equals the registrable domain or is a
subdomain of it, so ``docs.vendor.com`` is allowed for ``vendor.com`` while the
look-alike ``vendor.com.evil.example`` is not.

Registrable-domain computation uses a small built-in set of multi-label public
suffixes plus a "last two labels" fallback. This is intentionally simple and
dependency-free; it is a *conservative* boundary (it can only ever widen to a
shorter suffix, never cross to an unrelated registrable domain) and is
documented as an assumption. It is not a substitute for the full Public Suffix
List, which a production deployment behind AgentCore Browser should adopt.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

# A deliberately small set of multi-label public suffixes so that, for example,
# ``vendor.co.uk`` resolves to the registrable domain ``vendor.co.uk`` rather
# than the public suffix ``co.uk``. Extend via configuration if needed; this is
# not campus policy, only a parsing aid.
_MULTI_LABEL_SUFFIXES: frozenset[str] = frozenset(
    {
        "co.uk",
        "org.uk",
        "ac.uk",
        "gov.uk",
        "com.au",
        "net.au",
        "org.au",
        "edu.au",
        "co.nz",
        "co.jp",
        "com.br",
        "com.mx",
        "co.in",
        "com.sg",
        "com.cn",
    }
)


class DomainError(ValueError):
    """Raised when a host/URL cannot yield a usable registrable domain."""


def _normalize_host(host: str) -> str:
    value = (host or "").strip().lower().rstrip(".")
    if not value:
        raise DomainError("empty host")
    return value


def registrable_domain(host: str) -> str:
    """Return the registrable domain (eTLD+1) for ``host``.

    Raises :class:`DomainError` for empty input or a bare single-label host.
    """

    value = _normalize_host(host)
    labels = value.split(".")
    if len(labels) < 2 or any(not label for label in labels):
        raise DomainError(f"host {host!r} has no registrable domain")
    last_two = ".".join(labels[-2:])
    if last_two in _MULTI_LABEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def registrable_domain_from_url(url: str) -> str:
    """Return the registrable domain for an HTTPS URL's host."""

    parsed = urlsplit((url or "").strip())
    host = parsed.hostname
    if not host:
        raise DomainError(f"URL {url!r} has no host")
    return registrable_domain(host)


def _host_in_zone(host: str, zone: str) -> bool:
    return host == zone or host.endswith("." + zone)


@dataclass(frozen=True, slots=True)
class DomainAllowlist:
    """The set of host zones the research tool may fetch.

    ``vendor_domain`` is the approved registrable domain; ``standards_authorities``
    are explicitly configured recognized standards hosts (empty by default).
    """

    vendor_domain: str
    standards_authorities: tuple[str, ...] = ()

    @classmethod
    def derive(
        cls, official_url: str, standards_authorities: tuple[str, ...] = ()
    ) -> DomainAllowlist:
        vendor_domain = registrable_domain_from_url(official_url)
        cleaned = tuple(
            sorted(
                {
                    _normalize_host(host)
                    for host in standards_authorities
                    if host and host.strip()
                }
            )
        )
        return cls(vendor_domain=vendor_domain, standards_authorities=cleaned)

    def is_allowed(self, host: str) -> bool:
        try:
            candidate = _normalize_host(host)
        except DomainError:
            return False
        if _host_in_zone(candidate, self.vendor_domain):
            return True
        return any(_host_in_zone(candidate, zone) for zone in self.standards_authorities)

    def scope_of(self, host: str) -> str | None:
        """Return ``"official_vendor"`` / ``"standards"`` / ``None`` for ``host``."""

        try:
            candidate = _normalize_host(host)
        except DomainError:
            return None
        if _host_in_zone(candidate, self.vendor_domain):
            return "official_vendor"
        if any(_host_in_zone(candidate, zone) for zone in self.standards_authorities):
            return "standards"
        return None
