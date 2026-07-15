# Case API

This workspace owns the future TypeScript Lambda/API Gateway application for
cases, uploads, review decisions, packet access, audit events, and the
configured ServiceNow connector boundary. It will provide Cognito authorization,
durable storage, and AWS deployment adapters without duplicating deterministic
policy or workflow logic.

For the initial local application, the public routes are implemented by the
standard-library adapter in
[`services/review-agent/src/review_agent/server.py`](../review-agent/src/review_agent/server.py)
over the existing Python workflow. The React workspace uses the same OpenAPI
contract through `apps/reviewer-web/src/api.ts`. This is an explicit prototype
transport choice recorded in
[ADR 0005](../../docs/decisions/0005-local-review-api.md), not a production
TypeScript Lambda implementation.

This boundary owns deterministic authorization, idempotency, optimistic
concurrency, and connector configuration when the AWS adapter lands. Models
cannot select tables, fields, records, or write operations.

## Implemented Lambda proxy (issue #20)

`src/index.ts` is the typed, unit-tested source of truth for the AgentCore
proxy. It uses AWS SDK v3 modular clients (S3 presigner, SQS, and the
`bedrock-agentcore` data-plane client) and reaches the runtime via SigV4 —
never `fetch`. It caps the JSON metadata surface at ≤ 1 MiB, allowlists
downstream headers (never forwarding Host/Authorization), issues case-scoped
presigned evidence uploads/packet downloads instead of streaming bytes through
API Gateway, forwards only invite-token **hashes**, and returns
correlation-ID-tagged errors without logging bodies, tokens, or secrets. Side
effects are injected (`createHandler(config, deps)`) so `test/handler.test.ts`
runs hermetically.

- `npm test` — vitest unit suite (auth/token/presign/body-limit/error paths).
- `npm run typecheck` — `tsc --noEmit`.
- `npm run build` — esbuild bundle to `dist/index.mjs` (deployable artifact;
  mirrors the committed `infra/lambda/case-proxy/index.mjs` that CDK packages).
