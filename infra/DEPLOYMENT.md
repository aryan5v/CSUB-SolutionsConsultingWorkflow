# Deployment record — foundation stack

This is the recorded provisioning gate required before creating AWS resources
(see [`README.md`](README.md) "Provisioning gate", `CLAUDE.md` AWS section, and
`PLAN.md` Wednesday environment gate).

## Gate (recorded 2026-07-14)

| Field | Value |
|---|---|
| Purpose | First real deployment of the prototype storage foundation (PRD sec 5). |
| Account | `<SANDBOX_ACCOUNT_ID>` (AWS Innovation Sandbox — budget-capped, auto-expiring lease) |
| Profile / identity | Approved sandbox SSO deployment role (recorded outside source; no personal identity committed). |
| Region | `us-west-2` (camp-designated region) |
| Resource owner | `<TEAM_OWNER>` |
| Budget / alarm | Enforced by the Innovation Sandbox lease (account-level cap + auto-cleanup) |
| Expiration | Governed by the sandbox lease |
| Data classification | Sanitized / synthetic prototype data only. No real institutional data. |
| Retention | Prototype; buckets and table are `DESTROY` on teardown (sandbox). |
| Teardown | `npm --prefix infra run destroy` (`cdk destroy`). See below. |

## What this stack creates (`ReviewFoundationStack`)

- A customer-managed **KMS key** (rotation enabled) for S3 encryption.
- **S3 raw-sources bucket** — SSE-KMS, public access blocked, TLS enforced,
  versioned. Layout target: `raw/<box-file-id>/<sha256>/<filename>`.
- **S3 normalized bucket** — SSE-KMS, public access blocked, TLS enforced.
- **DynamoDB `cases` table** — on-demand billing, KMS (AWS-managed) at rest,
  point-in-time recovery, partition key `case_id`.

All resources are tagged (`project`, `owner`, `environment`, `data-classification`)
and use `RemovalPolicy.DESTROY` + `autoDeleteObjects` so `cdk destroy` fully
cleans the sandbox.

## Estimated cost

Idle cost is dominated by the KMS customer-managed key (~$1/month) plus a few
cents of KMS/S3/DynamoDB request charges. On-demand DynamoDB and S3 are ~$0 when
idle. The sandbox lease is the hard budget ceiling.

## Commands

```bash
export AWS_PROFILE=myisb_IsbUsersPS-<SANDBOX_ACCOUNT_ID>
export AWS_REGION=us-west-2
export CDK_DEFAULT_ACCOUNT=<SANDBOX_ACCOUNT_ID>
export CDK_DEFAULT_REGION=us-west-2

npm --prefix infra ci                 # locked install
npm --prefix infra run synth          # cdk synth (non-mutating)
npm --prefix infra run diff           # cdk diff (non-mutating)
npx --prefix infra cdk bootstrap aws://<SANDBOX_ACCOUNT_ID>/us-west-2
npm --prefix infra run deploy         # cdk deploy
npm --prefix infra run destroy        # cdk destroy (teardown)
```

## Outcome — 2026-07-14 (DEPLOYED to us-west-2)

`ReviewFoundationStack` is deployed and `CREATE_COMPLETE` in `us-west-2`. Deployed
resources: KMS key `4b60a31d-6fae-41c4-80cb-64edea6528e3`, buckets
`reviewfoundationstack-rawsourcesbuckete4ca4f2f-ivlaanigsdc0` and
`reviewfoundationstack-normalizedbucketaeadf737-dqlssfghnexx` (both SSE-KMS +
public access blocked), DynamoDB table
`ReviewFoundationStack-CasesTableABF7127D-WD6X4VKUTEXT` (ACTIVE, on-demand).

### The sandbox SCP wrinkle and the fix

A first attempt with the default synthesizer **rolled back**. The account is
governed by an Innovation Sandbox SCP that denies
actions performed by **CDK's bootstrap `cfn-exec-role`** (a guardrail against
newly-created roles) — `iam:CreateRole`, `iam:DetachRolePolicy`, tagging, etc.

Crucially, those actions are **allowed for the deploying SSO identity itself**
(verified by probe: that identity can create, tag, and policy IAM roles directly).
The fix is to deploy with the CLI's own credentials instead of assuming the
blocked exec-role:

```ts
synthesizer: new cdk.CliCredentialsStackSynthesizer()
```

With this, CloudFormation acts as the permitted SSO identity and the deploy
succeeds — no SCP change or admin involvement required. See
[`SANDBOX-ACCESS-REQUEST.md`](SANDBOX-ACCESS-REQUEST.md) (now only needed if a
future stage hits an action the SSO identity itself lacks).

### Region note

