# CSUB Solutions Consulting Workflow

An AWS-first prototype for the CSU AI Summer Camp 2026. The exact partner-campus problem is still being finalized; this repository provides the shared project shell so the team can start discovery, design, and implementation quickly once the brief arrives.

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
├── AGENTS.md             Guidance for coding agents and contributors
├── CLAUDE.md             Claude Code project instructions
└── .env.example          Environment variable template
```

## Current status

- [x] Repository shell created
- [x] Starter PRD created
- [x] AWS CLI/MCP workflow documented
- [ ] Receive and validate the CSU partner problem brief
- [ ] Select the first user journey and success metric
- [ ] Choose the smallest viable AWS architecture
- [ ] Build, test, and demo the prototype

## Local setup

1. Clone the private repository and enter the project directory.
2. Copy `.env.example` to `.env` only if the eventual application needs local configuration. Never commit `.env` or credentials.
3. Confirm the AWS CLI is available:

   ```bash
   aws --version
   aws sts get-caller-identity
   ```

4. Read [`AGENTS.md`](AGENTS.md), [`CLAUDE.md`](CLAUDE.md), [`docs/PRD.md`](docs/PRD.md), and [`infra/README.md`](infra/README.md) before adding implementation details.

## Development principles

- Start from the partner campus's actual workflow and constraints.
- Prefer a narrow, demonstrable prototype over premature platform breadth.
- Use AWS managed services when they reduce operational burden, while keeping interfaces replaceable and testable.
- Keep student, staff, and institutional data private by default.
- Record important assumptions and decisions in `docs/`.
