# Request: AWS permissions to deploy the prototype (camp account)

**To:** AI Summer Camp AWS organization administrator (management account `<ORG_MGMT_ACCOUNT_ID>`)
**From:** Danny Villanueva (`dvillanueva8@csub.edu`)
**Account:** `<SANDBOX_ACCOUNT_ID>` (my ISB sandbox, SSO role `myisb_IsbUsersPS`)
**Region:** `us-west-2`

> **Status (2026-07-14): the foundation deploy is UNBLOCKED without this request.**
> Deploying with `CliCredentialsStackSynthesizer` (as the SSO identity, not CDK's
> blocked exec-role) succeeded. This request is retained only in case a later
> stage needs an action the SSO identity itself lacks. See `DEPLOYMENT.md`.

## What's blocking us

Deploying the CSUB Technology Review Agent prototype (AWS CDK) into my sandbox is
blocked by an explicit-deny in service control policy `p-nw6rpuvq`
(org `o-19qav45m70`). A `cdk deploy` of a minimal KMS + S3 + DynamoDB stack rolled
back with `AccessDenied` / `UnauthorizedTaggingOperation` on the actions below.

## Two acceptable resolutions

1. Relax SCP `p-nw6rpuvq` for this sandbox to allow the actions listed below, **or**
2. Provision a CSUB project account (ISB lease or standard account) that permits them.

## Minimum actions needed (foundation storage stack)

| Service | Actions |
|---|---|
| IAM | `CreateRole`, `DeleteRole`, `GetRole`, `PassRole`, `AttachRolePolicy`, `DetachRolePolicy`, `PutRolePolicy`, `DeleteRolePolicy`, `TagRole`, `UntagRole`, `CreatePolicy`, `CreateServiceLinkedRole` |
| Tagging | Resource tagging must be allowed (the SCP currently denies it): `iam:TagRole`, `kms:TagResource`, `dynamodb:TagResource`, `s3:PutBucketTagging`, `lambda:TagResource` |
| KMS | `CreateKey`, `TagResource`, `EnableKeyRotation`, `PutKeyPolicy`, `CreateAlias`, `ScheduleKeyDeletion` |
| DynamoDB | `CreateTable`, `DescribeTable`, `UpdateTable`, `DeleteTable`, `TagResource`, `UpdateContinuousBackups` |
| SSM | `GetParameters`, `GetParameter`, `PutParameter` (CDK bootstrap version) |
| S3 | already largely allowed; ensure `PutBucketTagging` and `PutEncryptionConfiguration` |

## Additional actions for the full application (Wednesday)

`bedrock:*` and `bedrock-agent*` (models, Guardrails, Knowledge Bases, AgentCore),
`lambda:*`, `apigateway:*`, `cognito-idp:*`, `cloudfront:*`, `logs:*`,
`cloudwatch:*`, `cloudtrail:*`, `secretsmanager:*`, plus S3 Vectors / OpenSearch
Serverless if used for retrieval.

## Notes

- Region `us-east-1` is already permitted (CDK bootstrap succeeded there).
- All prototype data is sanitized/synthetic; no real institutional data.
- The stack is teardown-safe (`cdk destroy`); the sandbox lease also auto-cleans.
- Until this is granted, the local vertical slice runs fully **without AWS** via
  deterministic fakes (`python -m review_agent.demo`), so the demo is not blocked.