Deployed to `us-west-2` (camp-designated region and the account's SSO region). An
earlier bootstrap in `us-east-1` was fully torn down (0 stacks / 0 CDK buckets
there).

## Security defaults applied

- Block public access on all buckets; no public exposure.
- KMS encryption at rest; TLS (`aws:SecureTransport`) enforced via bucket policy.
- Least-privilege: no IAM principals granted here beyond CDK's deploy role.
- No secrets, account-specific credentials, or institutional data in source.

## Platform stack (`PlatformStack`) — gate and runbook

`PlatformStack` deploys the supported core demo platform (Cognito,
CloudFront/OAC + private S3, HTTP API + Lambda proxy, DynamoDB records, ECR,
encrypted logging/alarms/dashboard, CloudTrail, SQS, and a monthly Budget).
AgentCore, Guardrail, and S3 Vectors/Knowledge Bases remain fully modeled but
are independently default-off behind typed deployment gates. It reuses the
foundation KMS key and `cases` table by reference.

### AWS Organizations SCP constraint

The current deployment environment explicitly denies
`s3vectors:CreateVectorBucket` and `bedrock-agentcore:CreateMemory` via AWS
Organizations service control policies. Creating either resource causes
CloudFormation rollback. Deploy the supported core with all three optional
feature flags false:

```bash
-c enableAgentCoreServices=false \
-c enableVectorStores=false \
-c enableGuardrail=false
```

No account or personal identity is required to document or apply these gates.
A future account may enable a service only after its effective SCPs are verified
to permit the relevant create APIs.

### CloudTrail audit-bucket compatibility

After the denied services were gated off, `AWS::CloudTrail::Trail`
`ManagementAudit` failed with `InvalidRequest`: CloudTrail had insufficient
permissions to validate/access its audit S3 bucket or the cross-stack
customer-managed KMS key. Because this bucket stores only CloudTrail management
logs, `AuditBucket` now uses S3-managed `AES256` encryption and the Trail does
not set `KMSKeyId`. This is intentionally limited to the audit bucket; evidence,
generated packets, raw/normalized sources, CloudWatch logs, queues, DynamoDB,
and other data stores retain their existing encryption.

The audit bucket still blocks all public access, enforces SSL, remains
versioned, expires objects after the configured finite retention period, and
auto-deletes for sandbox teardown. CDK still creates the CloudTrail service
bucket policy (`s3:GetBucketAcl` and scoped `s3:PutObject`). This avoids changing
the shared cross-stack KMS policy. No account or personal identifier is needed.

### Additional gate to record before deploying

| Field | Value |
|---|---|
| Budget | Monthly `budgetLimitUsd` (default 50 USD); optional `budgetNotificationEmail`. |
| Data classification | Sanitized/synthetic only. PII/PHI classification + guardrail-mode approval **required** before any Knowledge Base ingestion. |
| Cognito domain | Defaults to account/environment-unique `csub-reviewer-<environment>-<account>`; set `cognitoDomainPrefix`/`COGNITO_DOMAIN_PREFIX` to another globally unique prefix if unavailable. |
| Model IDs | Discover and pin `embeddingModelArn` / foundation-model IDs after auth; never commit them. |
| AgentCore services | Default `enableAgentCoreServices=false`; enable only where SCPs permit AgentCore create APIs. An image URI never bypasses this gate. |
| Vector stores | Default `enableVectorStores=false`; enable only where SCPs permit `s3vectors:CreateVectorBucket`. |
| Guardrail | Independent default `enableGuardrail=false`; enable only after guardrail-mode approval. |
| AgentCore image | After the master gate is allowed, publish the ARM64 HTTP image and pass its immutable digest as `agentCoreImageUri`. |
| Network mode | `PUBLIC` for sandbox; production delta is `VPC` (`agentCoreNetworkMode=VPC`). |

### Commands (non-mutating first)

```bash
export CDK_DEFAULT_ACCOUNT=<SANDBOX_ACCOUNT_ID>
export CDK_DEFAULT_REGION=us-west-2

npm --prefix services/auth-api ci
npm --prefix services/auth-api run typecheck
npm --prefix services/auth-api test
npm --prefix services/auth-api run build              # creates Lambda dist/index.mjs
npm --prefix infra ci
npm --prefix infra test                               # CDK unit assertions
npm --prefix infra run synth -- --strict              # offline, no credentials
npm --prefix infra run diff                          # review additive foundation export + new resources

# Deploy foundation first (adds a managed export), then the supported core.
npm --prefix infra run deploy -- ReviewFoundationStack
npm --prefix infra run deploy -- PlatformStack \
  -c cognitoDomainPrefix=<globally-unique-prefix> \
  -c enableAgentCoreServices=false \
  -c enableVectorStores=false \
  -c enableGuardrail=false \
  -c budgetLimitUsd=50 -c budgetNotificationEmail=<owner-email>

# Future allowed account only: verify effective SCPs first, then opt in.
npm --prefix infra run deploy -- PlatformStack \
  -c enableAgentCoreServices=true \
  -c agentCoreImageUri=<account>.dkr.ecr.us-west-2.amazonaws.com/<repo>@sha256:<digest> \
  -c enableVectorStores=true \
  -c embeddingModelArn=arn:aws:bedrock:us-west-2::foundation-model/<embed-model> \
  -c enableGuardrail=true
```

Use `AuthBaseUrl`, `AuthCognitoClientId`, and `AuthCognitoCallbackUrl` for the
VETTED Better Auth same-origin flow. Their secret values remain in Secrets
Manager. Demo Cognito self-signup verifies email and creates a reviewer account
for the seeded `csub-demo` workspace; it must not be treated as production
membership provisioning.

Use the resulting `CognitoDomainUrl`, `UserPoolClientId`, and
`CloudFrontDomain` outputs for the transitional public Cognito client and to set `VITE_COGNITO_DOMAIN`,
`VITE_COGNITO_CLIENT_ID`, and the exact
`https://<CloudFrontDomain>/app` redirect/logout variables for the reviewer
build. The transitional client is secretless and also allowlists only the documented
`http://127.0.0.1:5173/app` local-development origin. A separate confidential
client is generated for Better Auth; its secret is never output.

### Deployed artifact for the Lambda proxy

CDK packages `infra/lambda/case-proxy/index.mjs` (a committed, dependency-light
runtime handler) so synth stays offline. Its logic mirrors the typed,
unit-tested source in `services/case-api/src`; `npm --prefix services/case-api
run build` produces the fully bundled equivalent (`dist/index.mjs`) when a
self-contained artifact is preferred.

### Estimated cost and teardown

Idle cost is dominated by KMS keys (~$1/key/month) plus minimal S3/DynamoDB/logs
request charges; CloudFront, Cognito, API Gateway, and SQS are ~$0 idle. The
sandbox lease is the hard ceiling and the Budget provides an explicit alert.
Teardown: `npm --prefix infra run destroy` (with `destroyOnRemoval=true`,
buckets and the ECR repo self-empty). Delete the runtime/endpoint and any
ingested Knowledge Base data first if those were enabled.

## Main-to-AWS release runbook

The guarded workflow is defined in `.github/workflows/deploy.yml`; its design
record is `docs/decisions/0008-guarded-main-to-aws-delivery.md`. Required
repository variables are:

| Variable | Source |
|---|---|
| `AWS_ACCOUNT_ID`, `AWS_REGION`, `APP_ENV`, `PROJECT_OWNER` | Approved sandbox gate and deployed stack tags |
| `AWS_ROLE_TO_ASSUME`, `ALERT_TOPIC_ARN` | `VettedGitHubOidc` outputs |
| `FOUNDATION_STACK`, `PLATFORM_STACK` | `ReviewFoundationStack`, `PlatformStack` |
| `API_ENDPOINT`, `COGNITO_DOMAIN`, `COGNITO_CLIENT_ID`, `CLOUDFRONT_DOMAIN` | Public `PlatformStack` outputs |
| `CLOUDFRONT_DISTRIBUTION_ID` | Distribution resolved once by the SSO bootstrap |
| `COGNITO_DOMAIN_PREFIX` | Existing deployed Cognito prefix; prevents replacement drift |
| `RETENTION_DAYS`, `REVIEW_MODEL_ID`, `BUDGET_LIMIT_USD` | Approved live stack configuration |
| `SERVICE_NOW_TABLE_NAME`, `DESTROY_ON_REMOVAL` | Approved connector and sandbox lifecycle posture |
| `EXPECTED_CATALOG_ROWS` | `982` for the reconciled demo export |

The `production` GitHub environment must retain its custom `main` deployment
branch policy. The repository OIDC subject must retain the ordered immutable
`repo` identity plus the ordered custom claims `context` and
`workflow_ref`. Changing the workflow filename, branch, repository, or
environment requires an intentional trust-policy update through SSO.

Normal merges deploy automatically. Use manual `dry-run` to create, inspect,
and then delete guarded change sets without executing them. `rollback` accepts
only a full main-branch SHA whose archive has a healthy marker. If a stack is
`UPDATE_ROLLBACK_FAILED`, stop automatic retries, inspect stack events, recover
through SSO, run the canaries, and record a new healthy release. SNS messages
contain only stage, commit, workflow URL, and rollback status.
