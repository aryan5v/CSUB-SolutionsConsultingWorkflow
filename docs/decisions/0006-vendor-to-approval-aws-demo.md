# ADR 0006: Vendor-to-approval AWS demo scope

- Status: Accepted
- Date: 2026-07-15

## Context

PR #16 connects the deterministic reviewer workflow to a polished local UI, but the client-facing demonstration must also reduce vendor effort, track the request before submission, use the supplied ServiceNow export correctly, and demonstrate an AWS-native deployed system. The prior plan classified vendor upload and ServiceNow import as stretch work and did not include Slack or configurable review profiles.

## Decision

The Thursday core flow is reviewer case creation, tracked vendor invitation, evidence and trust-center intake, deterministic adaptive questions, catalog lookup, parallel versioned security/accessibility review, cited packet, in-app human decision, Slack notification/Q&A with deep links, and two-step simulated ServiceNow write-back.

Catalog membership is not blanket approval. The complete export remains searchable and preserves explicit support and license signals. Product approval is scoped to the product, use case, evidence version, policy version, and active review-profile versions.

The prototype deploys one seeded `csub-demo` workspace on AWS. Cognito protects reviewer/admin routes; opaque expiring tokens protect vendor intake. Bedrock models may extract, research, analyze, and draft but cannot set policy, confirm semantic matches, approve, or write externally. AWS services are used where they provide a concrete capability: CloudFront/S3, Cognito, API Gateway/Lambda, DynamoDB, KMS/S3, Bedrock/Guardrails/Knowledge Bases, AgentCore Runtime/Memory/Browser, S3 Vectors, Secrets Manager, CloudWatch, CloudTrail, and budget controls.

## Consequences

- Vendor upload, adaptive intake, versioned profiles, Slack, and mock ServiceNow import become core demo work.
- Self-service tenant signup, Teams, live ServiceNow, arbitrary agent creation, and production rollout remain deferred.
- The Box corpus remains a development source, never an end-user integration, and is not ingested into Bedrock until its PII/PHI classification is confirmed.
- Fixture fallbacks must be explicit and labeled; they cannot silently replace failed live AWS analysis.
