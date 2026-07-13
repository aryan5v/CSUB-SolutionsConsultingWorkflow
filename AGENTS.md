# Agent and contributor instructions

## Project intent

This repository contains the CSUB Solutions Consulting Workflow prototype for CSU AI Summer Camp 2026. The partner problem statement is intentionally a placeholder until the CSU partner provides the brief. Do not invent requirements, workflows, data sources, or success criteria and present them as facts.

## Before making changes

1. Read `README.md`, `CLAUDE.md`, and `docs/PRD.md`.
2. Check the current Git status and preserve unrelated user changes.
3. Identify whether the change is discovery/documentation, application code, infrastructure, or testing.
4. If the change depends on missing partner information, document the assumption and add an open question to the PRD.

## Engineering guidance

- Use AWS CLI commands for repeatable infrastructure inspection and deployment workflows.
- Keep AWS account, region, profile, and resource names configurable; do not hard-code credentials or personal account details.
- Prefer least-privilege IAM policies, encryption at rest and in transit, structured logs, and explicit retention rules.
- Keep provider-specific calls behind small interfaces so the core workflow can be tested without live AWS services.
- Add tests with behavior changes. For infrastructure changes, include validation or a dry-run path where practical.
- Do not commit `.env` files, access keys, tokens, generated artifacts, or user-provided institutional data.
- Favor small, reviewable commits with clear messages.

## Documentation expectations

- Update `docs/PRD.md` when requirements or scope change.
- Record meaningful architecture choices in `docs/decisions/` using a short ADR when that directory is introduced.
- Keep `README.md` focused on getting a new contributor productive.
- Use `TBD`, `Assumption`, and `Open question` labels rather than hiding uncertainty.

## Validation checklist

Before handing off a change:

- Run the most relevant tests or checks available.
- Review `git diff` for secrets, unrelated edits, and accidental generated files.
- Confirm documentation matches the current implementation.
- If AWS access is required, state which account/profile/region was used and avoid including sensitive output.
