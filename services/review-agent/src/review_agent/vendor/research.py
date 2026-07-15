"""Official-vendor research agent (PLAN: official-vendor research node).

Deployed when the invite is sent: gathers best-effort, publicly documented facts
about the vendor's security/compliance posture while the vendor prepares their
upload. Strictly advisory (AGENTS.md trust boundary): it summarizes and cites
from the official-vendor scope only, discloses uncertainty, and never asserts
compliance as fact, sets a risk tier, or approves anything. A human confirms
before any of it informs a decision.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..adapters.model import ModelClient
from ..contracts.common import Citation, CitationScope, SourceCoordinates
from ..contracts.vendor import VendorResearchResult

_SYSTEM = (
    "You are an official-vendor research assistant. Using only publicly "
    "documented information from the vendor's own official domain, summarize the "
    "vendor's stated security and compliance posture (certifications, data "
    "handling, subprocessors). Summarize and cite only. Do NOT assert that the "
    "vendor is compliant, do NOT set risk tiers, and do NOT recommend approval. "
    "Always disclose what you could not verify in 'uncertainty'."
)


@runtime_checkable
class VendorResearchClient(Protocol):
    def research(
        self, *, vendor: str, product: str, official_domain: str | None
    ) -> VendorResearchResult: ...


class DeterministicVendorResearch:
    """Local fake: obviously-synthetic, ungrounded result (no network)."""

    def research(
        self, *, vendor: str, product: str, official_domain: str | None
    ) -> VendorResearchResult:
        return VendorResearchResult(
            vendor=vendor,
            product=product,
            official_domain=official_domain,
            summary=f"[deterministic-fake] no live research performed for {vendor}",
            findings=[],
            citations=[],
            uncertainty="local deterministic research; nothing grounded or verified",
        )


class ModelVendorResearch:
    """Model-backed research via the ModelClient seam (Bedrock in AWS mode).

    Findings are cited to the official-vendor scope with ``verified=False`` — the
    research is a lead for a human to confirm, not evidence of compliance.
    """

    def __init__(self, model: ModelClient) -> None:
        self._model = model

    def research(
        self, *, vendor: str, product: str, official_domain: str | None
    ) -> VendorResearchResult:
        raw = self._model.complete_json(
            system=_SYSTEM,
            prompt=(
                f"Summarize the publicly documented security/compliance posture of "
                f"{vendor}'s {product}. List concrete facts as short strings in "
                f"'findings' and disclose gaps in 'uncertainty'."
            ),
            context={
                "task": "vendor_research",
                "vendor": vendor,
                "product": product,
                "official_domain": official_domain,
            },
        )
        findings = [str(f) for f in raw.get("findings", []) if str(f).strip()]
        source = SourceCoordinates(
            source_id=official_domain or f"vendor:{vendor}",
            filename=official_domain,
        )
        citations = [
            Citation(
                claim=finding,
                source=source,
                scope=CitationScope.OFFICIAL_VENDOR,
                verified=False,
            ).to_dict()
            for finding in findings
        ]
        return VendorResearchResult(
            vendor=vendor,
            product=product,
            official_domain=official_domain,
            summary=str(raw.get("summary", "")),
            findings=findings,
            citations=citations,
            uncertainty=str(
                raw.get("uncertainty", "not independently verified; human confirmation required")
            ),
        )
