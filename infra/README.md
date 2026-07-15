# AWS infrastructure plan

The accepted architecture is recorded in [`../docs/decisions/0001-aws-agentic-review-architecture.md`](../docs/decisions/0001-aws-agentic-review-architecture.md). Infrastructure must remain configurable and reproducible; do not hard-code personal account details or credentials.

This directory owns the AWS CDK TypeScript application. The first infrastructure implementation change must add a locked package manifest plus deterministic format, lint, type-check, unit-test, `cdk synth`, and `cdk diff` commands and compose its non-mutating checks into the root `make verify` gate.

## Planned services

- S3 and KMS for raw sources, normalized snapshots, evidence, generated packets, and the static UI.
- CloudFront for UI delivery.
- Cognito requester and reviewer groups.
- API Gateway and TypeScript Lambdas for case and connector APIs.
- DynamoDB for cases, normalized structured records, workflow versions, decisions, audit events, and mock ServiceNow state.
- Bedrock models, Guardrails, Knowledge Bases, and S3 Vectors.
- Bedrock AgentCore Runtime, Memory, and restricted Browser.
- CloudWatch logs, metrics, alarms, and dashboards; CloudTrail for write-action auditing.
- Secrets Manager for future connector credentials.

## Required configuration

```bash
export AWS_PROFILE=<team-profile>
export AWS_REGION=<approved-region>
export APP_ENV=development
export PROJECT_OWNER=<team-owner>
export RESOURCE_EXPIRATION=<yyyy-mm-dd>
```

Discover and pin model/inference-profile IDs after authentication. Keep account, region, bucket, table, knowledge-base, model, and guardrail identifiers in environment-specific configuration.

## Provisioning gate

Before creating resources, record:

- Approved account/profile and region.
- Billing owner, prototype budget, and budget alarm threshold.
- Allowed data classification and sanitized-demo boundary.
- Resource owner and expiration date.
- IAM roles and read/write trust boundaries.
- Encryption, logging, retention, deletion, and backup behavior.
- Expected cost and teardown command/runbook.

Authenticate and verify identity without copying sensitive output into documentation:

```bash
aws sts get-caller-identity
aws bedrock list-foundation-models --region "$AWS_REGION"
```

## Security defaults

- Block public access on data buckets; expose only the intended static UI through CloudFront.
- Use KMS encryption, TLS, least-privilege roles, and separate ingestion/runtime/write permissions.
- Do not log document bodies, tokens, credentials, or unnecessary sensitive content.
- Restrict vendor browsing by domain and treat retrieved pages as untrusted.
- Require a deterministic approved human decision before connector write permissions are used.
- Keep the ServiceNow mock enabled by default; a future live/Serac connector requires a separate reviewed configuration and role.

## Teardown

The deployment implementation must provide a repeatable destroy path and document any retained buckets or tables. Before teardown, export only approved audit results, empty retained prototype data as authorized, remove secrets, verify stacks are deleted, and confirm that budget alarms and temporary identities no longer remain.

## Platform stack (`PlatformStack`)

`PlatformStack` is the AWS-native demo platform that composes with — and never
mutates the stable construct IDs of — `ReviewFoundationStack`. The shared
customer-managed KMS key and `cases` table are passed by object reference
(CDK-managed cross-stack references), not hand-written CloudFormation exports.

### What it creates

- **Storage:** KMS-encrypted, versioned evidence and generated-packet buckets
  (case-scoped presigned uploads/downloads), an SSE-S3 private frontend bucket
  served only through CloudFront **Origin Access Control (OAC, never OAI)**, and
  a KMS-encrypted CloudTrail audit bucket. All buckets block public access and
  enforce TLS.
- **DynamoDB (PITR on all):** vendor, product (catalog), contact, invite
  (keyed by `token_hash`, never plaintext), submission, review, profile
  (immutable `(user_id, version)`), integration-event, audit, and idempotency.
- **Cognito:** reviewer user pool (no self-service signup) + app client.
- **API (HTTP API + Lambda proxy):** reviewer/admin routes require the Cognito
  JWT authorizer; `/intake` and `/slack/events` are public at the
  gateway and enforced downstream (opaque token / signature). The invite token
  is token-free in the URL — it is read only from `Authorization: Bearer`,
  validated and hashed inside the Lambda, and never placed in a path or query.
  The Node 22 ARM64 Lambda proxy uses AWS SDK v3 (SigV4) to reach AgentCore —
  never `fetch` — caps the JSON metadata surface at ≤ 1 MiB, allowlists headers
  (never forwarding Host/Authorization), and returns correlation-ID errors
  without bodies/tokens.
