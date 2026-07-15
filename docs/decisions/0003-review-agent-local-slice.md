# 0003 - Review agent local vertical slice

- Status: Accepted
- Date: 2026-07-14
- Deciders: Integration owner
- Related: [PRD](../PRD.md), [PLAN](../../PLAN.md), [ADR 0001](0001-aws-agentic-review-architecture.md), [ADR 0002](0002-engineering-foundation.md)

## Context

Tuesday's gate requires a local vertical slice: locked shared contracts, lossless
approved-software ingestion, deterministic policy evaluation, bounded specialist
orchestration, packet composition, and a contract-faithful mock ServiceNow
write-back that runs end to end without provisioning AWS. The workspace was a
README-only stub. We need something runnable in CI today and cheap to extend
into the Wednesday AWS integration.

## Decision

Scaffold `services/review-agent` (Python) plus the `packages/contracts` schemas
with these choices:

1. **Contracts locked as JSON Schema, mirrored as Python dataclasses.** The
   schemas in `packages/contracts/schemas` are the cross-language source of
   truth; `review_agent.contracts` mirrors them and validates payloads at
   boundaries with a lightweight `required`/`enum` checker. A full JSON Schema
   validator can drop in behind the same `validate()` entry point later.
2. **Standard-library-only local slice.** No third-party runtime dependency is
   required to run the slice or its 44 unit tests, so CI stays green with a bare
   `python3`. LangGraph and boto3 are deferred to a pinned `aws` extra wired
   Wednesday.
3. **Every AWS/external boundary is an interface with a local fake.** `ModelClient`
   (Bedrock), `StorageClient` (S3), and `ServiceNowConnector` (mock) each have a
   deterministic local implementation and a documented seam. The
   `DeterministicModelClient` never touches the network and returns
   obviously-synthetic output so nothing is mistaken for a grounded finding.
4. **Deterministic policy, disputed thresholds escalate.** The policy engine is a
   pure function of a small explicit `PolicyInputs` surface. Threshold values are
   labeled ASSUMPTION and cited; genuinely disputed bands (the PRD open
   questions) live in a conflict registry and escalate to a human rather than
   being resolved by a model.
5. **Workflow as node functions over `ReviewGraphState`.** The orchestrator runs
   as a deterministic sequential runner with a `Checkpointer` boundary for
   pause/resume. Each method maps 1:1 to a LangGraph node so Wednesday binds the
   same functions to a graph with an AgentCore checkpointer.

## Consequences

- The Tuesday gate is demonstrable now: one low, one medium, and one safe
  escalation case run locally, plus a mock before/after write-back preview,
  idempotent commit, and packet attachment.
- Contracts are locked; changes after the lock must coordinate every consumer
  (TypeScript `case-api`, `reviewer-web`) per `docs/ENGINEERING.md`.
- Wednesday work is additive: implement `BedrockModelClient`, `S3Storage`, the
  LangGraph binding, and a full schema validator behind the existing interfaces;
  no local-slice code needs to change to keep tests deterministic.
- The TypeScript `case-api` and CDK `infra` remain README stubs; this ADR does
  not cover them.

## Assumptions and open questions

- ASSUMPTION: the encoded threshold bands are placeholders pending the
  partner-confirmed decision tree; they must be reconciled before the demo.
- Open questions from the PRD (approved AWS account/region, authoritative Box
  artifacts, partner-confirmed thresholds, reviewer authorization, retention)
  remain in the PRD and the conflict registry, not resolved here.
