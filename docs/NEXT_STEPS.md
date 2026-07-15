# Next steps

Working backlog for the CSUB Technology Review Agent, kept in priority order.
`PLAN.md` is the phased execution plan and `docs/PRD.md` is the product source of
truth; this file tracks what to pick up next and why. Update it as items land.

_Last updated: 2026-07-14._

## Where we are

The backend review-agent runs end to end and is wired to **real AWS** (behind
`USE_LOCAL_FAKES=false`), verified live in us-west-2:

- Bedrock (Claude Sonnet 4.5 + Nova) behind `BedrockModelClient`.
- KMS-encrypted S3 + on-demand DynamoDB for evidence and case snapshots.
- Durable pause/resume via `DynamoDbCheckpointer`.
- Real `langgraph.StateGraph` binding of the workflow.
- Vendor evidence portal (link → notify vendor + committee → research agent →
  drop to bucket → deterministic gap analysis), wired into the graph as an
  `awaiting_vendor_evidence` interrupt.

Open PRs (stacked): `#14` (AWS integration), `#15` (vendor portal + wiring).
The `case-api` (intake front door) and `reviewer-web` UI are still stubs.

## Tomorrow (2026-07-15)

- [ ] **Feed a real product + real evidence document into `smoke_agents.py`.**
      Today the specialists analyze the synthetic sample cases, so their output is
      thin. Add a way to point the live runner at a real vendor product and pass a
      real HECVAT/SOC2/VPAT document's text as evidence context, so we can see the
      security/accessibility specialists produce substantive, grounded analysis.
      Keep it manual/gated (Bedrock only); no institutional data committed.

## Next up (highest leverage first)

1. [ ] **Surface the gap report + research in the packet and reviewer view.**
       The workflow now computes `gap_report` and `vendor_research`, but the draft
       packet does not render them yet. Add sections so a reviewer sees missing
       evidence and the (advisory, cited) research at review time. (Follow-on from
       ADR 0009.)
2. [ ] **Stand up `services/case-api` (TypeScript) against the locked OpenAPI
       contract.** This is the real intake front door — the endpoint a requester
       submits through and the API that drives the deployed workflow. Until this
       exists there is no automatic "on submit, store + start review" path.
3. [ ] **Real ingestion of the approved-software corpus.** Point an openpyxl
       `WorkbookReader` at the SNOW export (~982 rows), reconcile row/column
       counts, and back `ApprovedSoftwareIndex` with it. Keep `CSUBdocs/` out of
       Git; surface extraction warnings, never silently drop cells.
4. [ ] **Encode the real two-track decision tree into the policy engine.** Replace
       the placeholder thresholds with the accessibility + security tiers from
       `CSUBdocs/SC decision tree.docx` (highest-tier-wins). Route the "confirm"
       items (user-count threshold, liability-insurance amount, basic-controls
       list) through the conflict registry for Doug Cornell to validate — do not
       let a model resolve them.

## Retrieval, guardrails, and safety

5. [ ] **Bedrock Guardrails** on the model calls; wire `guardrail_id` through
       `BedrockModelClient` (the seam already exists).
6. [ ] **Separate retrieval scopes** for campus policy vs. vendor evidence
       (Knowledge Base / S3 Vectors), so evidence never crosses case/vendor/product
       boundaries.
7. [ ] **Full JSON-Schema validation.** Swap the lightweight `required`/`enum`
       checker for a real JSON-Schema validator behind the existing `validate()`
       entry point.

## Contacts, notifications, delivery

8. [ ] **Real recipient resolution.** Replace the derived
       `security@<official_domain>` / configured committee list with real vendor +
       committee contacts once the intake API captures them.
9. [ ] **Real notifications (SES/SNS)** behind the `Notifier` seam, with verified
       identities and Secrets Manager credentials. Keep the mock as the default
       until a channel is approved.

## Testing and demo readiness

10. [ ] **12 sanitized gold cases** (4 low, 4 medium, 4 high/unknown) covering the
        risk-boundary inputs: user count, cost, data levels, AI, SSO, integrations,
        classroom/public use, GDPR, PCI.
11. [ ] **Adversarial / edge tests:** malformed uploads, stale evidence,
        vendor/product mismatch, unresolved rules, and prompt-injection in
        retrieved/uploaded content.

## Observability, retention, ops

12. [ ] **Metrics** for analysis latency, model/tool failures, citations,
        escalation, approvals, and writes (CloudWatch).
13. [ ] **Retention/TTL** for case snapshots and evidence objects (DynamoDB TTL +
        S3 lifecycle), matching the PRD retention decision when it lands.

## Deferred / blocked

- **AgentCore Memory checkpointer** — blocked: the ISB sandbox denies AgentCore
  control-plane calls (`ListMemories` → `AccessDeniedException`). Needs a Memory
  resource provisioned with IAM. `DynamoDbCheckpointer` covers durable resume in
  the meantime (ADR 0006).
- **LangGraph-native resume** (`Command`/`interrupt`) + a DynamoDB
  `BaseCheckpointSaver`, plus `ReviewGraphState.from_dict` rehydration so a resumed
  process can continue the graph rather than only read the pause point (ADR 0007).
- **ServiceNow write-back** stays the `MockServiceNowConnector`; a restricted Serac
  MCP adapter is a later, sandbox-gated step (PLAN "Serac integration path").

## Housekeeping

- [ ] Merge the stacked PRs in order (`#14` → `#15`) once reviewed; retarget bases
      to `main` as parents land. A coding agent cannot approve/merge its own PR.
