"""Official-domain vendor research with SSRF, DNS/IP, redirect, and provenance
controls (issue #44).

Public evidence research may fetch only HTTPS destinations on the vendor's
confirmed host and its subdomains (plus configured standards authorities),
validating every DNS answer and redirect hop, enforcing size/content-type/count/
time limits, capturing full provenance for every claim, treating retrieved
content as untrusted, and quarantining off-domain links for human confirmation.
Provider calls sit behind small interfaces (:class:`Resolver`,
:class:`HttpTransport`) with local fakes; deterministic limits live in
:class:`ResearchPolicy`, outside any model prompt.
"""

from __future__ import annotations

from .domain import (
    DomainAllowlist,
    DomainError,
    confirmed_host_from_url,
    is_ip_literal_like,
    validate_public_dns_host,
)
from .factory import build_research_provider
from .policy import ResearchPolicy
from .provenance import (
    ProvenanceRecord,
    QuarantinedLink,
    ResearchFinding,
    ResearchGap,
    ResearchResult,
    provenance_to_citation,
)
from .service import (
    GuardedHttpTransport,
    HttpTransport,
    RawResponse,
    ResearchError,
    Resolver,
    SystemResolver,
    VendorResearchProvider,
    VendorResearchService,
)
from .ssrf import ResearchBlocked, assert_public_ip, parse_destination

__all__ = [
    "DomainAllowlist",
    "DomainError",
    "GuardedHttpTransport",
    "HttpTransport",
    "ProvenanceRecord",
    "QuarantinedLink",
    "RawResponse",
    "ResearchBlocked",
    "ResearchError",
    "ResearchFinding",
    "ResearchGap",
    "ResearchPolicy",
    "ResearchResult",
    "Resolver",
    "SystemResolver",
    "VendorResearchProvider",
    "VendorResearchService",
    "assert_public_ip",
    "build_research_provider",
    "confirmed_host_from_url",
    "is_ip_literal_like",
    "parse_destination",
    "provenance_to_citation",
    "validate_public_dns_host",
]
