"""SSRF, DNS/IP, redirect, and URL destination controls (issue #44).

Every destination the research tool considers -- the initial target and every
redirect hop -- is validated here before any socket is opened. The controls,
each with an adversarial test:

* HTTPS scheme only; no credentials in the URL (``user:pass@`` or
  ``allowed.com@evil.com``); only allow-listed ports (443 by default).
* Host must be on the approved allowlist (the vendor's registrable domain or an
  explicitly configured standards authority). See :mod:`.domain`.
* Host must not be an IP literal in *any* numeric form (dotted, decimal, hex,
  octal, or IPv6), which blocks alternate-form SSRF targets.
* Every resolved DNS answer must be a global/public address. Loopback,
  link-local (including the ``169.254.169.254`` metadata endpoint), private,
  CGNAT, reserved, multicast, unspecified, and IPv4-mapped IPv6 forms are all
  refused. Because *all* answers are validated and one answer is pinned for the
  connection, DNS-rebinding and resolution drift cannot smuggle a private
  target past the check.

Nothing here performs I/O beyond DNS resolution through the injected resolver.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from .domain import DomainAllowlist
from .policy import ResearchPolicy


class ResearchBlocked(Exception):
    """A destination or response violated a research safety control.

    ``code`` is a stable, loggable reason (e.g. ``"private_ip"``); ``detail`` is
    a short human message. No response body or resolved secret is included.
    """

    def __init__(self, code: str, detail: str, *, url: str | None = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.url = url


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


def assert_public_ip(ip_text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Validate that ``ip_text`` is a routable public address or raise.

    IPv4-mapped IPv6 addresses are unwrapped and validated as their IPv4 form so
    ``::ffff:127.0.0.1`` cannot bypass the loopback check.
    """

    try:
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(ip_text)
    except ValueError as error:
        raise ResearchBlocked("unresolvable_ip", f"not an IP address: {ip_text}") from error

    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped

    blocked_flags = (
        ("loopback", address.is_loopback),
        ("link_local", address.is_link_local),  # covers 169.254.169.254 metadata
        ("private", address.is_private),
        ("reserved", address.is_reserved),
        ("multicast", address.is_multicast),
        ("unspecified", address.is_unspecified),
    )
    for reason, hit in blocked_flags:
        if hit:
            raise ResearchBlocked(f"{reason}_ip", f"non-public destination {address}")
    if not address.is_global:
        # Catches CGNAT (100.64.0.0/10) and other non-globally-routable space.
        raise ResearchBlocked("non_global_ip", f"non-public destination {address}")
    return address


def parse_destination(url: str, allowlist: DomainAllowlist, policy: ResearchPolicy) -> str:
    """Validate a single URL's scheme/credentials/port/host and return its host.

    Raises :class:`ResearchBlocked` on any violation. This does not resolve DNS;
    the caller resolves and validates every answer with :func:`assert_public_ip`.
    """

    if not isinstance(url, str) or not url.strip():
        raise ResearchBlocked("invalid_url", "empty URL", url=url if isinstance(url, str) else None)
    clean = url.strip()
    try:
        return _validate_destination(clean, allowlist, policy)
    except ResearchBlocked as blocked:
        if blocked.url is None:
            blocked.url = clean
        raise


def _validate_destination(url: str, allowlist: DomainAllowlist, policy: ResearchPolicy) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ResearchBlocked("scheme_not_https", f"scheme must be https, got {parsed.scheme!r}")
    if parsed.username or parsed.password:
        raise ResearchBlocked("credentialed_url", "credentials are not allowed in the URL")
    host = parsed.hostname
    if not host:
        raise ResearchBlocked("missing_host", "URL has no host")
    host = host.lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as error:
        raise ResearchBlocked("invalid_port", "URL has an invalid port") from error
    effective_port = port if port is not None else 443
    if effective_port not in policy.allowed_ports:
        raise ResearchBlocked("port_not_allowed", f"port {effective_port} is not allowed")
    if is_ip_literal_like(host):
        raise ResearchBlocked("ip_literal_host", f"host must be a DNS name, got {host!r}")
    if not allowlist.is_allowed(host):
        raise ResearchBlocked("off_domain", f"host {host!r} is not on the approved allowlist")
    return host
