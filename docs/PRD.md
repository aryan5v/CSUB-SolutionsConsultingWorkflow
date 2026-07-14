# Product Requirements Document

## Document control

| Field | Value |
|---|---|
| Product | CSUB Technology Review Agent |
| Repository | `aryan5v/CSUB-SolutionsConsultingWorkflow` |
| Program | CSU AI Summer Camp 2026 |
| Delivery window | Tuesday, July 14–Thursday, July 16, 2026 |
| Status | Approved prototype specification |
| Primary users | CSUB technology-review requesters and reviewers |
| Data boundary | Supplied Box dataset plus sanitized case uploads |
| System of record | ServiceNow-compatible mock for the prototype |
| Last updated | July 14, 2026 |

## 1. Product summary

CSUB staff currently evaluate proposed software using an approved-software export, risk-review recommendations, process flowcharts, decision trees, TAAP material, and vendor evidence. The prototype will bring those inputs into one review workspace and use deterministic policy evaluation plus bounded AI specialists to reduce document handling and draft review material.

The product will:

- Check whether software is already present in the approved-software export.
- Calculate security and accessibility routing with source-linked deterministic rules.
- Produce a low-risk recommendation or an editable medium-risk TAAP/security packet.
- Escalate high-risk, contradictory, unsupported, and incomplete cases.
- Ground factual findings in supplied institutional material, case evidence, or captured official-vendor sources.
- Require a reviewer decision before any consequential action.
- Demonstrate contract-faithful, clearly labeled simulated ServiceNow write-back.

The supplied discovery transcript, challenge overview, Box files, and the decisions recorded in this PRD are the planning basis. Any statement not verified in those materials remains labeled as an assumption or open question.

### Known prototype source inventory

The ingestion manifest must cover the complete supplied Box folder, including:

- `SNOW Export_approved_software_database.xlsx`.
- `Risk Review Recommendations.xlsx`.
- `Risk Review Process.pdf`.
- `Solution Acquisition Process.pdf`.
- Both supplied decision-tree documents.
- TAAP and approval templates, data-classification guidance, and the signed TAAP example.
- Example HECVAT, SOC 2, PCI, penetration-test, VPAT/ACR, email, and completed-review material.

Filenames may be normalized for display, but each manifest entry must retain the original Box identifier, filename, version, and hash. The source files themselves must not be committed to Git.

## 2. Users and primary journey

### Requester

Provides the product, vendor, intended users, use case, platform, data classification, integrations, estimated cost, accessibility context, official vendor domain, and available evidence.

### Reviewer

Confirms possible approved-software matches, examines policy results and citations, edits the draft packet, requests missing information, and explicitly approves or rejects the proposed outcome and write-back.

### Administrator/integration owner

Configures policy versions, approved ServiceNow tables and fields, AWS environment settings, retention, and access. Models and requesters cannot change this configuration.

### End-to-end journey

1. A requester creates a case and uploads sanitized evidence.
2. The system validates required fields and looks for approved-software candidates.
3. A reviewer confirms any non-exact match.
4. A deterministic policy engine calculates the risk route and required documents.
5. Security and accessibility specialists analyze the case in parallel.
6. Evidence and official-vendor research specialists fill supported gaps.
7. A citation checker rejects unsupported or cross-vendor findings and permits one repair pass.
8. The system drafts the appropriate low- or medium-risk packet.
9. The reviewer edits and approves, rejects, or requests more information.
10. An approved decision produces a ServiceNow update preview and, after a second explicit confirmation, writes to the mock connector and attaches the packet.

## 3. Scope and priorities

### Must deliver by Thursday

- Guided intake and evidence upload metadata.
- Lossless approved-software workbook ingestion and searchable normalized records.
- Risk-review recommendation clause extraction with source coordinates.
- Versioned flowchart and decision-tree rule representation.
- Exact, alias, vendor/product, fuzzy, and semantic approved-software lookup with match-method disclosure.
- Deterministic risk and routing result with source citations.
- Parallel security and accessibility analysis.
- Vendor/product-scoped evidence retrieval.
- Low-risk summary and full editable medium-risk TAAP/security packet.
- Citation, conflict, missing-evidence, and prompt-injection checks.
- Human pause, edit, resume, reject, and approve workflow.
- ServiceNow-compatible preview, mock update, work note, and packet attachment.
- Audit trail covering workflow versions, reviewer decisions, and write actions.
- Three polished demo scenarios: low/approved, medium, and safe escalation.

### Conditional stretch work

Only begin these items when core acceptance gates are green by Thursday at 10:00 AM, in this order:

1. Vendor document-upload link scoped to a case.
2. Draft vendor evidence-request email that remains manually sent.
3. Read-only ServiceNow ticket import.
4. Reviewer metrics dashboard.

### Non-goals

- Production deployment or institution-wide rollout.
- Treating the prototype as the official system of record.
- Unreviewed approvals, signatures, risk-tier changes, or external writes.
- Live ServiceNow integration during the three-day build.
- Autonomous web browsing outside configured official vendor and standards domains.
- Processing real sensitive student, employee, health, payment, or credential data.
- Allowing an LLM to establish campus policy or invent recommendation language.

