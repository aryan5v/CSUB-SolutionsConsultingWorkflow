"""Adversarial SSRF / DNS / redirect tests for official-domain research (#44).

All hosts and IPs are synthetic. No real network I/O occurs: a fake resolver and
fake transport stand in for DNS and HTTPS so every safety control is exercised
deterministically.
"""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from review_agent.research import (
    DomainAllowlist,
    RawResponse,
    ResearchBlocked,
    ResearchPolicy,
    VendorResearchService,
    assert_public_ip,
    is_ip_literal_like,
    parse_destination,
)

PUBLIC_IP = "93.184.216.34"


class FakeResolver:
    def __init__(self, mapping: dict[str, list[str]], default: list[str] | None = None) -> None:
        self._mapping = mapping
        self._default = default if default is not None else [PUBLIC_IP]

    def resolve(self, host: str) -> list[str]:
        return self._mapping.get(host, list(self._default))


class FakeTransport:
    def __init__(self, mapping: dict[str, dict], *, connected_ip: str | None = None) -> None:
        self._mapping = mapping
        self._connected_ip = connected_ip
        self.calls: list[tuple[str, str, str]] = []

    def fetch(self, *, ip: str, host: str, url: str, timeout: float, max_bytes: int) -> RawResponse:
        self.calls.append((ip, host, url))
        spec = self._mapping[url]
        return RawResponse(
            status=spec.get("status", 200),
            headers=spec.get("headers", {"content-type": "application/pdf"}),
            body=spec.get("body", b"%PDF-1.4 evidence"),
            connected_ip=self._connected_ip or ip,
            oversized=spec.get("oversized", False),
        )


def _service(
    transport: FakeTransport, resolver: FakeResolver, **policy_kw
) -> VendorResearchService:
    return VendorResearchService(
        transport=transport,
        resolver=resolver,
        policy=ResearchPolicy(**policy_kw),
        clock=lambda: "2026-07-15T00:00:00+00:00",
        monotonic=lambda: 0.0,
    )


class IpLiteralTests(unittest.TestCase):
    def test_alternate_numeric_ip_forms_are_detected(self) -> None:
        for host in (
            "127.0.0.1",
            "2130706433",  # decimal
            "0x7f000001",  # hex
            "017700000001",  # octal
            "127.1",  # short dotted
            "::1",  # ipv6 loopback
            "169.254.169.254",  # metadata
        ):
            self.assertTrue(is_ip_literal_like(host), host)

    def test_normal_hostnames_are_not_ip_literals(self) -> None:
        for host in ("vendor.com", "trust.vendor.com", "vendor.co.uk"):
            self.assertFalse(is_ip_literal_like(host), host)


class PublicIpTests(unittest.TestCase):
    def test_private_and_reserved_addresses_are_blocked(self) -> None:
        for ip in (
            "127.0.0.1",  # loopback
            "10.0.0.5",  # private
            "192.168.1.10",  # private
            "172.16.0.1",  # private
            "169.254.169.254",  # link-local metadata
            "100.64.0.1",  # CGNAT (not global)
            "0.0.0.0",  # unspecified
            "224.0.0.1",  # multicast
            "::1",  # ipv6 loopback
            "fd00::1",  # ipv6 unique-local
            "::ffff:127.0.0.1",  # ipv4-mapped loopback
        ):
            with self.assertRaises(ResearchBlocked, msg=ip):
                assert_public_ip(ip)

    def test_public_address_is_accepted(self) -> None:
        self.assertIsNotNone(assert_public_ip(PUBLIC_IP))


class DestinationParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.allowlist = DomainAllowlist(vendor_domain="vendor.com")
        self.policy = ResearchPolicy()

    def _block_code(self, url: str) -> str:
        with self.assertRaises(ResearchBlocked) as ctx:
            parse_destination(url, self.allowlist, self.policy)
        return ctx.exception.code

    def test_http_scheme_rejected(self) -> None:
        self.assertEqual(self._block_code("http://vendor.com/x"), "scheme_not_https")

    def test_credentialed_url_rejected(self) -> None:
        self.assertEqual(self._block_code("https://user:pass@vendor.com/x"), "credentialed_url")

    def test_userinfo_lookalike_host_rejected(self) -> None:
        # urlsplit treats vendor.com as userinfo and evil.example as the host.
        self.assertEqual(self._block_code("https://vendor.com@evil.example/x"), "credentialed_url")

    def test_unsafe_port_rejected(self) -> None:
        self.assertEqual(self._block_code("https://vendor.com:8080/x"), "port_not_allowed")

    def test_ip_literal_host_rejected(self) -> None:
        self.assertEqual(self._block_code("https://2130706433/x"), "ip_literal_host")

    def test_off_domain_host_rejected(self) -> None:
        self.assertEqual(self._block_code("https://evil.example/x"), "off_domain")

    def test_lookalike_suffix_host_rejected(self) -> None:
        self.assertEqual(self._block_code("https://vendor.com.evil.example/x"), "off_domain")

    def test_subdomain_allowed(self) -> None:
        self.assertEqual(
            parse_destination("https://trust.vendor.com/x", self.allowlist, self.policy),
            "trust.vendor.com",
        )


