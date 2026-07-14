# Three-Day Implementation Plan

This is the execution plan for the requirements in [`docs/PRD.md`](docs/PRD.md). The schedule assumes intensive use of frontier coding agents with one human integration owner.

## Delivery rules

- Lock shared schemas and interfaces before parallel implementation begins.
- Use separate branches/worktrees for independent workstreams.
- Keep institutional source files and generated artifacts outside Git.
- Every behavior change includes tests and documentation.
- Models may draft and analyze but cannot establish policy or approve/write externally.
- Core medium-risk, human-review, and mock-write capabilities take priority over stretch work.
- Merge checkpoints occur Tuesday midday/EOD, Wednesday midday/EOD, and Thursday at 10:00 AM.

## Target workflow

```mermaid
flowchart LR
    I["Guided intake"] --> L["Approved-software lookup"]
    L --> R["Deterministic policy engine"]
    R --> S["Security specialist"]
    R --> A["Accessibility specialist"]
    S --> E["Evidence specialist"]
    A --> E
    E --> V["Official-vendor research"]
    V --> C["Citation and conflict checker"]
    C -->|"One repair"| C
    C --> P["Packet composer"]
    P --> H["Human review and editing"]
    H -->|"Approve"| W["Write-back preview and confirmation"]
    H -->|"Changes"| P
    H -->|"Reject"| X["Close without write-back"]
    W --> M["Simulated ServiceNow"]
```

## Shared contracts to lock first

- Case intake and validation schema.
- `SourceManifest`, `ApprovedSoftwareRecord`, `RecommendationClause`, `AssessmentAnswer`, `EvidenceRecord`, `WorkflowGraph`, and `PolicyRuleSet`.
- `ReviewGraphState` and structured specialist outputs.
- Packet and citation schemas.
- REST/OpenAPI contract from the PRD.
- `ServiceNowConnector` and mock data contract.
- Error codes, audit-event format, configuration precedence, and test fixtures.

The integration owner approves shared-contract changes after parallel work begins.

## Tuesday, July 14 — Contracts and local vertical slice

### Data and policy agent

- Create the Box source manifest and local ingestion contract.
- Parse and reconcile every approved-software workbook row and column.
- Generate lossless JSON/Parquet snapshots and normalized records.
- Extract recommendation clauses with stable IDs and source coordinates.
- Implement version-aware HECVAT normalization and extraction warnings.
- Transcribe both flowcharts and decision trees into source-linked versioned JSON.
- Create a conflict registry instead of resolving disputed thresholds.
- Implement deterministic policy evaluation and boundary tests.

### Workflow and LLM agent

- Define LangGraph state, node inputs/outputs, and checkpoint boundaries.
- Implement approved-software lookup and policy-tool adapters.
- Add parallel security and accessibility specialist nodes.
- Add evidence, scoped vendor-research, citation-checker, and packet-composer nodes.
- Enforce structured model outputs and one repair pass.
- Provide local deterministic/mock model behavior for tests.

### UI agent

Screen specs, states, API bindings, and design-system decisions: [`docs/UX-UI-PLAN.md`](docs/UX-UI-PLAN.md).

- Build guided intake with required-field and data-boundary messaging.
- Show approved-software candidates, match type, score, and source row.
- Add workflow progress and security/accessibility result views.
- Build editable medium-risk packet and citation panels.
- Build review decisions and simulated write-back preview/confirmation.

### AWS and integration agent

- Establish configurable CDK application boundaries without hard-coded account details.
- Add storage, API, model, and connector interfaces with local implementations.
- Implement `MockServiceNowConnector`, synthetic records, concurrency checks, attachments, and idempotency.
- Establish CI for documentation checks, lint, type checks, tests, and secret scanning.
- Define structured audit events and local logging.

### Tuesday gate

- PRD, plan, architecture decision, and agent instructions are current.
- Source files are checksummed, classified, and excluded from Git.
- Approved-software row/column counts reconcile.
- Recommendation clauses retain source coordinates.
- Both flowcharts have verified JSON representations.
- One low-risk and one medium-risk case run locally.
- Mock ServiceNow before/after preview works.
- CI runs the available documentation and code checks.

## Wednesday, July 15 — AWS integration and full workflow

### Environment decision gate

Before provisioning, record the approved AWS account/profile, region, owner, budget, expiration, data classification, retention, and teardown path. Inspect Bedrock access and pin available model/inference-profile IDs.

### Build and integration

