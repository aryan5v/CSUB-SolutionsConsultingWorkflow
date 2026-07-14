# Client Brief v2 — Solutions Consulting Workflow Automation
**Sponsor:** Chris Diniz, CSUB ITS · **Team:** DxHub AI Camp · **Status:** Post-discovery, sprint scope locked
**Supersedes:** challenge_overview.md (v1). Ground truth: discovery call transcript (Chris Diniz, CSUB) + challenge overview. Pending input: links to CSUB's official policies and documented decision tree — will supersede the transcript-derived tree below once reconciled.

---

## 1. Problem Statement

CSUB requires every technology purchase — software, hardware, SaaS — to pass security, accessibility, and contract/insurance review by the Solutions Consulting committee before Procurement will process it. This policy existed for years but was enforced on the honor system; most requesters skipped it. The new Procure-to-Pay (P2P) workflow now hard-gates all tech purchases through Solutions Consulting: no review, no PO.

The result: previously invisible purchase volume slammed into a manual, tribal-knowledge process sized for a trickle. Reviews that took 2–3 weeks now take ~2 months. Most incoming requests are low-risk and routine, yet each consumes committee time. Requesters don't understand the process or its vocabulary (HECVAT, SOC 2, Level 1 data, insurance thresholds) and depend on hand-holding from the committee lead.

**Sponsor's success criterion (verbatim intent):** offload the low-risk items — auto-vet them, present the chair a list of "these are okay" with a recommendation and document trail, chair approves with one click. **Human in the loop before anything finalizes, non-negotiable.**

## 2. Current Workflow (Before)

1. Requester submits via ServiceNow, often confused about requirements
2. Committee lead answers vocabulary/process questions by email, repeatedly
3. Requester chases vendor for documentation (HECVAT, SOC 2, VPAT); weeks pass
4. Committee members validate documents by hand; ISO assesses controls
5. Committee votes weekly; queue backlog compounds
6. Cycle time: was 2–3 weeks → now ~2 months under P2P volume

**Root causes:** decision tree lives in reviewers' heads; requesters can't self-serve; every request gets the same manual treatment regardless of risk; document chasing is serial and human-driven.

## 3. The Decision Tree (captured from discovery call)

Previously listed as a "known gap — undocumented tribal knowledge." Chris walked the full tree verbally on the discovery call; it is now captured below. **To be reconciled against CSUB's official documented tree when links are provided — the official version wins, and any drift between documented and practiced process gets flagged to the sponsor.**

A request's overall risk = the higher of its two track ratings.

### Accessibility track
| Risk | Trigger | Required action |
|---|---|---|
| Low | <10 users AND not used in a class | Document accessibility concerns; requester acknowledges; done |
| Medium | Used in a classroom | TAAP form documenting gaps + mitigation (e.g., screen-reader assistant provided); signed by requester's supervisor + accessibility officer |
| High | Public-facing OR campus-wide | All of the above + vendor accessibility roadmap with remediation timelines |

### Security track
| Risk | Trigger | Required action |
|---|---|---|
| Low | Single user, no PII / Level 1 data | Advisory only ("be careful, you're at risk") |
| Medium | Department-level use, Level 2 data | Verify liability insurance + basic security requirements. **EU hosting → GDPR flag → hard stop for Procurement** |
| High | Level 1 data OR most-of-campus OR payment cards | Insurance threshold verification + HECVAT; PCI certification if credit cards involved |

**Sponsor's automation appetite:** automate low fully (with human sign-off), medium ideally, leave high-risk to humans.

## 4. Solution Scope (Sprint — 3 days)

**In scope — the low-risk fast path, end to end:**
1. **Guided intake** — plain-language questions (user count, classroom use, public-facing, data types with Level 1/2 explained in human terms, hosting location, payment cards). Requesters never need to know what a HECVAT is; the system tells them what's required and why.
2. **AI triage** — intake answers → risk classification per track + overall, triggered rules with policy citations, required-documents list, recommendation, rationale. Deterministic rules engine implements the tree; LLM explains, handles ambiguity, and drafts the rationale. The model cannot override the rubric.
3. **Chair review queue** — recommendations with full document trail and one-click Approve. The AI recommends; the human decides. This gate is the centerpiece of the demo.

**Stretch (only if core is solid by day 2):** agentic vendor-document verification — search public sources for the vendor's VPAT / SOC 2 / HECVAT (many are published; HECVATs via the Community Broker Index), extract claims, attach with citations. Demo against pre-verified vendors with cached results; live mode as bonus.

**Out of scope — roadmap slide:**
- Vendor-initiated document submission against a ticket
- ServiceNow write-back (sponsor confirmed deferred)
- Requester email-drafting assistant for vendor doc requests
- Medium-risk TAAP auto-drafting
- Auth/SSO hardening (Cognito), production IAM posture

## 5. Target Workflow (After)

Requester answers plain-language intake → system classifies risk against the documented tree → low-risk requests arrive at the chair pre-vetted with recommendation, citations, and document trail → chair approves in one click → requester gets a fast, predictable answer. Committee time shifts to genuine risk (medium/high), not routine processing.

## 6. Architecture (AWS, camp account)

- **Frontend:** static (S3 + CloudFront or Amplify) — intake form + chair queue
- **API:** API Gateway → Lambda (Python): `POST /requests` (triage), `GET /requests` (queue), `POST /requests/{id}/approve` (human gate = status transition TRIAGED → APPROVED)
- **AI:** Bedrock `converse` (Claude, temp 0, strict JSON schema, pydantic-validated, retry-once); Nova fallback configured
- **Knowledge:** policy docs + decision tree + approved-software list in S3, injected into context (corpus is small; vector RAG deliberately deferred — Bedrock Knowledge Bases on roadmap when corpus scales to thousands of vendor docs)
- **State:** DynamoDB single table, GSI on status
- **Source-of-truth discipline:** decision tree maintained as one structured YAML/JSON artifact with per-node policy citations; both the rules engine and the LLM prompt derive from it — no drift
- **Demo insurance:** seeded canned requests (one per risk tier) with cached model responses; demo survives Bedrock or network failure

## 7. Success Metrics

- Cycle time for low-risk requests: weeks → days (target: same-day triage, chair approval at next touch)
- Share of requests taking the fast path (sponsor estimates most volume is low-risk)
- Reviewer hours per low-risk request → near zero (one click)
- Incomplete-submission rate ↓ (guided intake asks for the right things up front)
- Audit completeness ↑ (every recommendation carries citations + document trail)

## 8. Risks & Honest Caveats

- Transcript-derived tree may differ from official policy — reconciliation pending; official docs win
- Exact thresholds (insurance dollar amounts, Level 1/2 definitions) need the official docs before production use
- Live web verification of vendor docs is inherently flaky — hence cached demo path
- Trust is earned incrementally: system launches as recommendation-only; automation expands as the committee's confidence grows (sponsor's stated posture)

## 9. Open Items

- [ ] Receive + ingest CSUB policy links and official decision tree; diff against §3; flag drift to Chris
- [ ] Confirm Bedrock model access (Claude) on camp account — check today
- [ ] Sample vendor docs (HECVAT/SOC 2/VPAT) and TAAP form from sponsor for stretch goal
- [ ] Confirm 2–3 real vendors for cached verification demo