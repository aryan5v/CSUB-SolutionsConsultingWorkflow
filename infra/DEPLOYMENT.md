# Deployment record — foundation stack

This is the recorded provisioning gate required before creating AWS resources
(see [`README.md`](README.md) "Provisioning gate", `CLAUDE.md` AWS section, and
`PLAN.md` Wednesday environment gate).

## Gate (recorded 2026-07-14)

| Field | Value |
|---|---|
| Purpose | First real deployment of the prototype storage foundation (PRD sec 5). |
| Account | `<SANDBOX_ACCOUNT_ID>` (AWS Innovation Sandbox — budget-capped, auto-expiring lease) |
| Profile / identity | SSO role `myisb_IsbUsersPS` (`dvillanueva8@csub.edu`) |
| Region | `us-west-2` (camp-designated region) |
| Resource owner | Danny Villanueva |
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
governed by an Innovation Sandbox SCP (`o-19qav45m70` / `p-nw6rpuvq`) that denies
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
