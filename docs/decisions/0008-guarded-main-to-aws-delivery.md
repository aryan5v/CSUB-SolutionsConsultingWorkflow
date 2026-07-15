# ADR 0008: Guarded main-to-AWS continuous delivery

- Status: Accepted
- Date: 2026-07-15

## Context

VETTED is demonstrated from an AWS sandbox where merges to `main` need to reach
the live CloudFront application without an operator rebuilding the release.
The account's Organizations policy blocks the standard CDK CloudFormation
execution role, so deployments must retain `CliCredentialsStackSynthesizer`.
That makes the GitHub entry role and release guard part of the primary security
boundary.

## Decision

`.github/workflows/deploy.yml` uses two jobs. The build job has read-only source
access and no OIDC permission; it runs `make verify`, creates the frontend and
CDK cloud assembly, and seals both in a checksum manifest. The production job
alone receives a short-lived AWS web-identity session. Its subject contains
immutable GitHub owner/repository IDs in the `repo` segment, the `production`
environment context, and the exact main-branch `workflow_ref`. The environment
permits only `main`.

Before any stack is executed, CD prepares and inspects change sets for both
`ReviewFoundationStack` and `PlatformStack`. Unknown actions, removal,
replacement, destructive policy actions, incomplete responses, and all
security-sensitive resource changes fail closed. Security changes use the
separate human SSO path; automatic CD has no override.

The candidate cloud assembly and frontend are archived under an immutable
commit key with SHA-256 digests. Infrastructure executes in dependency order,
the frontend uploads content-addressed assets before `index.html`, and public
plus IAM component canaries must pass before the last-known-good pointer moves.
Failure restores the exact previous healthy assembly in reverse dependency
order, restores its frontend, and reruns the canaries. Release phase records
are append-only in S3. SNS receives sanitized failure status only.

Manual dispatch supports `dry-run`, `deploy`, and rollback to a previously
recorded healthy commit. Concurrent runs are serialized; queued pushes may be
coalesced by GitHub to the latest `main`, so the contract is latest-main
delivery rather than deployment of every intermediate commit.

## Consequences

- Build scripts and dependencies never execute with AWS credentials.
- Rollback does not depend on source availability or a fresh dependency build.
- Destructive or IAM/auth/KMS policy changes require an SSO operator review.
- Direct Lambda catalog/queue canaries are component checks and do not claim to
  exercise Cognito/API Gateway authentication end to end.
- The CD role is intentionally scoped to this sandbox and these two stacks; a
  production institution rollout requires a separate account and policy review.
