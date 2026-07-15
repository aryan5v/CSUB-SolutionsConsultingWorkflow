# ADR 0002: Adapt Twenty Frontend Workspace Patterns

## Status

Accepted for the focused dashboard-first reviewer workspace.

## Context

The CSUB Technology Review Agent needs a reviewer workspace that can show record collections, relationships, workflow state, and supporting documents without becoming a generic analytics dashboard. The approved PRD calls for review runs, vendor/product evidence boundaries, human review, audit history, and a simulated ServiceNow write-back.

The frontend reference is [twentyhq/twenty](https://github.com/twentyhq/twenty), inspected at commit `58fcb3cb0ff21d0e4d1a5f00c85d5736de2e33af`. Its `twenty-front` and `twenty-ui` packages provide the relevant record-workspace patterns: navigation drawer, searchable record tables, composable card surfaces, dense relationship lists, and side detail panels.

## Decision

Adapt the frontend patterns into this lightweight React/Vite prototype rather than importing the complete Twenty monorepo. The dashboard remains the default operational handoff view, while the application preserves the broader PR #8 workspace:

- **Workspace:** Dashboard, Inbox, My work, Active review, and grounded Chat.
- **Records:** Vendors, Contacts, Review requests, Tasks, and Notes.
- **Automation:** Local workflow definitions, draggable/editable nodes, runs, and versions.
- **Review system:** Separate Evidence scopes and an immutable-style Audit history.
- **Administration:** Local Settings and reviewer Documentation.

Vendors are the durable relationship record; requests, runs, contacts, evidence, tasks, and notes remain linked operational records. The detailed review workspace still covers intake, approved-software candidate confirmation, deterministic routing, parallel findings, packet editing, a human decision, and separately confirmed simulated write-back.

The shell uses accessible light and dark themes, the original yellow/blue identity, restrained monospaced/ASCII accents, semantic controls, visible focus states, and responsive layouts. Tailwind and a shadcn `components.json` support locally owned Dither Kit charts, avatars, buttons, and gradients under `apps/reviewer-web/src/components/dither-kit/`; custom CSS provides the product-level system. The workflow builder remains local and bounded: it can edit visual draft steps but cannot change policy rules, evidence scopes, approval authority, or connector mappings. The phased adaptation is documented in [`../twenty-vendor-frontend-plan.md`](../twenty-vendor-frontend-plan.md).

## Consequences

- The prototype remains a local React/Vite application backed by sanitized mock data; it does not imply that workflow execution, uploads, authentication, or live integrations are complete.
- React 19 is required by the installed Dither Kit context API. Dither Kit's generated source and exact runtime dependencies remain local and reviewable.
- Dashboard charts communicate queue movement, route mix, and evidence readiness only. They are not reviewer-performance scores and do not move the PRD's reviewer-metrics stretch work into core scope.
- Future API wiring can replace local arrays while preserving the vendor, relationship, review, evidence, workflow, and audit boundaries.
- Any reuse of substantial Twenty source must preserve the source project's applicable AGPL-3.0 licensing and attribution requirements. This implementation adapts interaction and information-architecture patterns only; it does not retain Twenty source, Recoil state, GraphQL layers, workflow execution, or authenticated navigation.
- Review policy calculation, source precedence, evidence scope, and human approval remain governed by `docs/PRD.md` and `PLAN.md`, not by the UI reference.
