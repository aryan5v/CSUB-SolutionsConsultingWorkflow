# Contributing

## First-time setup

1. Read `AGENTS.md`, `docs/PRD.md`, `PLAN.md`, `docs/ENGINEERING.md`, and `docs/AGENT_WORKFLOW.md`.
2. Create the local development environment and Git hooks:

   ```bash
   make bootstrap
   ```

3. Confirm the repository is healthy:

   ```bash
   make verify
   ```

`make bootstrap` creates an ignored `.venv`, installs the pinned pre-commit version, and installs pre-commit and pre-push hooks. It does not install application dependencies; each application or service owns its lockfile and setup instructions.

## Development workflow

- Start from current `main` and use a short-lived branch or worktree.
- Use the `Agent task` issue form for parallel Codex or Claude Code work.
- Keep one observable outcome and one primary code owner per task.
- Do not overlap shared-contract edits across agents.
- Add or update tests with every behavior change.
- Run focused checks while iterating and `make verify` before pushing.
- Open a small pull request linked to its PRD requirement and task.
- The authoring agent cannot be the only verifier. Preserve command output or CI links.
- Use squash merge after required CI, security analysis, review, and conversation resolution pass.

## Commit and pull-request quality

- Use imperative, outcome-focused commit messages.
- Keep generated files, institutional data, credentials, and local artifacts out of Git.
- Explain architecture or policy changes in an ADR.
- Include exact validation commands and meaningful results in the pull request.
- If a change introduces a new language, package manager, service, or generated contract, update `docs/ENGINEERING.md`, CI, CodeQL coverage, and Dependabot in the same pull request.

## Command contract

- `make check`: fast repository, documentation, and secret-pattern checks.
- `make lint`: syntax/static checks available without application dependencies.
- `make test`: repository-foundation unit tests.
- `make verify`: the required aggregate local/CI gate.
- `make hooks`: reinstall Git hooks after changing `.pre-commit-config.yaml`.
- `make agent-briefs`: regenerate ignored AgentProp briefs when AgentProp is installed.

Application workspaces must add their own deterministic install, lint, type-check, test, and build commands and compose them into `make verify` rather than creating a separate undocumented quality path.
