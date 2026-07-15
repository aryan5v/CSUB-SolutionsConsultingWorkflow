# 0009 - Vendor evidence wired into the review graph

- Status: Accepted
- Date: 2026-07-14
- Deciders: AWS/integration owner
- Related: [ADR 0007](0007-langgraph-binding.md), [ADR 0008](0008-vendor-evidence-portal.md), [PLAN](../../PLAN.md)

## Context

ADR 0008 built the vendor evidence portal as a standalone capability. To match
PLAN.md's target workflow it needs to be a node in the review graph: after the
deterministic policy engine names the required evidence, the case should send the
vendor link, pause for the drop, then resume into gap analysis before packet
composition — with the pause durable across a restart.

## Decision

1. **A new human/vendor interrupt: `AWAITING_VENDOR_EVIDENCE`.** After a
   non-escalated policy result, `needs_vendor_evidence` is true when a portal is
   wired, policy named required evidence, and none has been gathered.
   `request_vendor_evidence` sends the link (notify vendor + committee), deploys
   research, checkpoints, and pauses. `submit_vendor_evidence` resumes: it records
   the drop, runs `evaluate_evidence_gaps`, then specialists → packet.
2. **Additive state, contract kept in sync.** `ReviewGraphState` gains
   `vendor_invite`, `vendor_research`, `evidence_records`, and `gap_report` (all
   defaulted) plus the new status; the locked JSON Schema
   (`review-graph-state.schema.json`) is updated to match. Existing fields and
   callers are untouched.
3. **The portal is optional and off by default.** `ReviewWorkflow(portal=None)`
   behaves exactly as before, so every existing test and the LangGraph parity
   tests are unchanged. The gap step is a no-op without a portal or evidence.
4. **The LangGraph graph gains two nodes.** `request_vendor_evidence` (→ END, the
   interrupt) and `evaluate_evidence_gaps` (→ run_specialists). Routing out of the
   policy node mirrors `_analyze_and_compose`: escalate / await-vendor / analyze.
   On resume the same graph, re-invoked with evidence present, routes past the
   interrupt into gaps.

## Consequences

- The portal is now part of the workflow: a case that needs vendor documents
  pauses durably and resumes into deterministic gap analysis. Verified live in
  us-west-2 end to end (pause with Bedrock research + DynamoDB checkpoint → drop
  to bucket → resume → `missing: [soc2, vpat_acr]` → packet), plus unit and
  LangGraph parity/resume tests. CI stays stdlib-only.
- The draft packet does not yet render the gap report; surfacing gaps and research
  in the packet/UI is a follow-on.

## Assumptions and open questions

- ASSUMPTION: vendor contact defaults to `security@<official_domain>` and the
  committee to a configured list; real recipient resolution comes with the intake
  UI/API. The invite nonce is the case id in the prototype; production injects a
  high-entropy secret so links are unguessable.
