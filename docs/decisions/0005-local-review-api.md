# ADR 0005: Local Review API Adapter

## Status

Accepted for the initial local application.

## Context

PRs #7 and #10 already implement the review contracts, deterministic lookup and
policy engine, bounded specialists, packet composition, checkpoints, audit, and
approval-gated `MockServiceNowConnector` in `services/review-agent`. PR #8
provides the browser workspace, while `services/case-api` is still a production
TypeScript Lambda boundary with no handlers. Reimplementing the workflow in
TypeScript merely to connect the local UI would create two policy and connector
implementations during the three-day prototype.

## Decision

Expose the existing Python workflow through a dependency-free local adapter:

- `review_agent.api.LocalReviewApi` composes `ReviewWorkflow`, the shared domain
  contracts, deterministic local model/storage behavior, and
  `MockServiceNowConnector`.
- `review_agent.server` exposes the PRD routes on localhost with JSON responses,
  one-shot SSE state, bounded request bodies, structured errors, and localhost
  CORS. It defaults to sanitized synthetic cases and never performs a live
  ServiceNow write.
- `apps/reviewer-web/src/api.ts` is the typed browser seam. Vite proxies `/api`
  to `127.0.0.1:8787` for local development.
- Fuzzy/semantic confirmation resumes analysis through `POST /cases/{id}/analyze`
  with reviewer attribution. Reviewer edits and decisions use
  `POST /cases/{id}/review`; preview returns and stores the expected mock-record
  version, and commit must match that exact preview plus a separate explicit
  confirmation.

The OpenAPI and ServiceNow operation schema are updated in the same change as
both consumers. Field mappings remain deterministic backend configuration; the
browser and model cannot select writable fields. The initial reviewer identity
and `LocalWritebackConfig` are sanitized seeded configuration; Cognito-derived
reviewer identity and administrator-loaded mappings remain production work.

## Consequences

- The initial app runs end to end without live AWS, third-party Python runtime
  dependencies, institutional data, or a second rules implementation.
- The local server is not the production API Gateway/Lambda architecture. It
  has no production authentication, persistence, upload content handling, or
  multi-process durability and must bind to localhost by default.
- `services/case-api` remains the owner of the future TypeScript Lambda adapter.
  That adapter should call the review runtime behind the same OpenAPI contract,
  add Cognito authorization and durable storage, and replace—not fork—the local
  transport.
- Broader PR #8 vendor/workflow/settings pages remain sanitized local prototype
  surfaces; the consequential review path is the connected portion.
