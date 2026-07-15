"""Citation and conflict checker (FR-5).

Rejects unsupported or cross-vendor claims and permits at most one repair pass.
A claim is supported only if it carries a citation whose source resolves within
an allowed retrieval scope, and case/vendor evidence must not cross the case's
vendor or product boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CitationCheck:
    ok: bool
    rejected: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


# Scopes whose sources must belong to the case's vendor/product to be valid.
_VENDOR_SCOPED = frozenset({"case_evidence", "official_vendor"})


def check_citations(
    claims: list[dict],
    *,
    case_vendor: str | None,
    case_product: str | None,
) -> CitationCheck:
    """Validate a list of ``{"claim", "citations": [...]}`` items.

    Each claim must have at least one citation with a ``source.source_id``.
    Vendor-scoped citations must match the case vendor/product.
    """
    rejected: list[dict] = []
    reasons: list[str] = []
    vendor_norm = (case_vendor or "").strip().lower()
    product_norm = (case_product or "").strip().lower()

    for item in claims:
        citations = item.get("citations", [])
        if not citations:
            rejected.append(item)
            reasons.append(f"unsupported claim (no citation): {item.get('claim', '')[:80]}")
            continue
        for citation in citations:
            source = citation.get("source", {})
            if source is None or not isinstance(source, dict) or not source.get("source_id"):
                rejected.append(item)
                reasons.append("citation missing source_id")
                break
            scope = citation.get("scope")
            if scope in _VENDOR_SCOPED:
                cited_vendor = str(source.get("vendor", "")).strip().lower()
                cited_product = str(source.get("product", "")).strip().lower()
                if cited_vendor and vendor_norm and cited_vendor != vendor_norm:
                    rejected.append(item)
                    reasons.append(
                        f"cross-vendor evidence rejected: {cited_vendor} != {vendor_norm}"
                    )
                    break
                if cited_product and product_norm and cited_product != product_norm:
                    rejected.append(item)
                    reasons.append(
                        f"cross-product evidence rejected: {cited_product} != {product_norm}"
                    )
                    break

    return CitationCheck(ok=not rejected, rejected=rejected, reasons=reasons)