## 4. Functional requirements

### FR-1: Case intake

- Validate product, vendor, requester, use case, expected users, platform, data classification, cost, integrations, accessibility context, and official domain.
- Store uploaded-document metadata separately from extracted content.
- Identify missing required inputs before analysis.
- Treat uploaded and retrieved content as untrusted.

### FR-2: Approved-software lookup

- Preserve the original workbook and every original row and column.
- Normalize canonical product name, aliases, short name, vendor, platform, audience, department, assignment, support, location, and licensing metadata.
- Match in this order: exact name, alias/short name, vendor plus product, fuzzy candidates, semantic candidates.
- Return match method, score, record identifier, and source row.
- Require reviewer confirmation for fuzzy or semantic candidates.

### FR-3: Deterministic policy evaluation

- Execute only versioned rules traced to a flowchart, policy, decision tree, or confirmed override.
- Return risk route, triggers, required evidence, recommendation-clause identifiers, conflicts, and citations.
- Escalate missing inputs, unresolved thresholds, contradictory rules, high-risk outcomes, and unknown combinations.
- Do not allow model output to alter the calculated result.

Source precedence is:

1. Partner-confirmed override.
2. Current formal process or CSU policy.
3. Decision-tree draft.
4. Discovery-call statement.
5. Model inference, which may explain but cannot establish a rule.

### FR-4: Evidence analysis

- Normalize HECVAT question/answer data with workbook version, source sheet/cell, comments, and evidence references.
- Preserve formulas, blanks, merged cells, and unsupported layouts as warnings.
- Identify evidence type, vendor, product, dates, version, authority, and source hash for SOC 2, PCI, penetration-test, VPAT/ACR, email, TAAP, and completed-review examples.
- Prevent retrieval across case, vendor, or product boundaries.
- Flag expired, mismatched, incomplete, or contradictory evidence.

### FR-5: Agent-assisted analysis

- Run security and accessibility specialists in parallel after deterministic routing.
- Permit evidence and vendor-research specialists to choose only narrow, allowlisted read tools.
- Restrict vendor research to the supplied official domain and recognized standards sites.
- Produce schema-validated outputs with citations and uncertainty.
- Run one citation/completeness repair pass at most.

LLMs may extract, summarize, compare, research, explain, and draft. They may not establish rules, modify risk tiers, confirm fuzzy matches, sign a TAAP, approve a request, select ServiceNow fields, or perform write-back.

### FR-6: Packet generation and review

- Produce a concise low-risk recommendation when policy permits.
- Produce an editable medium-risk packet containing TAAP fields, security summary, accessibility findings, evidence inventory, gaps, mitigations, owners/placeholders, approved recommendation clauses, citations, and committee routing.
- Present conflicts and unsupported claims before approval.
- Persist reviewer edits, comments, identity, decision, and decision version.
- Support request-more-information, reject, and approve actions.

### FR-7: ServiceNow-compatible write-back

- Display a before/after dry-run preview by default.
- Require a recorded approved `HumanDecision` and a second `Approve and write back` confirmation.
- Use configured table, record, and field mappings; never model-generated mappings.
- Compare the expected record version before updating.
- Use `case_id + decision_version` as the idempotency key.
- Attach the generated packet once and verify the result.
- Record reviewer, values, packet hash, timestamps, and connector response.
- Label every prototype write as simulated.

## 5. Data and system requirements

### Source storage

Original institutional files remain outside Git in KMS-encrypted S3:

```text
s3://<bucket>/raw/<box-file-id>/<sha256>/<filename>
s3://<bucket>/normalized/<dataset>/<version>/
s3://<bucket>/case-evidence/<case-id>/<document-id>/
s3://<bucket>/generated/<case-id>/<packet-version>/
```

Each `SourceManifest` records source ID, filename, MIME type, hash, version, ingestion time, category, vendor/product, relevant dates, authority, allowed use, retention, extraction state, warnings, and source locations.

### Storage by data shape

- S3: originals, lossless JSON/Parquet snapshots, evidence, and generated packets.
- DynamoDB: cases, normalized software, recommendation clauses, policy versions, decisions, audit events, and mock ServiceNow state.
- S3 Vectors/Bedrock Knowledge Bases: embeddings for policy documents and scoped evidence retrieval.
- AgentCore Memory: short-term LangGraph checkpoints with a seven-day TTL; no long-term user-profile memory.

Excel is not treated as undifferentiated vector content. Structured lookup uses normalized data first; semantic search is a disclosed fallback.

### Public application interface

- `POST /cases`
- `POST /cases/{id}/documents`
- `POST /cases/{id}/analyze`
- `GET /cases/{id}/stream`
- `POST /cases/{id}/review`
- `POST /cases/{id}/servicenow/preview`
- `POST /cases/{id}/servicenow/commit`
- `GET /cases/{id}/packet`
- `GET /review-queue`

### Required domain contracts

`ReviewGraphState` contains case input, document IDs, software candidates and confirmation, policy result/version, specialist results, evidence gaps, citations, conflicts, draft packet, human edits/decision, connector target/version, write preview/result, and idempotency key.

