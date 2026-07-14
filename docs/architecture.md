# AWS Architecture — Solutions Consulting Workflow

Layered architecture for the low-risk fast path (sprint scope). Source of truth for
component boundaries is [`CLIENT-BRIEF.md` §6](../CLIENT-BRIEF.md); this diagram visualizes it.

**Editable diagram:** [open in Excalidraw](https://excalidraw.com/#json=zmjRorP726yBCkiLjM01K,kTm6SA60hro3eplWvF-RUA)
· **Source elements:** [`architecture.excalidraw.json`](./architecture.excalidraw.json)

> The Excalidraw share link points to excalidraw.com's public store. Treat it as
> convenience only, not a private artifact — regenerate it if the diagram changes.

## Layers

### Frontend — static site (S3 + CloudFront / Amplify)
- **Intake Form (guided Q&A)** — plain-language questions; requester never needs to know what a HECVAT is.
- **Chair Review Queue** — recommendations with document trail and one-click Approve.

### API — API Gateway → Lambda (Python)
- `POST /requests` — triage a new submission
- `GET /requests` — the chair queue
- `POST /requests/{id}/approve` — the human gate (status transition `TRIAGED → APPROVED`)

### Logic & AI
- **Rules Engine (deterministic)** — implements the decision tree; the model cannot override the rubric.
- **Bedrock Converse — Claude** (temp 0, strict JSON schema, pydantic-validated, retry-once) explains and drafts rationale.
- **Nova** — configured fallback.

### Data & Knowledge
- **DynamoDB** — single table, GSI on `status`.
- **S3 Knowledge** — policy docs, decision tree, approved-software list, injected into context (vector RAG deferred).
- **Decision Tree YAML** — one structured artifact with per-node policy citations; both the rules engine and the LLM prompt derive from it, so there is no drift.

## Non-negotiables shown on the diagram
- **Human in the loop** — nothing finalizes without the chair's one-click approval.
- **Demo insurance** — seeded canned requests (one per risk tier) with cached model responses, so the demo survives a Bedrock or network failure.
