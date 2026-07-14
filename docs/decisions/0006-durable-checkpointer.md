# 0006 - Durable checkpointer for pause/resume

- Status: Accepted
- Date: 2026-07-14
- Deciders: AWS/integration owner
- Related: [PRD](../PRD.md), [ADR 0003](0003-review-agent-local-slice.md), [ADR 0005](0005-s3-and-dynamodb-persistence.md)

## Context

The workflow pauses at human-interrupt boundaries (match confirmation,
escalation, awaiting review). The `Checkpointer` seam from ADR 0003 persisted
`ReviewGraphState` snapshots only in memory, so a pause did not survive a process
restart. PRD sec 5 calls for durable pause/resume, originally sketched as
LangGraph + AgentCore Memory with a seven-day TTL.

## Decision

1. **Durability ships on DynamoDB now.** `DynamoDbCheckpointer` implements the
   existing `Checkpointer` protocol by delegating to the `CasesRepository` (ADR
   0005), so a case's snapshot is one KMS-encrypted record keyed by `case_id` in
   the deployed `CasesTable`. A fresh checkpointer in a later process loads the
   snapshot and resumes — verified live across two independent processes.
2. **AgentCore Memory is a documented seam, not wired.** The camp sandbox denies
   AgentCore control-plane calls (`ListMemories` -> `AccessDeniedException` under
   the ISB SCP), and a Memory resource must be provisioned with IAM first.
   `AgentCoreMemoryCheckpointer` keeps the interface real and fails with an
   actionable message; swapping it in later is a `build_checkpointer` change once
   provisioning is approved.
3. **Config-driven factory.** `build_checkpointer` returns `InMemoryCheckpointer`
   when `USE_LOCAL_FAKES` is set (default and CI) and `DynamoDbCheckpointer`
   otherwise. No workflow code changes to gain durability.

## Consequences

- Pause/resume is durable against real AWS today; snapshots survive process
  restarts. CI stays green — the checkpointer is tested over the in-memory cases
  repository, no boto3 or network.
- The checkpoint record and the case record are the same DynamoDB item (one
  durable snapshot per case), avoiding a second table and keeping resume simple.

## Assumptions and open questions

- ASSUMPTION: coarse whole-snapshot checkpointing is sufficient for the
  prototype; LangGraph's native per-thread checkpoint tuples are not required for
  the human-interrupt boundaries we resume from.
- Follow-on: full state rehydration (`ReviewGraphState.from_dict`) so a resumed
  process can *continue* the graph, not just read the pause point, lands with the
  LangGraph binding.
- Open question: the seven-day TTL/retention policy remains a PRD open question;
  DynamoDB TTL can be enabled on the table without an interface change.
