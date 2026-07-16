# Engineering system and code shape

## Repository architecture

The repository is a small polyglot monorepo with explicit ownership boundaries:

```text
apps/reviewer-web/       React/Vite requester and reviewer interface
services/auth-api/       TypeScript Lambda for reviewer session/auth (Cognito + Better Auth)
services/review-agent/   Python orchestration, ingestion, policy, tools, and packet logic
packages/contracts/      OpenAPI and JSON Schema contracts shared across languages
infra/                   AWS CDK TypeScript application and deployment runbooks
tests/                   Contract, integration, end-to-end, gold-case, and adversarial tests
scripts/                 Dependency-light repository automation
```

Do not place new application code in a generic root `src/` directory. A component belongs to exactly one deployable workspace. Cross-language interfaces originate in `packages/contracts/`; generated clients are outputs, not hand-edited sources.

Within `services/review-agent`, keep ingestion, deterministic policy, workflow orchestration, model adapters, and external tools as separate modules. Provider SDK calls stay behind interfaces so tests can use local fakes.

## Dependency and tool policy

- Commit one lockfile per workspace and use frozen/locked installs in CI.
- Pin GitHub Actions to full commit SHAs; Dependabot maintains the annotated versions.
- Prefer standard-library repository scripts and workspace-local tools over globally assumed commands.
- Add a dependency only when it removes more complexity than it introduces.
- Do not run package lifecycle scripts from untrusted branches with write-capable credentials.
- A new language or package manager must add bootstrap, lint, type-check, test, build, cache, Dependabot, and CodeQL coverage in the same pull request.

## Quality pyramid

1. Pre-commit: staged whitespace, common secret patterns, structure, and documentation links.
2. Pre-push/local: `make verify`, including repository tests and syntax checks.
3. Pull request: required repository checks, dependency review, CodeQL/code-scanning policy, teammate approval, and resolved conversations.
4. Component CI: workspace lint, type checks, unit tests, contract validation, and builds as components land.
5. Integration: local AWS fakes, LangGraph pause/resume, retrieval isolation, ServiceNow mock, and gold cases.
6. Deployment: CDK synth/diff, least-privilege review, budget/retention/teardown checks, then canary validation.

Merges to `main` use the guarded AWS release workflow documented in
[`../docs/decisions/0008-guarded-main-to-aws-delivery.md`](decisions/0008-guarded-main-to-aws-delivery.md).
The build job must remain credential-free. The production job may consume only
the checksum-verified bundle, must inspect every stack before executing any
change set, and advances the last-known-good pointer only after canaries pass.
Security-sensitive infrastructure changes remain a human SSO operation.

No agent may weaken or skip a gate to make its own change pass. If a gate is incorrect, fix it in a separate, explained change with independent review.

## Contract discipline

- Define API payloads, graph state, policy results, citations, packets, and ServiceNow operations as versioned contracts before implementing consumers.
- Validate at process and trust boundaries.
- Maintain backward compatibility inside an active integration window or coordinate every consumer in one change.
- Generated clients must be reproducible and checked for drift in CI once generation is introduced.
- Database and policy migrations require forward, backward, and rollback behavior plus fixtures.

## Observability and failure behavior

- Use structured events with correlation, case, workflow, policy, model, tool, and decision versions.
- Never log credentials, document bodies, sensitive prompts, or unnecessary institutional content.
- Timeouts, retries, idempotency, concurrency conflicts, and partial failure are explicit behaviors, not catch-all exceptions.
- Model and tool failures must produce reviewable states rather than silently changing risk or approval outcomes.

## Definition of ready for implementation

A task has a linked requirement, one owner, path boundaries, stable contracts, acceptance criteria, test approach, data classification, and exact verification commands. Tasks missing these inputs stay in planning rather than being handed to a coding agent.
