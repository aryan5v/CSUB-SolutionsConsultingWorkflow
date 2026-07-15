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
