# 0005 - S3 storage and DynamoDB cases persistence

- Status: Accepted
- Date: 2026-07-14
- Deciders: AWS/integration owner
- Related: [PRD](../PRD.md), [ADR 0001](0001-aws-agentic-review-architecture.md), [ADR 0003](0003-review-agent-local-slice.md), [ADR 0004](0004-bedrock-model-pinning.md)

## Context

The foundation stack (deployed to the us-west-2 sandbox) provides two
KMS-encrypted S3 buckets and an on-demand DynamoDB `CasesTable` keyed by
`case_id`. The local slice used `InMemoryStorage` behind the `StorageClient`
seam and had no durable case record. Wednesday wires both to real AWS without
changing the workflow code.

## Decision

1. **`S3Storage` enforces SSE-KMS per object.** The buckets already default to
   `aws:kms` with the foundation data key, but the writer also sets
   `ServerSideEncryption=aws:kms` and, when configured, `SSEKMSKeyId` explicitly,
   so every put is encrypted with the intended key regardless of bucket defaults
   (PRD sec 5). Callers own the key layout (`raw/<box-file-id>/<sha256>/...`).
2. **`DynamoDbCasesRepository` stores a JSON blob plus queryable attributes.** A
   case record is a `ReviewGraphState.to_dict()` snapshot serialized to a single
   `record` string, with top-level `case_id`/`status`/`updated_at` attributes for
   lookup and operator visibility. The blob avoids DynamoDB's item-type
   constraints (floats, empty strings, deep nesting) so snapshots round-trip
   losslessly. Writes are idempotent replaces keyed by `case_id`.
3. **`boto3` stays lazy and injectable.** Both adapters import `boto3` only when a
   client is first needed and accept an injected `client` for tests, so CI runs
   on the stdlib fakes with no boto3 or network. The not-found path in
   `S3Storage.exists` is duck-typed on the exception's `response` attribute to
   avoid importing `botocore` in CI.
4. **Config-driven factories.** `build_storage` / `build_cases_repository` return
   the in-memory fakes when `USE_LOCAL_FAKES` is set (default) and the live
   clients otherwise, reading resource names/ARNs from env only. No account ID or
   resource name is committed.

## Consequences

- Durable, encrypted persistence is available today; verified end-to-end by
  `services/review-agent/scripts/smoke_storage.py` (manual, live, cleans up after
  itself). CI stays green on injected fakes — 11 new unit tests, no boto3.
- The cases repository is snapshot-oriented; richer per-case indexes (GSIs, TTL)
  can be added later without changing the interface.

## Assumptions and open questions

- ASSUMPTION: a single JSON blob per case is sufficient for the prototype; if
  reviewers need server-side filtering by status/date, add a GSI later.
- Open question: retention/TTL for case records and evidence objects remains a
  PRD open question, not resolved here.
