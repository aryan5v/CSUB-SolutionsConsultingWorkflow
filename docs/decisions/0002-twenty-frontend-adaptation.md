# ADR 0002: Adapt Twenty Frontend Workspace Patterns

## Status

Accepted for the UI shell, workspace navigation, and workflow-builder pass.

## Context

The CSUB Technology Review Agent needs a reviewer workspace that can show record collections, relationships, workflow state, and supporting documents without becoming a generic analytics dashboard. The approved PRD calls for review runs, vendor/product evidence boundaries, human review, audit history, and a simulated ServiceNow write-back.

The frontend reference is [twentyhq/twenty](https://github.com/twentyhq/twenty), inspected at commit `58fcb3cb0ff21d0e4d1a5f00c85d5736de2e33af`. Its `twenty-front` and `twenty-ui` packages provide the relevant record-workspace patterns: navigation drawer, searchable record tables, composable card surfaces, dense relationship lists, and side detail panels.

## Decision

Adapt the frontend patterns into this lightweight React/Vite prototype rather than importing the complete Twenty monorepo. The application keeps a small dependency surface and local mock data, but now provides:

- Overview and review-run records in one operating view.
- Vendor records with an internal reporting person and attached vendor contacts.
- Contact records with staff-to-vendor relationship mapping.
- A scoped evidence library with a document viewer and source metadata.
- Audit-trail records for policy, reviewer, evidence, and connector events.
- A Twenty-like workspace shell with Home, Inbox, My work, Vendors, Contacts, Review requests, Tasks, Notes, Dashboards, nested Workflows, Settings, Documentation, and a reviewer Chat surface.
- Dashboard, workflow definitions/runs/versions, human task, note, and administration pages adapted to the CSUB review domain.
- A workflow canvas ported from Twenty's `WorkflowDiagramCanvasBase`, `WorkflowDiagramStepNodeEditableContent`, `WorkflowDiagramConnector`, and `SidePanelWorkflowSelectAction` composition, implemented with Twenty's `@xyflow/react` dependency and CSUB-specific local node data/actions.

`src/components/twenty/RecordSurface.tsx` contains the small adapted surface contract. The supplied CSUB theme tokens are authoritative for this prototype; Twenty's runtime theme and backend/client layers are not imported.

## Consequences

- The prototype remains buildable with the repository's small Vite toolchain.
- These new pages are local prototype surfaces backed by sanitized mock data; they do not imply that backend workflow execution, live dashboards, or live settings integrations are complete.
- Future API wiring can replace the local arrays behind the same record surfaces.
- Any reuse of substantial Twenty source must preserve the source project's applicable AGPL-3.0 licensing and attribution requirements. The current port is limited to UI composition and interaction patterns; Twenty's Recoil state, GraphQL data layer, backend workflow execution, and authenticated side-panel navigation are intentionally not imported.
- Review policy calculation, source precedence, and human approval remain governed by `docs/PRD.md` and `PLAN.md`, not by the UI reference.
