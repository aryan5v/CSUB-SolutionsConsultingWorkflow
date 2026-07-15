"""Vendor evidence-portal contracts (PLAN: case-scoped vendor upload link,
official-vendor research, evidence specialist).

These model the flow after intake: the app mints a case-scoped upload link,
notifies the vendor and the committee, a research agent gathers best-effort
public facts, the vendor drops compliance evidence into a bucket, and the app
computes the gap between what the vendor provided and what CSUB's deterministic
policy requires. New, additive contracts — the Tuesday-locked contracts are
untouched. The gap determination is deterministic and human-confirmed; research
is advisory and cited, never authoritative.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True, slots=True)
class VendorInvite:
    """A case-scoped invitation for a vendor to submit compliance evidence."""

    case_id: str
    vendor: str
    product: str
    token: str
    upload_prefix: str
    vendor_recipient: str
    committee_recipients: list[str]
    created_at: str
    expires_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VendorPortalLink:
    """The link handed to the vendor; ``url`` opens the token-scoped portal."""

    url: str
    token: str
    upload_prefix: str
    expires_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NotificationReceipt:
    """Record of a notification. Simulated and labeled until a real channel
    (SES/SNS) is approved — mirrors the ServiceNow write-back discipline."""

    audience: str  # "vendor" | "committee"
    channel: str  # "email" (simulated)
    recipient: str
    subject: str
    reference: str  # invite token
    sent: bool = True
    simulated: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VendorResearchResult:
    """Best-effort, advisory research about a vendor's public posture.

    Never authoritative: findings are cited to the official-vendor scope with
    ``verified=False`` and uncertainty is always disclosed. A human confirms
    before any of this informs a decision.
    """

    vendor: str
    product: str
    official_domain: str | None
    summary: str
    findings: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    uncertainty: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceGap:
    """One required evidence type and whether the vendor's uploads satisfy it."""

    evidence_type: str
    satisfied: bool
    provided_evidence_ids: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceGapReport:
    """Deterministic gap between required evidence and vendor-provided evidence.

    ``required`` comes from the deterministic policy engine, not a model. The
    report is advisory input to a human review; ``requires_human_confirmation``
    stays ``True`` — the tool never clears a case.
    """

    case_id: str
    risk_route: str
    policy_version: str
    required: list[str]
    satisfied: list[str]
    missing: list[str]
    gaps: list[EvidenceGap]
    generated_at: str
    requires_human_confirmation: bool = True

    def to_dict(self) -> dict:
        data = asdict(self)
        data["gaps"] = [g.to_dict() for g in self.gaps]
        return data
