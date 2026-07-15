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
- Secrets Manager for VETTED Better Auth/session and future connector credentials.

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
  a versioned SSE-S3 CloudTrail audit bucket. The audit bucket alone uses
  S3-managed encryption so CloudTrail can validate/write without access to the
  cross-stack KMS key; data/evidence stores remain KMS encrypted. All buckets
  block public access and enforce TLS.
- **DynamoDB (PITR on all):** vendor, product (catalog), contact, invite
  (keyed by `token_hash`, never plaintext), submission, review, profile
  (immutable `(user_id, version)`), integration-event, audit, and idempotency.
- **Cognito + VETTED Better Auth:** reviewer user pool with verified-email
  self-signup enabled for the sanitized demo, the existing secretless public
  client retained for reviewer-API migration, and a separate confidential
  authorization-code/PKCE client used only by Better Auth. Better Auth runs as
  a database-free Node.js 22 Lambda with eight-hour JWE cookie sessions. Its
  client secret and session key are KMS-encrypted in Secrets Manager and loaded
  at cold start; no secret value is stored in Lambda environment variables or
  outputs. Signup creates a reviewer demo account in the one seeded
  `csub-demo` workspace, not a new tenant.
- **Same-origin auth route:** CloudFront `/api/auth/*` targets an IAM-only Lambda
  Function URL through signed OAC. The behavior disables caching, forwards all
  auth cookies and OIDC query strings, and allowlists the origin/CSRF headers.
  Direct anonymous Function URL invocation is denied. Existing reviewer API
  routes remain Cognito-JWT protected and are not exposed by this behavior.
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
- **AgentCore (default off):** when `enableAgentCoreServices=true`, creates the
  least-privilege execution role, seven-day encrypted Memory, managed Browser,
  and — when an immutable image URI is also supplied — the ARM64 HTTP Runtime +
  Endpoint (`GET /ping`, `POST /invocations`, port 8080). With the master gate
  false, no `AWS::BedrockAgentCore::*` resource or AgentCore IAM is synthesized.
- **Guardrail (default off, independent):** when `enableGuardrail=true`, creates
  content + prompt-attack + PII + contextual-grounding policy with a pinned
  `GuardrailVersion` (never DRAFT).
- **Retrieval (default off):** when `enableVectorStores=true`, creates two S3
  Vector scopes (campus policy, case/vendor evidence). The two Bedrock Knowledge
  Bases additionally require `embeddingModelArn`; synth never ingests data.
  With the master gate false, no `AWS::S3Vectors::*`, Knowledge Base, KB IAM, or
  KB ingestion alarm is synthesized.
- **Observability:** KMS-encrypted log groups (finite retention), core CloudWatch
  alarms (API 5xx, proxy errors, DLQ depth), a conditional KB ingestion alarm,
  dashboard, and CloudTrail management auditing.
- **Cost:** a parameterized monthly AWS Budget (optional email subscriber).

### Configuration (context `-c key=value` or environment variable)

| Context key | Env var | Default | Effect / gate |
|---|---|---|---|
| `appEnv` | `APP_ENV` | `development` | Environment label and resource suffix. |
| `retentionDays` | `RETENTION_DAYS` | `90` | Finite retention for data, logs, audit. |
| `owner` | `PROJECT_OWNER` | `unspecified` | Owner tag. |
| `cognitoDomainPrefix` | `COGNITO_DOMAIN_PREFIX` | `csub-reviewer-<environment>-<account>` | Globally unique Cognito prefix domain; override if the derived prefix is unavailable in the Region. |
| `enableAgentCoreServices` | `ENABLE_AGENTCORE_SERVICES` | `false` | **Master gate:** AgentCore resources and AgentCore-specific IAM; image URI cannot bypass it. |
| `agentCoreImageUri` | `AGENTCORE_IMAGE_URI` | *(unset)* | With AgentCore enabled, creates Runtime + Endpoint. |
| `agentCoreNetworkMode` | `AGENTCORE_NETWORK_MODE` | `PUBLIC` | Sandbox `PUBLIC`; production `VPC`. |
| `enableVectorStores` | `ENABLE_VECTOR_STORES` | `false` | **Master gate:** S3 Vectors, Knowledge Bases, KB IAM/alarm. |
| `embeddingModelArn` | `EMBEDDING_MODEL_ARN` | *(unset)* | With vector stores enabled, creates the two Knowledge Bases. |
| `embeddingDimension` | `EMBEDDING_DIMENSION` | `1024` | S3 Vector index dimension (Titan V2 = 1024). |
| `enableGuardrail` | `ENABLE_GUARDRAIL` | `false` | Independent gate for Guardrail + pinned version. |
| `slackSecretArn` | `SLACK_SECRET_ARN` | *(unset)* | **Import only** — no placeholder is ever generated. |
| `serviceNowTableName` | `SERVICE_NOW_TABLE_NAME` | `sc_req_item` | Mock ServiceNow target (no credential). |
| `reviewModelId` | `REVIEW_MODEL_ID` | `us.anthropic.claude-sonnet-5` | Case Lambda reasoning inference profile; IAM is limited to this profile and its exact routed foundation-model ID. |
| `budgetLimitUsd` | `BUDGET_LIMIT_USD` | `50` | Monthly budget limit. |
| `budgetNotificationEmail` | `BUDGET_NOTIFICATION_EMAIL` | *(unset)* | Adds budget alert subscriber. |
| `destroyOnRemoval` | `DESTROY_ON_REMOVAL` | `true` | Sandbox teardown-safe (`DESTROY`); set `false` to retain. |

