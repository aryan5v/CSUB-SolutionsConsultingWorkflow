"""Provenance records for captured official-domain evidence (issue #44).

Every accepted public-evidence claim must resolve to a captured official source.
A :class:`ProvenanceRecord` stores, for one retrieval: the final URL, the full
redirect chain, the retrieval time, the content hash, the MIME type, the
vendor/product scope, and a source locator. :func:`provenance_to_citation`
projects a record into the citation shape the existing citation checker
(:mod:`review_agent.specialists.citations`) validates, so a research finding is
rejected by the same trust boundary as any other claim if its scope or
vendor/product does not match the case.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    provenance_id: str
    final_url: str
    redirect_chain: tuple[str, ...]
    retrieved_at: str
    content_sha256: str
    mime_type: str
    byte_length: int
    scope: str  # "official_vendor" | "standards"
    resolved_ip: str
    vendor: str | None = None
    product: str | None = None
    source_locator: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def provenance_to_citation(provenance: ProvenanceRecord, claim: str) -> dict:
    """Project a provenance record into a citation-checker-compatible claim.

    The returned ``source`` carries the provenance id plus the vendor/product so
    a cross-vendor or cross-product research finding is rejected by
    ``check_citations`` exactly like any other claim.
    """

    return {
        "claim": claim,
        "citations": [
            {
                "scope": provenance.scope,
                "source": {
                    "source_id": provenance.provenance_id,
                    "filename": provenance.final_url,
                    "sha256": provenance.content_sha256,
                    "vendor": provenance.vendor,
                    "product": provenance.product,
                    "version": provenance.retrieved_at,
                },
            }
        ],
    }


@dataclass(slots=True)
class ResearchFinding:
    """An accepted, provenance-backed source with any untrusted-content flags."""

    provenance: ProvenanceRecord
    untrusted_findings: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "provenance": self.provenance.to_dict(),
            "untrusted_findings": list(self.untrusted_findings),
        }


@dataclass(slots=True)
class ResearchGap:
    """A destination that could not become evidence; surfaces for manual review."""

    requested_url: str
    code: str
    detail: str

    def to_dict(self) -> dict:
        return {"requested_url": self.requested_url, "code": self.code, "detail": self.detail}


@dataclass(slots=True)
class QuarantinedLink:
    """An off-domain link held for human confirmation; never auto-promoted."""

    url: str
    reason: str

    def to_dict(self) -> dict:
        return {"url": self.url, "reason": self.reason}


@dataclass(slots=True)
class ResearchResult:
    vendor: str | None
    product: str | None
    vendor_domain: str
    findings: list[ResearchFinding] = field(default_factory=list)
    gaps: list[ResearchGap] = field(default_factory=list)
    quarantined: list[QuarantinedLink] = field(default_factory=list)
    downloads_used: int = 0
    deadline_exceeded: bool = False

    def to_dict(self) -> dict:
        return {
            "vendor": self.vendor,
            "product": self.product,
            "vendor_domain": self.vendor_domain,
            "findings": [f.to_dict() for f in self.findings],
            "gaps": [g.to_dict() for g in self.gaps],
            "quarantined": [q.to_dict() for q in self.quarantined],
            "downloads_used": self.downloads_used,
            "deadline_exceeded": self.deadline_exceeded,
        }
