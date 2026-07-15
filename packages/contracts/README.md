# Shared contracts

This workspace is the source of truth for OpenAPI and JSON Schema definitions shared by TypeScript and Python components, including case intake, policy results, graph state, citations, packets, audit events, and ServiceNow operations.

Generated language bindings must be reproducible and must not be hand-edited. Contract changes require compatibility tests and coordination with every consumer.

## Layout

```text
openapi.yaml                     # Locked REST contract (PRD sec 5 public interface)
schemas/
  case-intake.schema.json        # CaseIntake (FR-1)
  approved-software-record.schema.json  # ApprovedSoftwareRecord (FR-2)
  software-match.schema.json     # SoftwareMatch with disclosed match method (FR-2)
  source-coordinates.schema.json # Traceable pointer to an institutional source
  policy-result.schema.json      # Deterministic PolicyResult (FR-3)
  conflict.schema.json           # Conflict registry entry (FR-3, never model-resolved)
  evidence-record.schema.json    # EvidenceRecord (FR-4)
  citation.schema.json           # Citation grounding a claim (FR-5)
  packet.schema.json             # Low/medium-risk Packet (FR-6)
  audit-event.schema.json        # Structured AuditEvent (sec 7)
  review-graph-state.schema.json # ReviewGraphState checkpoint (sec 5)
  review-queue-item.schema.json  # Reviewer queue projection plus current state
  review-queue.schema.json       # GET /review-queue response envelope
  case-action-response.schema.json # Analyze/review/preview/commit response envelope
  servicenow-operations.schema.json  # WritePreview / WriteResult / HumanDecision (FR-7)
```

## Status

Locked for Tuesday, July 14. The Python `services/review-agent` package mirrors these
schemas as dataclasses in `review_agent.contracts` and validates against them at boundaries.
`$id` values use the stable `https://csub.example/contracts/...` namespace for cross-schema
`$ref`; they are identifiers, not network fetches.

Changes after the Tuesday lock require coordinating every consumer in one change per
`docs/ENGINEERING.md` contract discipline.
