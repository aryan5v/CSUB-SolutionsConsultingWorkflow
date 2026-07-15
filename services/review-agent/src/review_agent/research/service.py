"""Official-domain vendor research behind a small, guarded provider interface.

The research capability is expressed as two tiny interfaces so the deterministic
safety logic is testable without a network and the provider is replaceable:

* :class:`Resolver` -- turns a host into a list of IP strings. The default uses
  ``socket.getaddrinfo``; tests inject a fake to simulate rebinding / drift.
* :class:`HttpTransport` -- performs *one* non-redirecting HTTPS request pinned
  to a pre-validated IP and returns a size-capped :class:`RawResponse`. The
  default is a stdlib ``http.client`` implementation; an AgentCore Browser
  provider would implement the same interface and is used only when the approved
  account permits it (``ResearchPolicy.allow_agentcore_browser``). Either way the
  same SSRF/redirect/provenance boundary is enforced here.

:class:`VendorResearchService` owns the deterministic control flow: derive the
allowlist, validate every URL and every redirect hop, resolve and validate every
DNS answer, pin one validated IP for the connection, enforce content-type / size
/ redirect / download / time limits, capture provenance, quarantine off-domain
links, treat retrieved content as untrusted, and turn every failure into a gap
for manual review rather than a silent compliant finding.
"""

from __future__ import annotations

import datetime
import hashlib
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from urllib.parse import urljoin, urlsplit

from ..institutional.untrusted import scan_untrusted_text
from .domain import DomainAllowlist, DomainError
from .policy import ResearchPolicy
from .provenance import (
    ProvenanceRecord,
    QuarantinedLink,
    ResearchFinding,
    ResearchGap,
    ResearchResult,
)
from .ssrf import ResearchBlocked, assert_public_ip, parse_destination

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_ABS_HTTPS_URL = re.compile(r"https://[^\s\"'<>()\[\]]+", re.IGNORECASE)


