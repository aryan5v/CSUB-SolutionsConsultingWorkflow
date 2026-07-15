"""Run the AI agents against live Bedrock and print their output (manual).

Drives one case through the real security + accessibility specialists and the
vendor research agent on Bedrock, then shows the deterministic gap analysis.
Uses in-memory storage/checkpointer so it needs no S3/DynamoDB — only Bedrock
access. Nothing is written to any system; output is synthetic and non-sensitive.

    USE_LOCAL_FAKES=false AWS_REGION=us-west-2 \
        python services/review-agent/scripts/smoke_agents.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from review_agent.adapters.model import build_model_client  # noqa: E402
from review_agent.adapters.storage import InMemoryStorage  # noqa: E402
from review_agent.audit.log import AuditLog, InMemoryAuditSink  # noqa: E402
from review_agent.config import AppConfig  # noqa: E402
from review_agent.contracts.evidence import EvidenceType  # noqa: E402
from review_agent.contracts.graph_state import ReviewGraphState  # noqa: E402
from review_agent.lookup.approved_software import ApprovedSoftwareIndex  # noqa: E402
from review_agent.orchestration.graph import ReviewWorkflow  # noqa: E402
from review_agent.orchestration.state import InMemoryCheckpointer  # noqa: E402
from review_agent.policy.conflicts import default_conflict_registry  # noqa: E402
from review_agent.policy.rules import default_ruleset  # noqa: E402
from review_agent.samples import medium_risk_case, sample_records  # noqa: E402
from review_agent.vendor.link import LocalUploadLinkIssuer  # noqa: E402
from review_agent.vendor.notify import MockNotifier  # noqa: E402
from review_agent.vendor.portal import VendorEvidencePortal  # noqa: E402
from review_agent.vendor.research import ModelVendorResearch  # noqa: E402


def _show(title: str, result: dict) -> None:
    print(f"\n[{title} — live Bedrock]")
    print(f"  summary:     {(result.get('summary') or '(model returned none)')[:240]}")
    for finding in result.get("findings", [])[:3]:
        print(f"   - {str(finding)[:110]}")
    if result.get("uncertainty"):
        print(f"  uncertainty: {result['uncertainty'][:160]}")


def main() -> int:
    os.environ.setdefault("USE_LOCAL_FAKES", "false")
    config = AppConfig.from_env()
    if config.use_local_fakes:
        print("USE_LOCAL_FAKES is true; set it to false to exercise live Bedrock.")
        return 1

    model = build_model_client(config)
    print(f"model client: {type(model).__name__}")
    print(f"model id:     {config.model.reasoning_model_id}")

    audit = AuditLog(sink=InMemoryAuditSink())
    portal = VendorEvidencePortal(
        issuer=LocalUploadLinkIssuer(),
        notifier=MockNotifier(),
        research=ModelVendorResearch(model),
        storage=InMemoryStorage(),
        audit=audit,
    )
    workflow = ReviewWorkflow(
        model=model,
        software_index=ApprovedSoftwareIndex(sample_records()),
        ruleset=default_ruleset(),
        registry=default_conflict_registry(),
        audit=audit,
        checkpointer=InMemoryCheckpointer(),
        portal=portal,
    )

    state = ReviewGraphState(case_id="LIVE-AGENTS-1", case_input=medium_risk_case())
    workflow.run_until_review(state)  # pauses at vendor evidence
    print(f"\npolicy route: {state.policy_result.risk_route.value} | "
          f"required: {state.policy_result.required_evidence}")
    _show("VENDOR RESEARCH AGENT", state.vendor_research)

    # Vendor drops a HECVAT; resume runs the specialists on Bedrock.
    record = portal.ingest_upload(
        case_id=state.case_id, filename="hecvat.pdf", body=b"synthetic",
        evidence_type=EvidenceType.HECVAT,
    )
    workflow.submit_vendor_evidence(state, [record])
    _show("SECURITY SPECIALIST", state.specialist_results["security"])
    _show("ACCESSIBILITY SPECIALIST", state.specialist_results["accessibility"])
    print(f"\n[DETERMINISTIC GAP ANALYSIS] satisfied={state.gap_report['satisfied']} "
          f"missing={state.gap_report['missing']}")
    print(f"final status: {state.status.value}")
    print("\nLive agents smoke OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
