# AWS infrastructure notes

This directory is intentionally documentation-only until the partner problem and data boundary are known.

## CLI conventions

Use an explicit profile and region once the team receives its AWS account details:

```bash
export AWS_PROFILE=<team-profile>
export AWS_REGION=<approved-region>
aws sts get-caller-identity
```

Do not commit credentials, `.aws` files, account IDs, ARNs, or secrets. Prefer short-lived credentials and least-privilege roles. Keep resource names environment-specific and tag resources with at least project, owner, environment, and expiration metadata.

## Before provisioning

Document the following in an ADR or the PRD:

- Account and approved region
- Data classification and allowed sample data
- Services and resources to create
- Expected cost and budget alarm
- IAM roles and trust boundaries
- Logging, encryption, retention, and deletion behavior
- Teardown command or runbook

## Candidate architecture

The PRD lists candidate AWS services, but no service is committed yet. Do not create cloud resources until the partner workflow, data boundary, and ownership are confirmed.