class ResearchDestinationTests(unittest.TestCase):
    def test_private_ip_target_is_a_gap_not_a_finding(self) -> None:
        resolver = FakeResolver({"trust.vendor.com": ["10.0.0.5"]})
        transport = FakeTransport({})
        result = _service(transport, resolver).research(
            official_url="https://vendor.com",
            targets=["https://trust.vendor.com/vpat"],
        )
        self.assertEqual(result.findings, [])
        self.assertEqual(len(result.gaps), 1)
        self.assertEqual(result.gaps[0].code, "private_ip")
        self.assertEqual(transport.calls, [])  # never connected

    def test_metadata_endpoint_target_is_blocked(self) -> None:
        resolver = FakeResolver({"trust.vendor.com": ["169.254.169.254"]})
        result = _service(FakeTransport({}), resolver).research(
            official_url="https://vendor.com",
            targets=["https://trust.vendor.com/whoami"],
        )
        self.assertEqual(result.gaps[0].code, "link_local_ip")

    def test_dns_rebinding_one_private_answer_rejects_destination(self) -> None:
        resolver = FakeResolver({"trust.vendor.com": [PUBLIC_IP, "10.0.0.5"]})
        result = _service(FakeTransport({}), resolver).research(
            official_url="https://vendor.com",
            targets=["https://trust.vendor.com/vpat"],
        )
        self.assertEqual(result.findings, [])
        self.assertEqual(result.gaps[0].code, "private_ip")

    def test_connection_ip_mismatch_is_blocked(self) -> None:
        # Transport connects to a different IP than the service validated/pinned
        # (resolution drift / a misbehaving provider).
        resolver = FakeResolver({"trust.vendor.com": [PUBLIC_IP]})
        transport = FakeTransport(
            {"https://trust.vendor.com/vpat": {"status": 200}},
            connected_ip="10.0.0.9",
        )
        result = _service(transport, resolver).research(
            official_url="https://vendor.com",
            targets=["https://trust.vendor.com/vpat"],
        )
        self.assertEqual(result.gaps[0].code, "connection_ip_mismatch")

    def test_off_domain_target_is_quarantined(self) -> None:
        resolver = FakeResolver({})
        result = _service(FakeTransport({}), resolver).research(
            official_url="https://vendor.com",
            targets=["https://evil.example/doc"],
        )
        self.assertEqual(result.findings, [])
        self.assertEqual(len(result.quarantined), 1)
        self.assertEqual(result.quarantined[0].url, "https://evil.example/doc")

    def test_redirect_to_off_domain_host_is_quarantined(self) -> None:
        resolver = FakeResolver({"trust.vendor.com": [PUBLIC_IP]})
        transport = FakeTransport(
            {
                "https://trust.vendor.com/vpat": {
                    "status": 302,
                    "headers": {"location": "https://evil.example/steal"},
                }
            }
        )
        result = _service(transport, resolver).research(
            official_url="https://vendor.com",
            targets=["https://trust.vendor.com/vpat"],
        )
        self.assertEqual(result.findings, [])
        self.assertEqual(len(result.quarantined), 1)
        self.assertIn("evil.example", result.quarantined[0].url)

    def test_redirect_to_private_ip_host_form_is_blocked(self) -> None:
        resolver = FakeResolver({"trust.vendor.com": [PUBLIC_IP]})
        transport = FakeTransport(
            {
                "https://trust.vendor.com/vpat": {
                    "status": 302,
                    "headers": {"location": "https://2130706433/meta"},
                }
            }
        )
        result = _service(transport, resolver).research(
            official_url="https://vendor.com",
            targets=["https://trust.vendor.com/vpat"],
        )
        # Numeric host is not a DNS name -> blocked redirect escape (a gap).
        self.assertEqual(result.findings, [])
        self.assertEqual(result.gaps[0].code, "ip_literal_host")

    def test_same_domain_redirect_is_followed_and_chained(self) -> None:
        resolver = FakeResolver(
            {"trust.vendor.com": [PUBLIC_IP], "docs.vendor.com": [PUBLIC_IP]}
        )
        transport = FakeTransport(
            {
                "https://trust.vendor.com/vpat": {
                    "status": 301,
                    "headers": {"location": "https://docs.vendor.com/vpat.pdf"},
                },
                "https://docs.vendor.com/vpat.pdf": {
                    "status": 200,
                    "headers": {"content-type": "application/pdf"},
                },
            }
        )
        result = _service(transport, resolver).research(
            official_url="https://vendor.com",
            targets=["https://trust.vendor.com/vpat"],
        )
        self.assertEqual(len(result.findings), 1)
        prov = result.findings[0].provenance
        self.assertEqual(prov.final_url, "https://docs.vendor.com/vpat.pdf")
        self.assertEqual(prov.redirect_chain, ("https://trust.vendor.com/vpat",))

    def test_redirect_loop_exceeds_limit(self) -> None:
        resolver = FakeResolver({"a.vendor.com": [PUBLIC_IP], "b.vendor.com": [PUBLIC_IP]})
        transport = FakeTransport(
            {
                "https://a.vendor.com/": {
                    "status": 302,
                    "headers": {"location": "https://b.vendor.com/"},
                },
                "https://b.vendor.com/": {
                    "status": 302,
                    "headers": {"location": "https://a.vendor.com/"},
                },
            }
        )
        result = _service(transport, resolver, max_redirects=2).research(
            official_url="https://vendor.com",
            targets=["https://a.vendor.com/"],
        )
        self.assertEqual(result.gaps[0].code, "too_many_redirects")

    def test_oversized_response_is_blocked(self) -> None:
        resolver = FakeResolver({"trust.vendor.com": [PUBLIC_IP]})
        transport = FakeTransport(
            {"https://trust.vendor.com/big": {"status": 200, "oversized": True}}
        )
        result = _service(transport, resolver).research(
            official_url="https://vendor.com",
            targets=["https://trust.vendor.com/big"],
        )
        self.assertEqual(result.gaps[0].code, "response_too_large")

    def test_unsupported_content_type_is_blocked(self) -> None:
        resolver = FakeResolver({"trust.vendor.com": [PUBLIC_IP]})
        transport = FakeTransport(
            {
                "https://trust.vendor.com/app": {
                    "status": 200,
                    "headers": {"content-type": "application/octet-stream"},
                }
            }
        )
        result = _service(transport, resolver).research(
            official_url="https://vendor.com",
            targets=["https://trust.vendor.com/app"],
        )
        self.assertEqual(result.gaps[0].code, "unsupported_content_type")

    def test_download_count_limit_enforced(self) -> None:
        resolver = FakeResolver({"trust.vendor.com": [PUBLIC_IP]})
        transport = FakeTransport(
            {
                "https://trust.vendor.com/a": {"status": 200},
                "https://trust.vendor.com/b": {"status": 200},
            }
        )
        result = _service(transport, resolver, max_downloads=1).research(
            official_url="https://vendor.com",
            targets=["https://trust.vendor.com/a", "https://trust.vendor.com/b"],
        )
        self.assertEqual(len(result.findings), 1)
        self.assertEqual([g.code for g in result.gaps], ["download_limit"])

    def test_time_budget_exhaustion_is_a_gap(self) -> None:
        resolver = FakeResolver({"trust.vendor.com": [PUBLIC_IP]})
        transport = FakeTransport({"https://trust.vendor.com/a": {"status": 200}})
        ticks = iter([0.0, 100.0, 200.0])
        service = VendorResearchService(
            transport=transport,
            resolver=resolver,
            policy=ResearchPolicy(total_deadline_seconds=1.0),
            clock=lambda: "2026-07-15T00:00:00+00:00",
            monotonic=lambda: next(ticks),
        )
        result = service.research(
            official_url="https://vendor.com",
            targets=["https://trust.vendor.com/a"],
        )
        self.assertTrue(result.deadline_exceeded)
        self.assertEqual(result.gaps[0].code, "deadline_exceeded")


if __name__ == "__main__":
    unittest.main()
