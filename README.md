# Vetted

[![CI](https://github.com/aryan5v/CSUB-SolutionsConsultingWorkflow/actions/workflows/ci.yml/badge.svg)](https://github.com/aryan5v/CSUB-SolutionsConsultingWorkflow/actions/workflows/ci.yml)
[![Deploy](https://github.com/aryan5v/CSUB-SolutionsConsultingWorkflow/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/aryan5v/CSUB-SolutionsConsultingWorkflow/actions/workflows/deploy.yml)

An AWS-first, human-reviewed technology-review platform for CSU AI Summer Camp
2026. Vetted turns a ServiceNow ticket into a tracked vendor evidence
submission, runs deterministic policy routing with parallel security and
accessibility analysis, and drafts a cited packet a reviewer approves —
closing the loop with a simulated ServiceNow write-back and Slack
notifications.

## Context

This project is being developed as part of the [CSU AI Summer Camp 2026](https://dxhub.calpoly.edu/call-for-applicants-csu-ai-summer-camp-2026/) at Cal Poly San Luis Obispo. The working project name is **CSUB-SolutionsConsultingWorkflow**.

## Repository layout

```text
.
├── apps/                 User-facing deployable applications
├── services/             API and Python agent runtimes
├── packages/             Language-neutral shared contracts
├── docs/                 Requirements, engineering guidance, and decisions
├── infra/                AWS CDK and deployment notes
├── scripts/              Local development and validation helpers
├── tests/                Cross-service and acceptance tests
├── PLAN.md               Three-day implementation and agent workstreams
├── AGENTS.md             Guidance for coding agents and contributors
├── CLAUDE.md             Claude Code project instructions
└── .env.example          Environment variable template
```

The React/Vite reviewer workspace lives under `apps/reviewer-web/src/`. It adapts the Twenty
record-workspace and navigation patterns documented in
[`docs/decisions/0002-twenty-frontend-adaptation.md`](docs/decisions/0002-twenty-frontend-adaptation.md)
into a dashboard-first vendor-management prototype. The local sanitized demo
presents a focused reviewer information architecture in three navigation groups:
**Workspace** (Dashboard, a single Review queue, the Active review workspace, and
a clearly labeled preview Chat), **Records** (Review requests as the CRM hub via
`VendorRecordsPage`, Vendors as the reframed previously-approved software/vendor
catalog via `CatalogPage`, and Contacts backed by live `/vendor-contacts` CRUD),
and **System** (Audit, a two-tab Settings surface with the live Evidence policy
and Workspace preferences, and Documentation). The Active review workspace keeps
the two-step simulated ServiceNow write-back. The shell includes accessible
light/dark themes and the original
yellow/blue design language. Tailwind and shadcn configuration support locally
owned Dither Kit charts, gradients, buttons, and generative record avatars. See
[`docs/twenty-vendor-frontend-plan.md`](docs/twenty-vendor-frontend-plan.md) for
the phased Twenty-to-vendor adaptation plan.

**New request → vendor invite:** creating a case with vendor contact fields
find-or-creates the operational vendor/product/contact, issues a tracked intake
invitation, and records an invitation email attempt. The New Request form
offers a typeahead search over existing vendors (name or domain) instead of a
scroll-only dropdown. Email delivery is `simulated` locally; the deployed
Lambda sends live SES email when the stack is deployed with a verified sender
(`-c vendorEmailSender=...` or `VENDOR_EMAIL_SENDER`), which also grants the
scoped `ses:SendEmail` permission (issue #85 tracks requester notifications).
The reviewer UI still shows a copyable intake link either way. Vendor
`review_status` (`pending_review` / `accepted` / `declined`) is derived from
linked case lifecycles — it is not a stored Vendor table key and does not
mutate the institutional approved-software catalog.

## Start here

- [`docs/PRD.md`](docs/PRD.md): product requirements, scope, interfaces, security constraints, and acceptance criteria.
- [`PLAN.md`](PLAN.md): Tuesday–Thursday workstreams, gates, agent responsibilities, and definition of done.
- [`docs/decisions/0001-aws-agentic-review-architecture.md`](docs/decisions/0001-aws-agentic-review-architecture.md): accepted architecture and tradeoffs.
- [`docs/ENGINEERING.md`](docs/ENGINEERING.md): code shape, command contract, dependencies, quality gates, and service boundaries.
- [`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md): efficient Codex/Claude Code task routing, ownership, handoff, and independent verification.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): local setup and pull-request workflow.
- [`AGENTS.md`](AGENTS.md): mandatory coding-agent and contributor rules.
- [`infra/README.md`](infra/README.md): AWS configuration, deployment prerequisites, and teardown expectations.

## Current status

- [x] Partner workflow converted into a prototype PRD
- [x] Three-day implementation plan approved
- [x] AWS and bounded-agent architecture selected
- [x] Ingest the approved-software export locally (place the XLSX under `data/raw/`, which stays out of Git)
- [x] Complete connected local low-, medium-, and safe-escalation vertical slices
- [x] Deploy the approved AWS environment
- [x] Vendor lifecycle: adaptive per-case requirements, save-and-resume intake, request-changes resubmission, weekly reminders, and vendor-safe status
- [x] Integrations: simulated ServiceNow ticket import with automatic invitation issuance and two-step write-back; Slack notifications (live when a webhook is configured)
- [ ] Final demo rehearsal and recording ([`docs/DEMO.md`](docs/DEMO.md))

Not yet in the executing path (documented future work): live ServiceNow (#35),
Bedrock orchestration hardening and evaluations (#50), evidence content
validation (#48), vendor clarification threads (#41), and expiring-evidence
re-review (#53). LangGraph/AgentCore/Knowledge Bases mentioned in early
planning documents are aspirational, not wired.

Merges to `main` automatically create a verified, immutable AWS release. The
delivery workflow preflights both CloudFormation stacks before mutation, runs
live canaries, and restores the last-known-good cloud assembly and frontend on
failure. See [`docs/decisions/0008-guarded-main-to-aws-delivery.md`](docs/decisions/0008-guarded-main-to-aws-delivery.md).

## Local setup

1. Clone the repository and enter the project directory.
2. Copy `.env.example` to `.env` only if the eventual application needs local configuration. Never commit `.env` or credentials.
3. Keep downloaded Box files under `data/raw/` and generated output under `artifacts/`; both are Git-ignored.
4. Confirm the AWS CLI is available:

   ```bash
   aws --version
   aws sts get-caller-identity
   ```

5. Read [`AGENTS.md`](AGENTS.md), [`CLAUDE.md`](CLAUDE.md), [`docs/PRD.md`](docs/PRD.md), [`PLAN.md`](PLAN.md), [`docs/ENGINEERING.md`](docs/ENGINEERING.md), [`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md), and [`infra/README.md`](infra/README.md) before implementation.
6. Install the pinned Git hooks and run the same aggregate gate used by CI:

   ```bash
   make bootstrap
   make verify
   ```

7. Start the connected local application in two terminals:

   ```bash
   # Terminal 1: deterministic local API and workflow
   PYTHONPATH=services/review-agent/src python3 -m review_agent.server --port 8787

   # Terminal 2: reviewer workspace
   npm --prefix apps/reviewer-web ci
   npm --prefix apps/reviewer-web run dev
   ```

   Open `http://127.0.0.1:5173`. One Vite application serves the public landing
   page at `/`, the public vendor intake at `/intake`, and the authenticated
   reviewer workspace at `/app`. The application uses sanitized synthetic data
   and clearly labeled simulated ServiceNow operations; it does not require AWS
   credentials for the local flow.

## Development principles

- Treat the PRD and supplied partner artifacts as the source of truth; keep remaining unknowns explicit.
- Prefer a narrow, demonstrable prototype over premature platform breadth.
- Use AWS managed services when they reduce operational burden, while keeping interfaces replaceable and testable.
- Keep student, staff, and institutional data private by default.
- Record important assumptions and decisions in `docs/`.
