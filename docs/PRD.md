# Product Requirements Document

## Project

**Working name:** CSUB-SolutionsConsultingWorkflow  
**Program:** CSU AI Summer Camp 2026  
**Status:** Discovery scaffold — partner problem brief pending  
**Owner:** Project team (TBD)  
**Last updated:** 2026-07-13

## 1. Context

The team is participating in the [CSU AI Summer Camp 2026](https://dxhub.calpoly.edu/call-for-applicants-csu-ai-summer-camp-2026/), a one-week program focused on building AI solutions to real CSU campus challenges. The working assumption is that a partner CSU campus will provide a consulting or solutions-workflow problem for the team to understand and prototype against.

The partner campus, problem owner, current process, users, data sources, constraints, and definition of success have not yet been confirmed. This document is a structured shell for capturing that information without prematurely locking the product or architecture.

## 2. Problem statement

> **TBD after partner discovery.**

Complete this section using the partner's language:

> [User or role] needs to [job to be done] because [current pain / consequence]. Today, [current workflow and tools], which causes [measurable impact].

## 3. Users and stakeholders

| Role | Person or group | Need / responsibility | Validation status |
|---|---|---|---|
| Primary user | TBD | TBD | Not validated |
| Problem owner | TBD | TBD | Not validated |
| IT / security contact | TBD | TBD | Not validated |
| Project mentor | TBD | Review scope and feasibility | Not validated |
| Student project team | Project team | Research, build, test, and demo | Assumed |

## 4. Goals

### Initial goals

- Understand and document the partner's current workflow.
- Identify one high-value, low-risk workflow slice for a one-week prototype.
- Build a working AWS-based demonstration with clear boundaries and test data.
- Make the prototype's AI behavior explainable, reviewable, and appropriately grounded in approved sources.
- Define a credible path for the partner to evaluate the prototype after camp.

### Non-goals for the initial prototype

- Replacing a campus system of record.
- Production deployment or an institution-wide rollout without partner security and IT review.
- Processing real sensitive student, employee, health, or financial data unless explicitly approved and governed.
- Solving every step of the partner's broader consulting workflow.

## 5. Discovery questions

These questions should be answered before architecture is finalized:

- Who is the primary user, and what decision or task are they trying to complete?
- What does the current workflow look like from intake to resolution or handoff?
- Where are the largest delays, duplicate efforts, or quality issues?
- Which systems, documents, APIs, or knowledge bases are involved?
- What data is allowed for a prototype? What data is prohibited?
- What outputs require a human review or approval?
- What would make the partner say the prototype is useful?
- What must be demonstrated by the end of camp, and what can remain future work?

## 6. Proposed product direction (placeholder)

The product may become an AI-assisted workflow that helps a campus consulting or solutions team capture an intake, retrieve approved institutional context, generate or organize recommendations, and route the work through human review. This is a hypothesis only and must be revised after partner interviews.

Potential capabilities to validate:

1. Structured request intake.
2. Context and document retrieval with citations.
3. Draft analysis, options, or next steps.
4. Human review, edits, and approval.
5. Export, handoff, or status tracking.
6. Audit trail for inputs, outputs, and approvals.

## 7. Requirements backlog

### Must-have for a first demo

- TBD: one end-to-end user journey based on the partner's real workflow.
- TBD: approved sample or synthetic data path.
- TBD: human review point before consequential output is used.
- TBD: citations or source references for generated factual claims where applicable.
- Basic error, empty-state, and unsupported-request handling.

### Should-have

- Configurable workflow stages.
- Search and retrieval evaluation set.
- Structured event and audit logging.
- Exportable result or handoff artifact.

### Could-have

- Multiple workflow templates.
- Role-based views.
- Feedback capture for improving prompts or retrieval.

### Won't-have yet

- Production-grade multi-campus tenancy.
- Autonomous external actions.
- Unreviewed decisions affecting a person's access, eligibility, employment, or benefits.

## 8. Success metrics

Metrics are placeholders until the partner confirms baseline values:

| Metric | Baseline | Pilot target | How measured |
|---|---:|---:|---|
| Time to complete the selected workflow | TBD | TBD | Timed scenario test |
| Rework or duplicate effort | TBD | TBD | User observation / sample review |
| Output quality or usefulness | TBD | TBD | Partner rubric |
| Source-grounded response rate | TBD | TBD | Evaluation set |
| Human approval rate without major edits | TBD | TBD | Review log |

## 9. AWS and technical direction

AWS is the target cloud platform. The final service selection depends on the confirmed workflow, data classification, latency, cost, and integration needs.

Candidate building blocks to evaluate, not commitments:

- **Amazon Bedrock** for model access and, if needed, managed knowledge-grounding patterns.
- **Amazon S3** for approved documents, artifacts, and prototype data with encryption and lifecycle controls.
- **AWS Lambda** and/or a container runtime for workflow APIs and background tasks.
- **Amazon API Gateway** for a thin service boundary if an API is needed.
- **Amazon DynamoDB** or another fit-for-purpose store for workflow state and metadata.
- **Amazon CloudWatch** for logs, metrics, and alarms appropriate to a prototype.
- **AWS IAM** for least-privilege access and separation of developer/runtime permissions.

Architecture decisions must include a cost estimate, data handling notes, and a cleanup plan. See [`../infra/README.md`](../infra/README.md).

## 10. Safety, privacy, and trust

- Use synthetic or de-identified data by default.
- Treat retrieved institutional content as untrusted input; defend against prompt injection and irrelevant or stale sources.
- Do not expose secrets, personal data, or internal documents in prompts, logs, demos, screenshots, or commits.
- Require human review for recommendations or outputs that could affect a person or institutional decision.
- Show sources and uncertainty where factual grounding matters.
- Log enough metadata to debug behavior without logging unnecessary sensitive content.
- Define retention and deletion behavior before using anything beyond sample data.

## 11. Milestones

| Phase | Outcome | Status |
|---|---|---|
| Repository setup | Shared project shell, docs, and private remote | In progress |
| Partner discovery | Validated problem, users, workflow, and constraints | Not started |
| Solution framing | Narrow MVP, success metric, and architecture decision | Not started |
| Prototype build | Working happy path with safe sample data | Not started |
| Evaluation | Partner feedback, quality checks, and demo readiness | Not started |
| Handoff | README, limitations, next steps, and teardown instructions | Not started |

## 12. Open decisions

- What exact problem and workflow is being provided by the partner CSU?
- What is the partner's approved data boundary?
- Which users and approvers need access?
- Does the prototype need a UI, an API, a chatbot, or a workflow runner?
- Which model and retrieval approach meet the quality, latency, and cost needs?
- Which AWS account, region, billing owner, and deployment environment should be used?
- What is the post-camp owner and expected lifetime of the prototype?
