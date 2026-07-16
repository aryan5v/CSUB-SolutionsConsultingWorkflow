"""Accessibility specialist node (FR-5).

Runs in parallel with the security specialist. Produces a structured result
grounded in policy citations. It may summarize VPAT/ACR gaps but must not change
the risk route.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..adapters.model import ModelClient, RetryPolicy, invoke_structured, model_label
from ..contracts.case import CaseIntake
from ..contracts.common import Citation, CitationScope, SourceCoordinates
from ..contracts.policy import PolicyResult
from ..observability.metrics import MetricsEmitter

SPECIALIST_NAME = "accessibility"
SPECIALIST_VERSION = "accessibility@1"


def run_accessibility(
    case: CaseIntake,
    policy: PolicyResult,
    model: ModelClient,
    *,
    profile_version_id: str | None = None,
    retry_policy: RetryPolicy | None = None,
    metrics: MetricsEmitter | None = None,
    metric_dimensions: Mapping[str, str] | None = None,
) -> dict:
    raw = invoke_structured(
        model,
        system="You are an accessibility (ATI/Section 508/VPAT) review specialist. "
        "Summarize and compare only; do not set risk tiers.",
        prompt=f"Summarize accessibility review needs for {case.product_name}.",
        context={"task": "accessibility_analysis", "product": case.product_name},
        retry_policy=retry_policy,
        metrics=metrics,
        metric_dimensions=metric_dimensions,
    )
    needs_vpat = "vpat_acr" in policy.required_evidence or case.classroom_or_public_use
    citations = []
    if needs_vpat:
        citations.append(
            Citation(
                claim="VPAT/ACR accessibility conformance evidence required",
                source=SourceCoordinates(source_id="src:decision-tree", filename="accessibility"),
                scope=CitationScope.POLICY,
                verified=True,
            )
        )
    return {
        "specialist": SPECIALIST_NAME,
        "summary": raw.get("summary", ""),
        "vpat_required": needs_vpat,
        "findings": raw.get("findings", []),
        "citations": [c.to_dict() for c in citations],
        "uncertainty": raw.get("uncertainty", ""),
        "metadata": {
            "specialist_version": SPECIALIST_VERSION,
            "model": model_label(model),
            "simulated": raw.get("_model", {}).get("simulated", True),
            "repair_passes": raw.get("_model", {}).get("repair_passes", 0),
            "profile_version_id": profile_version_id,
        },
    }
