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