class ResearchError(Exception):
    """A non-security failure (transport/DNS error) that becomes a gap."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class RawResponse:
    """One HTTP response from a transport. Headers are lower-cased keys.

    ``oversized`` is set by the transport when the body exceeded the byte cap it
    was given; the service treats that as a blocked destination.
    """

    status: int
    headers: dict[str, str]
    body: bytes
    connected_ip: str
    oversized: bool = False


@runtime_checkable
class Resolver(Protocol):
    def resolve(self, host: str) -> list[str]:
        """Return all A/AAAA IP strings for ``host`` (never empty on success)."""
        ...


@runtime_checkable
class HttpTransport(Protocol):
    def fetch(
        self, *, ip: str, host: str, url: str, timeout: float, max_bytes: int
    ) -> RawResponse:
        """Issue one non-redirecting HTTPS GET pinned to ``ip`` with ``Host: host``."""
        ...


class SystemResolver:
    """Default resolver using ``socket.getaddrinfo`` (deduplicated)."""

    def resolve(self, host: str) -> list[str]:
        import socket

        try:
            infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror as error:
            raise ResearchError("dns_error", f"could not resolve {host}") from error
        seen: list[str] = []
        for info in infos:
            address = info[4][0]
            if address not in seen:
                seen.append(address)
        if not seen:
            raise ResearchError("dns_empty", f"no addresses for {host}")
        return seen


class GuardedHttpTransport:
    """Stdlib ``http.client`` transport pinned to a validated IP.

    The socket is opened to the pre-validated IP while TLS SNI and certificate
    validation use the real hostname, so the connection can never drift to a
    different address than the one the service validated. Redirects are never
    followed here; the service re-validates each hop. Not exercised in CI (no
    network); documented seam for the deployed environment.
    """

    def fetch(
        self, *, ip: str, host: str, url: str, timeout: float, max_bytes: int
    ) -> RawResponse:  # pragma: no cover - requires network
        import http.client
        import socket
        import ssl

        parsed = urlsplit(url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        context = ssl.create_default_context()
        conn: http.client.HTTPSConnection | None = None
        raw_sock: socket.socket | None = None
        tls_sock: ssl.SSLSocket | None = None
        response = None
        try:
            raw_sock = socket.create_connection((ip, 443), timeout=timeout)
            tls_sock = context.wrap_socket(raw_sock, server_hostname=host)
            # Inject the already-connected, IP-pinned TLS socket so http.client
            # never calls connect() again (which would re-resolve the host and
            # could drift off the validated IP).
            conn = http.client.HTTPSConnection(host, 443, timeout=timeout, context=context)
            conn.sock = tls_sock
            conn.request(
                "GET",
                path,
                headers={
                    "Host": host,
                    "Accept": "application/pdf,text/html,text/plain",
                    "User-Agent": "CSUB-Review-Research/1.0 (+guarded)",
                },
            )
            response = conn.getresponse()
            headers = {key.lower(): value for key, value in response.getheaders()}
            declared = headers.get("content-length")
            if declared is not None:
                try:
                    if int(declared) > max_bytes:
                        return RawResponse(
                            status=response.status,
                            headers=headers,
                            body=b"",
                            connected_ip=ip,
                            oversized=True,
                        )
                except ValueError:
                    pass
            body = response.read(max_bytes + 1)
            oversized = len(body) > max_bytes
            if oversized:
                body = body[:max_bytes]
            return RawResponse(
                status=response.status,
                headers=headers,
                body=body,
                connected_ip=ip,
                oversized=oversized,
            )
        except OSError as error:
            raise ResearchError("connect_error", f"could not fetch from {host}") from error
        finally:
            # Close everything exactly once. ``conn.close`` closes the injected
            # TLS socket (and its underlying raw socket); if the connection was
            # never built, close whichever socket was opened.
            if response is not None:
                response.close()
            if conn is not None:
                conn.close()
            elif tls_sock is not None:
                tls_sock.close()
            elif raw_sock is not None:
                raw_sock.close()


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


@dataclass(slots=True)
class _Budget:
    downloads_used: int = 0
    deadline_exceeded: bool = False
    started_at: float = field(default_factory=time.monotonic)


class VendorResearchService:
    """Fetch and validate official-domain evidence with deterministic controls."""

    def __init__(
        self,
        *,
        transport: HttpTransport,
        resolver: Resolver | None = None,
        policy: ResearchPolicy | None = None,
        clock: Callable[[], str] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._transport = transport
        self._resolver = resolver or SystemResolver()
        self._policy = policy or ResearchPolicy()
        self._clock = clock
        self._monotonic = monotonic
        self._counter = 0
        self._id_factory = id_factory or self._default_id

    def _default_id(self) -> str:
        self._counter += 1
        return f"prov-{self._counter:04d}"

    # -- public API -----------------------------------------------------------

    def research(
        self,
        *,
        official_url: str,
        targets: Sequence[str],
        vendor: str | None = None,
        product: str | None = None,
        source_locators: dict[str, str] | None = None,
    ) -> ResearchResult:
        """Fetch ``targets`` within the domain derived from ``official_url``.

        ``targets`` typically includes the trust-center URL and any candidate
        document URLs. Off-domain or invalid targets are quarantined or recorded
        as gaps; they never enter findings automatically.
        """

        locators = source_locators or {}
        try:
            allowlist = DomainAllowlist.derive(
                official_url, self._policy.standards_authorities
            )
        except DomainError as error:
            return ResearchResult(
                vendor=vendor,
                product=product,
                confirmed_host="",
                gaps=[ResearchGap(official_url, "invalid_official_url", str(error))],
            )

        result = ResearchResult(
            vendor=vendor, product=product, confirmed_host=allowlist.confirmed_host
        )
        budget = _Budget(started_at=self._monotonic())

        seen: set[str] = set()
        for target in targets:
            if not isinstance(target, str) or not target.strip():
                continue
            target = target.strip()
            if target in seen:
                continue
            seen.add(target)

            if budget.downloads_used >= self._policy.max_downloads:
                result.gaps.append(
                    ResearchGap(target, "download_limit", "download count limit reached")
                )
                continue
            if self._monotonic() - budget.started_at > self._policy.total_deadline_seconds:
                budget.deadline_exceeded = True
                result.gaps.append(
                    ResearchGap(target, "deadline_exceeded", "research time budget exhausted")
                )
                continue

            self._fetch_target(
                target, allowlist, vendor, product, locators.get(target), result, budget
            )

        result.downloads_used = budget.downloads_used
        result.deadline_exceeded = budget.deadline_exceeded
        return result

    # -- internals ------------------------------------------------------------

    def _fetch_target(
        self,
        target: str,
        allowlist: DomainAllowlist,
        vendor: str | None,
        product: str | None,
        source_locator: str | None,
        result: ResearchResult,
        budget: _Budget,
    ) -> None:
        try:
            provenance, body, host = self._fetch_with_redirects(
                target, allowlist, vendor, product, source_locator, budget
            )
        except ResearchBlocked as blocked:
            # Off-domain destinations (initial target or a redirect location) are
            # quarantined for human confirmation; all other blocks are gaps for
            # manual review. Neither becomes evidence.
            if blocked.code == "off_domain":
                result.quarantined.append(QuarantinedLink(blocked.url or target, blocked.detail))
            else:
                result.gaps.append(ResearchGap(target, blocked.code, blocked.detail))
            return
        except ResearchError as error:
            result.gaps.append(ResearchGap(target, error.code, error.detail))
            return

        untrusted = [f.to_dict() for f in scan_untrusted_text(self._decode(body))]
        result.findings.append(
            ResearchFinding(provenance=provenance, untrusted_findings=untrusted)
        )
        self._quarantine_offdomain_links(body, host, allowlist, result)

    def _fetch_with_redirects(
        self,
        url: str,
        allowlist: DomainAllowlist,
        vendor: str | None,
        product: str | None,
        source_locator: str | None,
        budget: _Budget,
    ) -> tuple[ProvenanceRecord, bytes, str]:
        chain: list[str] = []
        current = url
        for _hop in range(self._policy.max_redirects + 1):
            # Enforce the download-count and total-deadline budgets before any
            # network work in this hop (initial request and every redirect), and
            # clamp this request's timeout to the remaining budget.
            if budget.downloads_used >= self._policy.max_downloads:
                raise ResearchError("download_limit", "download count limit reached")
            remaining = self._policy.total_deadline_seconds - (
                self._monotonic() - budget.started_at
            )
            if remaining <= 0:
                budget.deadline_exceeded = True
                raise ResearchError("deadline_exceeded", "research time budget exhausted")
            timeout = min(self._policy.per_request_timeout_seconds, remaining)

            host = parse_destination(current, allowlist, self._policy)
            pinned_ip = self._resolve_and_pin(host)

            budget.downloads_used += 1
            response = self._transport.fetch(
                ip=pinned_ip,
                host=host,
                url=current,
                timeout=timeout,
                max_bytes=self._policy.max_response_bytes,
            )
            if response.connected_ip != pinned_ip:
                raise ResearchBlocked(
                    "connection_ip_mismatch",
                    "transport connected to an address the service did not validate",
                )
            if response.oversized:
                raise ResearchBlocked(
                    "response_too_large",
                    f"response exceeded {self._policy.max_response_bytes} bytes",
                )

            if response.status in _REDIRECT_STATUSES:
                chain.append(current)
                location = response.headers.get("location")
                if not location:
                    raise ResearchBlocked("redirect_no_location", "redirect without a Location")
                # Resolve relative redirects against the current URL, then
                # re-validate on the next loop. A same-host relative redirect is
                # allowed; a protocol-relative (``//other``) or absolute
                # off-domain redirect resolves to an off-allowlist host and is
                # quarantined by parse_destination.
                current = urljoin(current, location.strip())
                continue

            # 4xx/5xx (and any other non-2xx) bodies are never evidence.
            if not (200 <= response.status < 300):
                raise ResearchError("http_error", f"non-success status {response.status}")

            scope = allowlist.scope_of(host)
            if scope is None:  # defensive; parse_destination already enforced this
                raise ResearchBlocked("off_domain", f"host {host!r} left the allowlist")
            self._enforce_content_type(response)
            provenance = ProvenanceRecord(
                provenance_id=self._id_factory(),
                final_url=current,
                redirect_chain=tuple(chain),
                retrieved_at=self._clock(),
                content_sha256=hashlib.sha256(response.body).hexdigest(),
                mime_type=self._mime_type(response),
                byte_length=len(response.body),
                scope=scope,
                resolved_ip=pinned_ip,
                vendor=vendor,
                product=product,
                source_locator=source_locator,
            )
            return provenance, response.body, host

        raise ResearchBlocked(
            "too_many_redirects", f"exceeded {self._policy.max_redirects} redirects"
        )

    def _resolve_and_pin(self, host: str) -> str:
        answers = self._resolver.resolve(host)
        if not answers:
            raise ResearchError("dns_empty", f"no addresses for {host}")
        # Validate EVERY answer, then pin one. A single private/reserved answer
        # (DNS rebinding) rejects the whole destination.
        for answer in answers:
            assert_public_ip(answer)
        return answers[0]

    def _enforce_content_type(self, response: RawResponse) -> None:
        mime = self._mime_type(response)
        if mime not in self._policy.allowed_content_types:
            raise ResearchBlocked("unsupported_content_type", f"content-type {mime!r} not allowed")

    @staticmethod
    def _mime_type(response: RawResponse) -> str:
        raw = response.headers.get("content-type", "")
        return raw.split(";", 1)[0].strip().lower()

    @staticmethod
    def _decode(body: bytes) -> str:
        try:
            return body.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - decode never raises with replace
            return ""

    def _quarantine_offdomain_links(
        self,
        body: bytes,
        host: str,
        allowlist: DomainAllowlist,
        result: ResearchResult,
    ) -> None:
        text = self._decode(body)
        already = {q.url for q in result.quarantined}
        for match in _ABS_HTTPS_URL.finditer(text):
            link = match.group(0).rstrip(".,);]\"'")
            link_host = (urlsplit(link).hostname or "").lower().rstrip(".")
            if not link_host or allowlist.is_allowed(link_host):
                continue
            if link in already:
                continue
            already.add(link)
            result.quarantined.append(
                QuarantinedLink(link, f"off-domain link on {host}; requires human confirmation")
            )


@runtime_checkable
class VendorResearchProvider(Protocol):
    """Structural interface a review/submission path depends on for research.

    :class:`VendorResearchService` satisfies this. Injecting it (rather than
    importing the concrete service) keeps the vendor backend decoupled and lets
    the local slice run with no provider configured (research simply not
    performed) instead of fabricating findings.
    """

    def research(
        self,
        *,
        official_url: str,
        targets: Sequence[str],
        vendor: str | None = None,
        product: str | None = None,
        source_locators: dict[str, str] | None = None,
    ) -> ResearchResult:
        ...
