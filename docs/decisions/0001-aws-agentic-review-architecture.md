# ADR 0001: AWS-first bounded agentic review architecture

- Status: Accepted for prototype
- Date: 2026-07-14

## Context

The team has three days to demonstrate a technology-review workflow using a fixed Box dataset. The workflow requires structured spreadsheet lookup, policy decisions, parallel document analysis, human review, and a ServiceNow-shaped handoff. Live ServiceNow access and additional data are not expected.

## Decision

Use an AWS-first architecture with:

- React/Vite on S3 and CloudFront, Cognito, API Gateway, and TypeScript Lambdas.
- Python LangGraph on Bedrock AgentCore Runtime for parallel specialists, bounded repair, checkpointing, and human interruption.
- Deterministic application code for approved-software confirmation, policy calculation, risk tier, and write-back authorization.
- DynamoDB for structured state, KMS-encrypted S3 for files/artifacts, and Knowledge Bases with S3 Vectors for scoped retrieval.
- A contract-faithful `MockServiceNowConnector` for the demo.
- Serac MCP only as a possible future restricted sidecar, never as the prototype's trust boundary or core workflow engine.

## Rationale

LangGraph fits the small number of explicit stateful branches without requiring an unconstrained autonomous agent. Structured data remains queryable and auditable rather than being flattened into embeddings. The connector interface makes the demo independent of unavailable ServiceNow access. Human approval and deterministic write controls protect consequential actions.

## Consequences

- The team must define shared schemas before parallel work begins.
- Policy sources must be manually verified and versioned.
- AWS account, model, cost, retention, and teardown decisions are required before deployment.
- The mock connector is a committed deliverable; live ServiceNow is not.
- Agent outputs are drafts and evidence summaries, not institutional decisions.
- Unknown or conflicting policy must escalate rather than be inferred.
