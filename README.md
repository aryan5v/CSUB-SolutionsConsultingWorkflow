# CSUB Solutions Consulting Workflow

[![CI](https://github.com/aryan5v/CSUB-SolutionsConsultingWorkflow/actions/workflows/ci.yml/badge.svg)](https://github.com/aryan5v/CSUB-SolutionsConsultingWorkflow/actions/workflows/ci.yml)

An AWS-first, human-reviewed technology-review prototype for CSU AI Summer Camp 2026. It uses the supplied CSUB Box dataset to check approved software, apply source-linked review rules, draft low- and medium-risk outcomes, and demonstrate simulated ServiceNow write-back.

## Context

This project is being developed as part of the [CSU AI Summer Camp 2026](https://dxhub.calpoly.edu/call-for-applicants-csu-ai-summer-camp-2026/) at Cal Poly San Luis Obispo. The working project name is **CSUB-SolutionsConsultingWorkflow**.

## Repository layout

```text
.
├── docs/                 Product requirements and project decisions
├── infra/                AWS architecture and deployment notes
├── scripts/              Local development and validation helpers
├── src/                  Application code (to be added after discovery)
├── tests/                Automated tests
├── PLAN.md               Three-day implementation and agent workstreams
├── AGENTS.md             Guidance for coding agents and contributors
├── CLAUDE.md             Claude Code project instructions
└── .env.example          Environment variable template
```

## Start here

- [`docs/PRD.md`](docs/PRD.md): product requirements, scope, interfaces, security constraints, and acceptance criteria.
- [`PLAN.md`](PLAN.md): Tuesday–Thursday workstreams, gates, agent responsibilities, and definition of done.
- [`docs/decisions/0001-aws-agentic-review-architecture.md`](docs/decisions/0001-aws-agentic-review-architecture.md): accepted architecture and tradeoffs.
- [`AGENTS.md`](AGENTS.md): mandatory coding-agent and contributor rules.
- [`infra/README.md`](infra/README.md): AWS configuration, deployment prerequisites, and teardown expectations.

## Current status

- [x] Partner workflow converted into a prototype PRD
- [x] Three-day implementation plan approved
- [x] AWS and bounded-agent architecture selected
- [ ] Ingest and validate the supplied Box dataset
- [ ] Complete the local low- and medium-risk vertical slices
- [ ] Deploy the approved AWS environment
- [ ] Evaluate, harden, and demo the prototype

## Local setup

1. Clone the private repository and enter the project directory.
2. Copy `.env.example` to `.env` only if the eventual application needs local configuration. Never commit `.env` or credentials.
3. Keep downloaded Box files under `data/raw/` and generated output under `artifacts/`; both are Git-ignored.
4. Confirm the AWS CLI is available:

   ```bash
   aws --version
   aws sts get-caller-identity
   ```

5. Read [`AGENTS.md`](AGENTS.md), [`CLAUDE.md`](CLAUDE.md), [`docs/PRD.md`](docs/PRD.md), [`PLAN.md`](PLAN.md), and [`infra/README.md`](infra/README.md) before implementation.
6. Run the same repository checks required by CI:

   ```bash
   make check
   ```

## Development principles

- Treat the PRD and supplied partner artifacts as the source of truth; keep remaining unknowns explicit.
- Prefer a narrow, demonstrable prototype over premature platform breadth.
- Use AWS managed services when they reduce operational burden, while keeping interfaces replaceable and testable.
- Keep student, staff, and institutional data private by default.
- Record important assumptions and decisions in `docs/`.
