# ADR 0002: Agent-friendly engineering foundation

- Status: Accepted
- Date: 2026-07-14

## Context

The three-day prototype will be developed rapidly by humans using Codex, Claude Code, and parallel specialist agents. Fast parallel work increases the risk of overlapping edits, contract drift, unverified agent claims, dependency mistakes, and security regressions.

## Decision

- Use a polyglot monorepo partitioned into reviewer web, case API, review agent, language-neutral contracts, infrastructure, and cross-service tests.
- Use one repository-owned `make verify` command in local development, pre-push hooks, and CI.
- Use dependency-light local pre-commit hooks and GitHub-managed CodeQL, dependency review, Dependabot, secret scanning, and protected merges.
- Use bounded planner/coder/tester/verifier roles with independent verification and explicit file ownership.
- Pin Actions by SHA and lock application dependencies per workspace.

## Consequences

- The first change introducing a workspace must add its deterministic setup, lint, type-check, test, and build commands to the aggregate verification path.
- Agents cannot self-approve, bypass checks, or edit the same shared contracts concurrently.
- Root tooling changes require coordination because every workstream consumes them.
- CODEOWNERS remains deferred until teammate GitHub handles and ownership are confirmed; the repository still requires a teammate approval.