- Deploy KMS-encrypted S3, DynamoDB, API Gateway, Cognito, CloudFront, Knowledge Base/S3 Vectors, Guardrails, AgentCore Runtime/Memory, and monitoring.
- Ingest and verify the approved source corpus.
- Keep campus policy and vendor evidence in distinct retrieval scopes.
- Connect the UI and API to the deployed LangGraph workflow.
- Implement durable human interrupt, edit, reject, approve, and resume.
- Complete low-risk summaries and editable medium-risk packets.
- Connect ServiceNow preview, update, work note, and attachment operations to the mock connector.
- Create at least 12 sanitized gold cases: four low, four medium, and four high/unknown.
- Add metrics for analysis latency, model/tool failures, citations, escalation, approvals, and writes.

### Wednesday gate

- Low, medium, and safe-escalation cases run end to end in AWS.
- Review can pause across a restart and resume from persisted state.
- Packet citations resolve to the correct file and source location.
- An approved decision can update and attach through the mock connector only.
- Stale and failed writes surface clearly and retry without duplication.
- Vendor evidence cannot cross case, vendor, or product boundaries.

## Thursday, July 16 — Hardening and demo

### Test and remediation

- Reconcile all spreadsheet counts, columns, source coordinates, and hashes.
- Test formulas, blanks, merged cells, malformed sheets, and supported HECVAT versions.
- Run risk-boundary cases, including user count, cost, data levels, AI, SSO, integrations, classroom/public use, GDPR, and PCI.
- Test missing inputs, stale evidence, vendor/product mismatches, unresolved rules, and malicious document instructions.
- Test reviewer authorization and every pause/resume/reject/approve transition.
- Test ServiceNow dry-run parity, stale version, duplicate submission, attachment failure, and 401/403/429/500 equivalents.
- Review logs for sensitive content and confirm retention, lifecycle, budget, and teardown configuration.
- Run final security scan, integration review, and health checks.

### Demo package

Prepare three deterministic demo cases:

1. An approved or clearly low-risk product with a traceable source match.
2. A medium-risk department/classroom product producing a complete editable TAAP/security packet.
3. A high-risk, incomplete, or contradictory case that safely escalates.

The demo must show citations, human edits, explicit approval, before/after simulated ServiceNow state, packet attachment, and the `Simulated ServiceNow` label.

### Stretch gate

If all core acceptance criteria pass by 10:00 AM, add in order:

1. Case-scoped vendor document-upload link.
2. Manually sent vendor-request email draft.
3. Read-only ServiceNow import.
4. Reviewer metrics dashboard.

## Agentic AI boundaries

Good uses of agents:

- Choose relevant read-only evidence tools.
- Run security and accessibility analysis in parallel.
- Extract and compare evidence using document-specific prompts.
- Search the configured official vendor domain.
- Detect contradictions and product/version mismatches.
- Draft packets from approved templates and clauses.
- Evaluate citation completeness and perform one bounded repair.

Deterministic or human-only operations:

- Policy thresholds and risk calculation.
- Confirmation of fuzzy or semantic software matches.
- Cross-document authority and source precedence.
- Final reviewer decision or TAAP signature.
- ServiceNow table/field selection and write execution.
- Conflict resolution when supplied sources disagree.

## Serac integration path

- Do not make Serac a demo dependency.
- Use its ServiceNow MCP schemas only to validate connector compatibility.
- Keep `MockServiceNowConnector` as the active implementation.
- If a sandbox becomes available later, place `@serac-labs/servicenow-mcp` in an isolated sidecar behind the application connector.
- Allowlist schema discovery, record reading, restricted configured updates, and attachment upload only.
- Keep secrets in AWS Secrets Manager and separate read/write identities.
- Never expose arbitrary CRUD, deletes, scripts, deployment, user administration, or Flow Designer tools to a model.

## Coding-agent skill routing

- `amazon-bedrock`: models, Knowledge Bases, AgentCore, Guardrails, and model discovery.
- `aws-cdk`: infrastructure, validation, configuration, and teardown.
- `aws-sdk-python-usage`: Python ingestion and LangGraph AWS integrations.
- `aws-sdk-js-v3-usage`: TypeScript API and Lambda integrations.
- `spreadsheets:Spreadsheets`: workbook inspection and reconciliation.
- `pdf:pdf` and `documents:documents`: flowcharts, policies, TAAPs, and vendor evidence.
- `frontend-design`: requester and reviewer interfaces.
- `browse`/`qa`: official-vendor browsing and end-to-end testing.
- `codex-security:security-scan` and `security-diff-scan`: uploads, authentication, tool boundaries, and write-back.
- `review` and `health`: integration and release gates.
- `github:github`: Serac and dependency inspection.
- `find-skills`: only when a workstream lacks an existing trusted capability.

## Definition of done

- All PRD acceptance criteria pass or have a documented blocker.
- Documentation describes the implementation and its limitations accurately.
- No institutional files, generated packets, secrets, or unrelated changes are committed.
- CI and the most relevant local tests pass.
- The diff has received security and integration review.
- AWS resources have an owner, budget, retention policy, and teardown procedure.
- The demo is reproducible from a documented sanitized scenario.
