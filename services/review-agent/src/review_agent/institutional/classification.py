"""Classify each supplied Box source into an institutional review category.

This is a development-time slice. It decides three things for every source,
using only its location and filename (never its downloadable bytes):

1. Which review category the source belongs to.
2. Whether it is institutional policy, case/vendor evidence, or excluded.
   Institutional policy and case/vendor evidence stay in separate retrieval
   scopes and must not be mixed (AGENTS.md, PRD sec 5).
3. Whether it may be activated into the working policy set. Draft or
   unconfirmed sources and evidence examples are never activatable; only a
   human/administrator can confirm and activate a source.

The filenames matched here are already enumerated in ``docs/PRD.md`` under
"Known prototype source inventory", so this rule table carries no institutional
content, no hashes, and no secrets. Sources that do not match a known rule are
left ``UNRESOLVED`` and flagged for human classification rather than being
guessed at.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

from ..contracts.common import CitationScope
from ..contracts.policy import SourcePrecedence


class SourceCategory(str, Enum):
    APPROVED_SOFTWARE_CATALOG = "approved_software_catalog"
    RISK_REVIEW_RECOMMENDATIONS = "risk_review_recommendations"
    RISK_REVIEW_PROCESS = "risk_review_process"
    ACQUISITION_PROCESS = "acquisition_process"
    DECISION_TREE = "decision_tree"
    TAAP_TEMPLATE = "taap_template"
    APPROVAL_TEMPLATE = "approval_template"
    SECURITY_REVIEW_TEMPLATE = "security_review_template"
    DATA_CLASSIFICATION_GUIDANCE = "data_classification_guidance"
    PROCESS_NARRATIVE = "process_narrative"
    SIGNED_TAAP_EXAMPLE = "signed_taap_example"
    VENDOR_EVIDENCE_EXAMPLE = "vendor_evidence_example"
    UNCLASSIFIED = "unclassified"


class CorpusMembership(str, Enum):
    """Which corpus a source belongs to. Policy and evidence never mix."""

    INSTITUTIONAL_POLICY = "institutional_policy"
    CASE_VENDOR_EVIDENCE = "case_vendor_evidence"
    EXCLUDED = "excluded"
    UNRESOLVED = "unresolved"


class ConfirmationStatus(str, Enum):
    CONFIRMED = "confirmed"
    DRAFT_UNCONFIRMED = "draft_unconfirmed"
    EXAMPLE = "example"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True, slots=True)
class Classification:
    category: SourceCategory
    membership: CorpusMembership
    status: ConfirmationStatus
    activation_allowed: bool
    reason: str
    retrieval_scope: CitationScope | None = None
    precedence: SourcePrecedence | None = None
    notes: tuple[str, ...] = ()

    @property
    def is_institutional_policy(self) -> bool:
        return self.membership is CorpusMembership.INSTITUTIONAL_POLICY

    def to_dict(self) -> dict:
        out = asdict(self)
        out["category"] = self.category.value
        out["membership"] = self.membership.value
        out["status"] = self.status.value
        out["retrieval_scope"] = self.retrieval_scope.value if self.retrieval_scope else None
        out["precedence"] = int(self.precedence) if self.precedence is not None else None
        out["notes"] = list(self.notes)
        return out


@dataclass(frozen=True, slots=True)
class _Rule:
    category: SourceCategory
    status: ConfirmationStatus
    membership: CorpusMembership = CorpusMembership.INSTITUTIONAL_POLICY
    activation_allowed: bool = True
    retrieval_scope: CitationScope | None = CitationScope.POLICY
    precedence: SourcePrecedence | None = None
    reason: str = ""


# Confirmed institutional policy sources, keyed by lowercased filename. These
# filenames are the public inventory from docs/PRD.md, not institutional
# content. Templates and reference data carry no rule precedence; formal
# processes and data-classification guidance do.
_KNOWN: dict[str, _Rule] = {
    "snow export_approved_software_database.xlsx": _Rule(
        SourceCategory.APPROVED_SOFTWARE_CATALOG,
        ConfirmationStatus.CONFIRMED,
        reason="Approved-software export; institutional reference data (FR-2). "
        "Catalog membership is not blanket approval.",
    ),
    "risk review recommendations.xlsx": _Rule(
        SourceCategory.RISK_REVIEW_RECOMMENDATIONS,
        ConfirmationStatus.CONFIRMED,
        reason="Risk-review recommendation clauses (FR-3).",
    ),
    "risk review process.pdf": _Rule(
        SourceCategory.RISK_REVIEW_PROCESS,
        ConfirmationStatus.CONFIRMED,
        precedence=SourcePrecedence.FORMAL_POLICY,
        reason="Formal risk-review process flowchart (FR-3 precedence 2).",
    ),
    "solution acquisition process.pdf": _Rule(
        SourceCategory.ACQUISITION_PROCESS,
        ConfirmationStatus.CONFIRMED,
        precedence=SourcePrecedence.FORMAL_POLICY,
        reason="Formal solution-acquisition process flowchart (FR-3 precedence 2).",
    ),
    "csub taap.docx": _Rule(
        SourceCategory.TAAP_TEMPLATE,
        ConfirmationStatus.CONFIRMED,
        reason="Blank TAAP template for packet drafting (FR-6).",
    ),
    "solutions consulting  approval template.docx": _Rule(
        SourceCategory.APPROVAL_TEMPLATE,
        ConfirmationStatus.CONFIRMED,
        reason="Blank approval template.",
    ),
    "vendor information security risk review template.docx": _Rule(
        SourceCategory.SECURITY_REVIEW_TEMPLATE,
        ConfirmationStatus.CONFIRMED,
        reason="Blank security-review template.",
    ),
    "csu information security policy and standards data clasification.docx": _Rule(
        SourceCategory.DATA_CLASSIFICATION_GUIDANCE,
        ConfirmationStatus.CONFIRMED,
        precedence=SourcePrecedence.FORMAL_POLICY,
        reason="Data-classification guidance (FR-3 precedence 2).",
    ),
    "solutions consulting.docx": _Rule(
        SourceCategory.PROCESS_NARRATIVE,
        ConfirmationStatus.CONFIRMED,
        reason="Solutions Consulting process narrative.",
    ),
}


def _parts(relative_path: str) -> list[str]:
    return [p for p in relative_path.replace("\\", "/").split("/") if p]


def classify(relative_path: str) -> Classification:
    """Classify one source by its corpus-relative path.

    ``relative_path`` is a display path such as
    ``"Solutions Consulting/Risk Review Process.pdf"``. No bytes are read.
    """

    parts = _parts(relative_path)
    filename = parts[-1] if parts else relative_path
    name = filename.lower()
    lower_parts = {p.lower() for p in parts[:-1]}

    # Vendor/case evidence examples live under "Example Documents/". They are a
    # separate retrieval scope and are excluded from the institutional policy
    # corpus.
    if "example documents" in lower_parts:
        return Classification(
            category=SourceCategory.VENDOR_EVIDENCE_EXAMPLE,
            membership=CorpusMembership.CASE_VENDOR_EVIDENCE,
            status=ConfirmationStatus.EXAMPLE,
            activation_allowed=False,
            retrieval_scope=CitationScope.CASE_EVIDENCE,
            reason="Located under 'Example Documents/'; vendor/case evidence "
            "example, excluded from institutional policy.",
        )

    # A signed/completed TAAP is a filled example, not policy. Excluded.
    if "taap" in name and "signed" in name:
        return Classification(
            category=SourceCategory.SIGNED_TAAP_EXAMPLE,
            membership=CorpusMembership.EXCLUDED,
            status=ConfirmationStatus.EXAMPLE,
            activation_allowed=False,
            retrieval_scope=None,
            reason="Signed/completed TAAP example; excluded from institutional "
            "policy (a filled artifact, not a rule source).",
        )

    # Both decision trees are draft/unconfirmed. They stay institutional but
    # cannot be activated until a human confirms them (PRD open question;
    # FR-3 precedence 3, below any formal process).
    if name.startswith("sc decision tree"):
        return Classification(
            category=SourceCategory.DECISION_TREE,
            membership=CorpusMembership.INSTITUTIONAL_POLICY,
            status=ConfirmationStatus.DRAFT_UNCONFIRMED,
            activation_allowed=False,
            retrieval_scope=CitationScope.POLICY,
            precedence=SourcePrecedence.DECISION_TREE_DRAFT,
            reason="Draft/unconfirmed decision tree; not authoritative and not "
            "activatable until confirmed by a human (FR-3 precedence 3).",
        )

    rule = _KNOWN.get(name)
    if rule is not None:
        return Classification(
            category=rule.category,
            membership=rule.membership,
            status=rule.status,
            activation_allowed=rule.activation_allowed,
            retrieval_scope=rule.retrieval_scope,
            precedence=rule.precedence,
            reason=rule.reason,
        )

    return Classification(
        category=SourceCategory.UNCLASSIFIED,
        membership=CorpusMembership.UNRESOLVED,
        status=ConfirmationStatus.UNCLASSIFIED,
        activation_allowed=False,
        retrieval_scope=None,
        reason="No classification rule matched this filename.",
        notes=("requires human classification before use",),
    )
