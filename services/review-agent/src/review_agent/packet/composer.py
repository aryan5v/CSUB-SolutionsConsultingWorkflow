"""Packet composition (FR-6).

Produces a concise low-risk recommendation when policy permits, or a full
editable medium-risk TAAP/security packet. Recommendation language comes only
from approved clause identifiers; the composer never invents policy text.
"""

from __future__ import annotations

from ..contracts.case import CaseIntake
from ..contracts.common import Citation
from ..contracts.packet import Packet, PacketSection, PacketType
from ..contracts.policy import PolicyResult, RiskRoute


def compose_packet(
    *,
    case_id: str,
    case: CaseIntake,
    policy: PolicyResult,
    specialist_results: dict,
    packet_version: int = 1,
) -> Packet:
    if policy.risk_route in (RiskRoute.APPROVED, RiskRoute.LOW):
        packet = _compose_low_risk(case_id, case, policy, packet_version)
    else:
        packet = _compose_medium_risk(case_id, case, policy, specialist_results, packet_version)
    packet.sha256 = packet.compute_sha256()
    return packet


def _policy_citations(policy: PolicyResult) -> list[Citation]:
    return list(policy.citations)


def _compose_low_risk(
    case_id: str, case: CaseIntake, policy: PolicyResult, version: int
) -> Packet:
    route_label = "already approved" if policy.risk_route is RiskRoute.APPROVED else "low risk"
    sections = [
        PacketSection(
            key="recommendation",
            title="Recommendation",
            body=(
                f"{case.product_name} ({case.vendor_name}) is assessed as {route_label} "
                f"under policy {policy.policy_version}. Recommended clauses: "
                f"{', '.join(policy.recommendation_clause_ids) or 'none'}."
            ),
            editable=True,
            citations=_policy_citations(policy),
        ),
    ]
    return Packet(
        packet_id=f"{case_id}-packet",
        case_id=case_id,
        packet_version=version,
        packet_type=PacketType.LOW_RISK,
        sections=sections,
        recommendation_clause_ids=list(policy.recommendation_clause_ids),
        citations=_policy_citations(policy),
    )


def _compose_medium_risk(
    case_id: str,
    case: CaseIntake,
    policy: PolicyResult,
    specialist_results: dict,
    version: int,
) -> Packet:
    security = specialist_results.get("security") or {}
    accessibility = specialist_results.get("accessibility") or {}

    sections = [
        PacketSection(
            key="taap_summary",
            title="TAAP summary",
            body=(
                f"Product: {case.product_name}\nVendor: {case.vendor_name}\n"
                f"Use case: {case.use_case}\nExpected users: {case.expected_users}\n"
                f"Data classification: {case.data_classification.value}\n"
                f"Estimated cost (USD): {case.estimated_cost_usd}\n"
                f"Risk route: {policy.risk_route.value} (policy {policy.policy_version})"
            ),
            editable=True,
            citations=_policy_citations(policy),
        ),
        PacketSection(
            key="security_summary",
            title="Security summary",
            body=security.get("summary", "Pending specialist analysis."),
            editable=True,
        ),
        PacketSection(
            key="accessibility_findings",
            title="Accessibility findings",
            body=accessibility.get("summary", "Pending specialist analysis."),
            editable=True,
        ),
        PacketSection(
            key="evidence_inventory",
            title="Required evidence and gaps",
            body="Required: " + (", ".join(policy.required_evidence) or "none"),
            editable=True,
        ),
        PacketSection(
            key="mitigations",
            title="Mitigations and owners",
            body="[owner placeholder] Document mitigations for each open gap before approval.",
            editable=True,
        ),
        PacketSection(
            key="recommendation_clauses",
            title="Approved recommendation clauses",
            body="\n".join(f"- {cid}" for cid in policy.recommendation_clause_ids) or "None.",
            editable=True,
            citations=_policy_citations(policy),
        ),
        PacketSection(
            key="committee_routing",
            title="Committee routing",
            body="Route to the appropriate review committee per the risk tier before sign-off.",
            editable=True,
        ),
    ]

    all_citations = list(policy.citations)
    return Packet(
        packet_id=f"{case_id}-packet",
        case_id=case_id,
        packet_version=version,
        packet_type=PacketType.MEDIUM_RISK,
        sections=sections,
        recommendation_clause_ids=list(policy.recommendation_clause_ids),
        unsupported_claims=[],
        citations=all_citations,
    )