### AWS Organizations SCP compatibility

The current deployment environment explicitly denies
`s3vectors:CreateVectorBucket` and `bedrock-agentcore:CreateMemory` through AWS
Organizations service control policies. Either resource causes CloudFormation
creation to fail and the stack to roll back. The safe deployment profile is
therefore:

```bash
-c enableAgentCoreServices=false \
-c enableVectorStores=false \
-c enableGuardrail=false
```

This profile preserves CloudFront, Cognito, API Gateway/Lambda, DynamoDB, S3,
SQS/DLQ, CloudTrail, core CloudWatch monitoring, ECR, and the Budget. It emits
no AgentCore resources or AgentCore-specific IAM, and no S3 Vectors, Knowledge
Bases, KB IAM, or KB alarm. Use the `true` settings only after a different
account's effective SCPs have been verified to allow the corresponding create
APIs. No account or personal identity is required in configuration or source.

### CloudTrail sandbox compatibility

A core-stack creation reached `AWS::CloudTrail::Trail` but CloudTrail returned
`InvalidRequest` because it could not validate/access both the audit S3 bucket
and the cross-stack customer-managed KMS key. The audit bucket is dedicated to
CloudTrail management logs, so it intentionally uses S3-managed encryption
(`AES256`/SSE-S3), and the Trail does not set a KMS key. This avoids cross-stack
KMS policy changes while preserving CloudTrail's service bucket policy,
blocked public access, TLS-only access, versioning, finite lifecycle retention,
and teardown auto-delete. Evidence, generated packets, raw/normalized sources,
CloudWatch logs, queues, DynamoDB records, and other data stores retain their
existing encryption. No account or personal identifier is recorded here.

### Deployment gates (do not skip)

Before creating the gated resources, record PII/PHI classification and obtain
guardrail-mode approval. Do **not** ingest institutional data until that
approval is recorded. Discover and pin the embedding/foundation model IDs after
authenticating (`aws bedrock list-foundation-models`), then pass them via
context — never hard-code model IDs, account IDs, URLs, or credentials.

### VETTED authentication build and signup

Build `services/auth-api` before synth/deploy so `dist/index.mjs` is present:

```bash
npm --prefix services/auth-api ci
npm --prefix services/auth-api run typecheck
npm --prefix services/auth-api test
npm --prefix services/auth-api run build
```

`AuthBaseUrl`, `AuthCognitoClientId`, and `AuthCognitoCallbackUrl` are public
configuration outputs. The Cognito client secret and Better Auth session secret
remain only in Secrets Manager. The VETTED `/signup` experience starts the
Better Auth generic OIDC endpoint with `providerId: "cognito"` and
`requestSignUp: true`; Cognito verifies the email and the application treats the
account as a reviewer in the seeded `csub-demo` workspace. This demo setting
must be disabled or replaced by an institutional enrollment policy before
production.

The case Lambda receives `BEDROCK_REASONING_MODEL_ID` (default
`us.anthropic.claude-sonnet-5`) and `BEDROCK_MAX_TOKENS=1024`. The verified
Sonnet 5 profile rejects a `temperature` parameter, so callers must omit it.

### Reviewer frontend deployment outputs

After `PlatformStack` deploys, configure the reviewer frontend from stack
outputs (all values are public identifiers, not credentials):

| Frontend variable | Platform output/value |
|---|---|
| `VITE_COGNITO_DOMAIN` | `CognitoDomainUrl` |
| `VITE_COGNITO_CLIENT_ID` | `UserPoolClientId` |
| `VITE_COGNITO_REDIRECT_URI` | `https://<CloudFrontDomain>/app` |
| `VITE_COGNITO_LOGOUT_URI` | `https://<CloudFrontDomain>/app` |

The app client also allowlists `http://127.0.0.1:5173/app` for intentional
local development. Do not create users, passwords, or client secrets in source
or deployment scripts; demo-user provisioning remains an operator action.

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

## Guarded continuous delivery

The operator bootstraps GitHub OIDC once through the approved SSO profile:

```bash
AWS_PROFILE=<approved-sso-profile> AWS_REGION=us-west-2 \
  GITHUB_ORGANIZATION=<github-owner> GITHUB_REPOSITORY=<repository-name> \
  scripts/deploy/bootstrap_github_oidc.sh
```

The bootstrap creates the `production` GitHub environment with a main-only
branch rule, enables immutable custom OIDC subject claims, creates a
termination-protected `VettedGitHubOidc` stack, and outputs the deploy-role and
SNS alert-topic ARNs. Subscribe an operator to the topic, then set the public
stack outputs and ARNs as repository variables listed in
[`DEPLOYMENT.md`](DEPLOYMENT.md). Never store AWS keys in GitHub.

Every push to `main` runs `.github/workflows/deploy.yml`. Build and synth happen
without cloud credentials. The deployment job accepts only the sealed bundle,
guards both stacks before executing either one, promotes content-addressed UI
assets with `index.html` last, and runs release/auth/API/catalog canaries. An
exact healthy release is retained in the versioned frontend bucket for
automatic recovery. Manual workflow dispatch supports a non-executing dry run,
an explicit deploy, or rollback to a recorded healthy SHA.

Automatic CD intentionally blocks removal, replacement, IAM, auth, KMS, bucket
policy, and related security changes. Review those with `cdk diff` and deploy
through the approved SSO identity; there is no workflow bypass flag.