- **Async boundary:** KMS-encrypted analysis SQS queue + DLQ.
- **AgentCore:** least-privilege execution role, seven-day encrypted Memory,
  a managed Browser for allowlisted research, plus a **gated** ARM64 HTTP
  Runtime + Endpoint (`GET /ping`, `POST /invocations`, port 8080) created only
  when an immutable image URI is supplied.
- **Guardrail:** content + prompt-attack + PII + contextual-grounding policy,
  with a pinned `GuardrailVersion` for application use (never DRAFT).
- **Retrieval:** two S3 Vector scopes (campus policy, case/vendor evidence);
  the two Bedrock Knowledge Bases + roles are **gated** on a configured
  embedding-model ARN and never ingest data at synth.
- **Observability:** KMS-encrypted log groups (finite retention), CloudWatch
  alarms (API 5xx, proxy errors, DLQ depth, KB ingestion failures), a
  dashboard, and CloudTrail management auditing.
- **Cost:** a parameterized monthly AWS Budget (optional email subscriber).

### Configuration (context `-c key=value` or environment variable)

| Context key | Env var | Default | Effect / gate |
|---|---|---|---|
| `appEnv` | `APP_ENV` | `development` | Environment label and resource suffix. |
| `retentionDays` | `RETENTION_DAYS` | `90` | Finite retention for data, logs, audit. |
| `owner` | `PROJECT_OWNER` | `unspecified` | Owner tag. |
| `agentCoreImageUri` | `AGENTCORE_IMAGE_URI` | *(unset)* | **Gate:** creates Runtime + Endpoint. |
| `agentCoreNetworkMode` | `AGENTCORE_NETWORK_MODE` | `PUBLIC` | Sandbox `PUBLIC`; production `VPC`. |
| `embeddingModelArn` | `EMBEDDING_MODEL_ARN` | *(unset)* | **Gate:** creates the two Knowledge Bases. |
| `embeddingDimension` | `EMBEDDING_DIMENSION` | `1024` | S3 Vector index dimension (Titan V2 = 1024). |
| `enableGuardrail` | `ENABLE_GUARDRAIL` | `true` | Create Guardrail + pinned version. |
| `slackSecretArn` | `SLACK_SECRET_ARN` | *(unset)* | **Import only** — no placeholder is ever generated. |
| `serviceNowTableName` | `SERVICE_NOW_TABLE_NAME` | `sc_req_item` | Mock ServiceNow target (no credential). |
| `budgetLimitUsd` | `BUDGET_LIMIT_USD` | `50` | Monthly budget limit. |
| `budgetNotificationEmail` | `BUDGET_NOTIFICATION_EMAIL` | *(unset)* | Adds budget alert subscriber. |
| `destroyOnRemoval` | `DESTROY_ON_REMOVAL` | `true` | Sandbox teardown-safe (`DESTROY`); set `false` to retain. |

### Deployment gates (do not skip)

Before creating the gated resources, record PII/PHI classification and obtain
guardrail-mode approval. Do **not** ingest institutional data until that
approval is recorded. Discover and pin the embedding/foundation model IDs after
authenticating (`aws bedrock list-foundation-models`), then pass them via
context — never hard-code model IDs, account IDs, URLs, or credentials.

### Coordinated (additive) foundation changes

Referencing the shared key/table adds a CDK-managed export to
`ReviewFoundationStack`, and the new lifecycle rules on the raw/normalized
buckets are in-place property updates. These are additive and cause **no
resource replacement** and **no logical-ID changes**; run `cdk diff` before
deploying to confirm.

### Teardown

With `destroyOnRemoval=true` (sandbox default) run `npm --prefix infra run
destroy`. Buckets (`autoDeleteObjects`) and the ECR repo (`emptyOnDelete`) empty
themselves; DynamoDB tables and the guardrail/version are deleted. For a
retention posture, set `destroyOnRemoval=false` and document which stateful
resources are intentionally retained before teardown.