`ServiceNowConnector` exposes:

- `inspect_schema(table)`
- `get_request(external_id)`
- `preview_update(case_id, decision_version)`
- `update_request(approved_fields, expected_version)`
- `attach_packet(record_id, packet, sha256)`
- `verify_writeback(idempotency_key)`

The prototype implements `MockServiceNowConnector`. A future restricted Serac MCP adapter must implement the same contract.

## 6. Technical architecture

- React/Vite TypeScript UI hosted on S3 and CloudFront.
- Cognito requester and reviewer roles.
- API Gateway and small TypeScript Lambda APIs.
- Python LangGraph agent on Amazon Bedrock AgentCore Runtime.
- Latest region-approved Claude Sonnet model for reasoning/drafting; Nova Pro fallback.
- Nova 2 Lite for extraction/normalization and Titan Text Embeddings V2 for embeddings.
- DynamoDB, KMS-encrypted S3, S3 Vectors, and Bedrock Knowledge Bases.
- AgentCore Browser with domain restrictions.
- Bedrock Guardrails plus application-level injection, citation, and schema validation.
- CloudWatch structured logs/metrics and CloudTrail write auditing.

Exact model and inference-profile IDs are discovered in the approved AWS account and pinned in environment configuration. Provider-specific calls remain behind testable interfaces.

Serac is not a runtime dependency for the demo. Its ServiceNow MCP schemas may guide compatibility. If a sandbox later becomes available, only a sandboxed sidecar with allowlisted schema-read, record-read, restricted-update, and attachment operations may be introduced. Broad CRUD, delete, script, deployment, user-administration, and Flow Designer tools remain unavailable to the model.

## 7. Security, privacy, and operational requirements

- Use sanitized, synthetic, or explicitly approved sample data only.
- Never commit Box files, generated packets, credentials, tokens, account IDs, or `.env` files.
- Encrypt data at rest and in transit and use least-privilege roles.
- Keep runtime read and write permissions separate.
- Store connector credentials in Secrets Manager.
- Reject or isolate prompt instructions found in retrieved documents.
- Log identifiers, versions, decisions, hashes, latency, and error metadata without unnecessary document bodies or sensitive content.
- Configure retention, lifecycle deletion, budgets, and teardown before provisioning.
- Keep AWS account, profile, region, resource names, and model IDs configurable.

## 8. Success metrics and acceptance criteria

| Measure | Prototype target |
|---|---:|
| Approved-software row/column reconciliation | 100% |
| Executable rules with verified source | 100% |
| Generated factual claims with citations | 100% |
| High/unknown/incomplete cases incorrectly fast-pathed | 0 |
| Cross-vendor or cross-case evidence leakage | 0 |
| Writes without an approved human decision | 0 |
| Duplicate notes or attachments on retry | 0 |
| Automated case analysis time | Under 5 minutes, excluding review |
| Sanitized gold cases | At least 12: 4 low, 4 medium, 4 high/unknown |

Acceptance also requires:

- Visible distinction between exact, alias, fuzzy, and semantic matches.
- Source coordinates for every recommendation clause and machine-executable rule.
- Full medium-risk packet contents and editable reviewer workflow.
- Safe escalation for conflicts, missing evidence, stale documents, and unsupported claims.
- Correct pause, restart, resume, edit, reject, retry, and checkpoint-expiry behavior.
- Authorization and adversarial tests for uploads, retrieved pages, and write-back.
- A visible `Simulated ServiceNow` label in the demo and generated audit entries.

## 9. Delivery milestones

| Date | Outcome | Completion gate |
|---|---|---|
| Tue, Jul 14 | Contracts, source pipeline, deterministic rules, local vertical slice | One low and one medium flow; reconciled workbooks; flowchart JSON; mock write preview; CI |
| Wed, Jul 15 | AWS deployment and integrated human-review workflow | Low, medium, escalation cases in AWS; pause/resume; packet; mock write and attachment |
| Thu, Jul 16 | Hardening, evaluation, and demo | Acceptance suite, three polished cases, audit/retention/teardown review, demo-ready system |

Detailed workstreams, gates, and agent ownership are defined in [`../PLAN.md`](../PLAN.md).

## 10. Assumptions and open questions

### Assumptions

- The supplied Box folder is the complete institutional dataset for the prototype.
- No live ServiceNow credentials or additional institutional data will arrive during the build.
- Medium-risk output is a draft for human editing, not an approval or signed TAAP.
- ServiceNow write-back is simulated but contract-faithful.
- Serac is a future integration option, not a Thursday dependency.
- AWS deployment uses a team-approved account and region that will be recorded before provisioning.

### Open questions

- Which AWS account, profile, region, billing owner, budget, and expiration date are approved?
- Which Box artifacts are authoritative versus examples or drafts?
- What are the partner-confirmed values for conflicting insurance, cost, user-count, AI, and medium-control thresholds?
- Who is authorized to act as the prototype reviewer?
- What retention period should apply to raw sources, case evidence, checkpoints, and generated packets?
- Who owns evaluation and teardown after Thursday?

Unanswered questions must be represented in configuration or the conflict registry and must not be silently resolved by an agent.
