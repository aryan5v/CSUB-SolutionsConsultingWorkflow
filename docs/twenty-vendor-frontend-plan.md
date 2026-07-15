# Twenty-inspired vendor-management frontend plan

## Purpose

Adapt the strongest interaction and information-architecture patterns from
[Twenty](https://github.com/twentyhq/twenty) into the CSUB technology-review
workspace without importing Twenty's CRM domain, backend architecture, or
policy semantics.

This plan is based on Twenty commit
`58fcb3cb0ff21d0e4d1a5f00c85d5736de2e33af`, inspected in
`packages/twenty-front` and `packages/twenty-ui` on July 14, 2026.

The product remains a **vendor-management and human-review workspace**. It is
not a general CRM. `docs/PRD.md` and `PLAN.md` remain authoritative for policy,
evidence, approval, and write-back behavior.

## Design principles to carry forward

1. **Records first, workflow second.** Vendors, contacts, requests, evidence,
   and reviews should feel like durable records with relationships—not a set of
   disconnected demo pages.
2. **Fast scanning, deep inspection on demand.** Dense lists and saved views
   handle triage; side panels and full record pages handle detailed work.
3. **One object, several useful views.** Reviewers should be able to inspect the
   same vendor set through table, status board, and saved filters without
   duplicating data.
4. **Context stays attached.** Tasks, notes, evidence, review runs, decisions,
   and audit events should remain visibly linked to their vendor and request.
5. **Customization stops at trust boundaries.** Layout and display choices may
   be configurable. Policy thresholds, source precedence, approval authority,
   connector mappings, and evidence scopes may not be changed through UI
   customization.
6. **Adapt patterns, do not copy architecture.** Rebuild the useful behavior in
   the existing React/Vite prototype. Do not import Twenty's metadata engine,
   GraphQL stack, Jotai state graph, or broad CRM actions.

## Pattern-to-product mapping

| Twenty pattern | CSUB vendor-management adaptation | Priority | Representative Twenty source |
|---|---|---:|---|
| Grouped, collapsible, resizable navigation drawer | Group Dashboard/Inbox/My work/Chat, Records, Automation, Review system, and Administration. Preserve mobile full-screen navigation and keyboard focus. | P0 | `modules/ui/navigation/navigation-drawer/components/NavigationDrawer.tsx`; `NavigationDrawerSection.tsx`; `NavigationDrawerItem.tsx` |
| Metadata-driven record index | A purpose-built Vendor index with stable columns for vendor identity, official domain, internal owner, active reviews, evidence status, latest decision, and route. Reuse the pattern, not the metadata engine. | P0 | `modules/object-record/record-index/components/RecordIndexContainer.tsx`; `RecordIndexTableContainer.tsx` |
| View bar with saved views, filters, sorts, and options | Vendor views: **All vendors**, **Needs review**, **Active reviews**, **Evidence expiring**, **Safe escalations**, and **Unassigned owner**. Keep URL/state shareable when routing is added. | P1 | `modules/views/components/ViewBar.tsx`; `ViewBarDetails.tsx`; `view-picker/components/ViewPickerDropdown.tsx` |
| Table, board, and calendar layouts over one record set | Table is the default. Add a status board for review stage only after table interactions are stable. Calendar is limited to evidence expiry and review due dates; it is not a general CRM calendar. | P2 | `RecordIndexContainer.tsx`; `record-board`; `record-calendar` |
| Company record page with configurable tabs/widgets | Vendor record tabs: **Overview**, **Reviews**, **Evidence**, **People**, **Timeline**, **Tasks**, and **Notes**. Keep a fixed reviewed layout in the prototype instead of user-authored schemas. | P0 | `modules/page-layout/constants/DefaultCompanyRecordPageLayout.ts`; `PageLayoutRecordPageRenderer` |
| Relation sections with add/open/all behavior | Link vendors to internal owners, vendor contacts, review requests, review runs, evidence, tasks, and notes. Always show scope and provenance when the related object is evidence. | P0 | `record-detail-section/relation/components/RecordDetailRelationSection.tsx`; `RecordDetailRelationRecordsList.tsx` |
| Record side panel with navigation history | Open a vendor quick view from dashboard, queue, evidence, or contact records without losing list position. Use a full page for packet editing and consequential decisions. | P1 | `modules/side-panel/pages/record-page/components/SidePanelRecordPage.tsx`; `useOpenRecordInSidePanel.ts` |
| Timeline, tasks, notes, files, and email widgets | Vendor timeline combines audit-safe relationship events, review milestones, reviewer decisions, and simulated connector events. Keep tasks, notes, and files; replace CRM email sync with manually drafted contact messages. | P1 | `modules/activities`; `DefaultCompanyRecordPageLayout.ts` |
| Command menu and record-aware actions | Add keyboard navigation/search for vendors, requests, evidence, and pages. Permit read/open/create-draft actions only. Approval and write-back stay in explicit review checkpoints, never generic commands. | P2 | `modules/command-menu`; `modules/command-menu-item`; `SidePanelRouter.tsx` |
| Editable workflow diagram and step inspector | Keep the local graph builder, action library, draggable nodes, versions, and runs. Label policy evaluation as immutable and require explicit human nodes before simulated connector actions. | P0 | `workflow/workflow-diagram/components/WorkflowDiagramCanvasEditable.tsx`; `WorkflowDiagramStepNodeEditableContent.tsx`; `side-panel/pages/workflow` |
| Workflow run visualization and step logs | Show current node, inputs/outputs, citations, repair count, pauses, and failure state for each review run. Never expose document bodies or secrets in logs. | P1 | `WorkflowRunDiagramCanvas.tsx`; `workflow-run/observability` |
| Responsive dashboard widget grid | Keep a curated dashboard now. Later allow rearranging approved widgets only: queue attention, route mix, evidence readiness, stage throughput, and recent decisions. Dither Kit remains the chart renderer. | P2 | `page-layout/components/PageLayoutGridLayout.tsx`; `widgets/components/WidgetRenderer.tsx` |
| AI chat thread list and contextual chat | Preserve chat history, suggested prompts, current-scope chips, and a clear read-only boundary. Context must be case/vendor scoped and retrieved content remains untrusted. | P1 | `modules/ai/components/AiChatThreadsList.tsx`; `AiChatThreadListItem.tsx`; `AiChatEditorSection.tsx` |
| Sectioned settings experience | Settings groups: Workspace, Review controls, Members, Integrations, Notifications, Appearance. Protected controls are explanatory/read-only unless backed by approved deterministic configuration. | P1 | `modules/settings`; `useSettingsNavigationItems.tsx`; `twenty-ui` input primitives |
| Shared UI primitives and theme tokens | Continue the dense list/detail rhythm, restrained cards, compact tags, icon buttons, tabs, empty states, keyboard focus, and light/dark tokens. Keep the CSUB yellow/blue identity and minimal ASCII/Dither accents. | P0 | `packages/twenty-ui/src/{navigation,input,data-display,surfaces,theme}` |

## Target information architecture

```text
Dashboard
Workspace
  Inbox
  My work
  Active review
  Chat
Records
  Vendors
  Contacts
  Review requests
  Tasks
  Notes
Automation
  Workflows
  Workflow runs
  Workflow versions
Review system
  Evidence
  Audit
Administration
  Settings
  Documentation
```

Dashboard remains the landing page. Vendors are the primary durable business
record. Review requests and review runs are related operational records, not
substitutes for the vendor directory.

## Vendor record design

### Header

- Dither avatar, canonical vendor name, legal name, official domain.
- Internal reporting person and relationship owner.
- Current relationship status, highest open route, and evidence warning.
- Primary actions: open active review, draft owner/vendor message, add scoped
  evidence. No approval action appears at vendor level.

### Overview tab

- Identity and ownership fields.
- Products/aliases and approved-software matches with method disclosure.
- Open review summary and next human action.
- Evidence boundary callout.
- Small timeline of recent relationship and review events.

### Reviews tab

- Linked requests and runs.
- Stage, deterministic route, match method, owner, updated time.
- Saved filters for open, awaiting decision, evidence hold, and completed.

### Evidence tab

- Separate groups for campus policy references, case uploads, and official
  vendor evidence.
- Freshness, product/version match, source location, authority, and warnings.
- Never blend policy and vendor evidence into one undifferentiated list.

### People tab

- Internal owner first.
- Vendor contacts with role, email, primary/supporting status, and linked cases.
- Draft-message action only; no autonomous sending.

### Timeline, Tasks, and Notes tabs

- Timeline contains immutable review/audit milestones plus clearly distinct
  relationship activity.
- Tasks are human-owned follow-ups and cannot alter policy results.
- Notes are contextual and cannot become policy or cited findings without an
  explicit source record.

## Phased delivery

### Phase 0 — Preserve and stabilize current functionality

- Keep the polished dashboard, active review, evidence, audit, theme, and
  Dither integration.
- Restore all PR #8 routes and local interactions.
- Ensure navigation, light/dark mode, mobile behavior, search, and local state
  work across every surface.
- Run strict TypeScript, production build, repository checks, and an
  accessibility review.

### Phase 1 — Vendor record foundation

- Finish vendor and contact indices with search, filters, selection, and local
  create/edit flows.
- Build the fixed Vendor record tabs described above.
- Add linked requests, runs, evidence, tasks, and notes.
- Add quick-view side panel behavior while retaining a full detail route.

### Phase 2 — Saved operational views

- Add view picker and URL/state-backed filters/sorts.
- Ship the six predefined vendor views before allowing custom views.
- Add multi-select only for safe actions such as assign owner or create tasks.
- Do not add bulk approval, bulk policy edits, or bulk write-back.

### Phase 3 — Timeline and command surfaces

- Merge relationship and review events into a typed timeline.
- Add keyboard command/search for navigation, record opening, and draft
  creation.
- Add recent records and favorites.
- Keep consequential actions out of the command menu.

### Phase 4 — Workflow and observability refinement

- Keep the graph editor and action library.
- Add read-only run diagrams, node status, safe logs, citations, and pause
  reasons.
- Version workflow definitions and show draft versus active state.
- Enforce that graph edits cannot change policy rules or connector mappings.

### Phase 5 — Curated dashboard customization

- Allow rearranging a small allowlist of Dither-backed widgets.
- Persist layout separately from review data.
- Include reset-to-default and responsive layouts.
- Defer arbitrary iframe, code, rich-text, and user-authored data-source widgets.

## What not to borrow

- Opportunities, sales pipelines, campaigns, email/calendar synchronization,
  billing, marketplace, and generic CRM terminology.
- Twenty's dynamic object/field metadata authoring for this three-day
  prototype.
- Its GraphQL/Apollo/Jotai state architecture, optimistic cache layer, and SSE
  infrastructure.
- Arbitrary workflow HTTP, code, delete-record, or broad CRUD actions.
- User-configurable policy thresholds, risk routes, source precedence,
  ServiceNow field mappings, or evidence-scope rules.
- Generic bulk actions that could approve, reject, attach packets, or write to
  an external system.
- Dashboard metrics that rank reviewer performance; reviewer metrics remain a
  PRD stretch item.

## Acceptance criteria

- Dashboard remains the default page.
- Every PR #8 surface is reachable and retains its useful local interaction.
- A vendor can be found, selected, inspected, and related to contacts, reviews,
  and evidence without losing context.
- Non-exact software matches still require a recorded person.
- Policy routing remains visibly deterministic and source-linked.
- Evidence scopes remain distinct in lists, records, search, and chat.
- Packet edits invalidate stale decisions.
- Simulated ServiceNow requires an approved human decision and a second
  confirmation.
- All chart surfaces use Dither Kit and retain accessible text alternatives.
- Light/dark, keyboard focus, mobile navigation, type checks, production build,
  and repository checks pass.

## Licensing and attribution

Twenty is AGPL-3.0 licensed. Prefer adapting interaction patterns and writing
project-native components. If substantial Twenty source is copied, preserve
required attribution and obtain project-owner review of AGPL obligations before
shipping or distributing the result.
