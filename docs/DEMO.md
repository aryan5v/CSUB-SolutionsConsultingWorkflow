# Vetted — Demo Plan and Script

Presentation: Friday morning. Recording: Thursday after the 16:00 code freeze.
Target length: **6–7 minutes** of demo inside a ~10-minute presentation slot.

## Setup (before recording)

1. Fresh clone on the demo machine; `make bootstrap && make verify` green.
2. Place the approved-software export at
   `data/raw/SNOW Export_approved_software_database.xlsx` (git-ignored). The
   local API logs `[catalog] loaded N approved-software rows` on startup.
3. Two terminals:

   ```bash
   # Terminal 1 — deterministic local API (add the webhook for live Slack pings)
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/…  \
   PYTHONPATH=services/review-agent/src python3 -m review_agent.server --port 8787

   # Terminal 2 — reviewer workspace with the local session bypass
   VITE_LOCAL_AUTH_BYPASS=true npm --prefix apps/reviewer-web run dev
   ```

4. Open three browser tabs: `http://127.0.0.1:5173/` (landing),
   `/app` (reviewer workspace), and the demo Slack channel.
5. Rehearse the full path twice from a fresh server restart before recording.
   If anything fails live, cut to the recorded backup — never improvise state.

## Demo beats and script

### 1. The problem (≈30s — slide, no app)

> "Before CSUB buys any software, state law requires a security and an
> accessibility review. Today that's a ServiceNow ticket, then weeks of
> email archaeology: chasing vendors for HECVATs, SOC 2 reports, and VPATs,
> reading them by hand, and a committee vote. Since procurement started
> enforcing the process, two-to-three-week reviews take two months. Vetted
> automates the routine work and keeps people on every decision."

### 2. Ticket in, review out (≈60s)

- Reviewer workspace → **Review requests** → "Start from a request ticket".
- Ticket `RITM0098200` is pre-filled. Click **Preview** — show the versioned
  field mapping (labeled *Simulated ServiceNow*). Click **Create review**.

> "A campus requester opens a ServiceNow ticket — that's unchanged. Vetted
> imports it: one action creates the case, the vendor record, the contact
> from the ticket, and a tracked, expiring intake link. Re-delivering the
> same ticket can't create a duplicate."

- Copy the generated intake link.

### 3. The vendor sees only what matters (≈90s)

- Open the intake link in a new tab (vendor's view).

> "This is the vendor's whole experience — no account, no forty-page form.
> They drop the evidence they already have, paste their trust-center URL,
> and finalize."

- Upload the sanitized sample files (a VPAT-named PDF, a SOC 2 excerpt).
- Point at the checklist: **"Tailored to this request"** note.

> "Here's the part the committee cares about: the school said at intake this
> is a public, classroom-facing tool with no Level 1 data — so the
> deterministic policy engine asks this vendor for accessibility conformance
> evidence, not the full battery. A Level 1 student-data system would see
> HECVAT and SOC 2 requirements appear automatically."

- Run analysis → matched files auto-cover requirements; answer the one
  remaining question; **Finalize** ("freezes this evidence version").
- Show "Save progress" first: "they can leave and come back — the link is
  their workspace, and weekly reminder emails nag them, not our staff."

### 4. Agents do the reading, rules do the routing (≈60s)

- Back in the reviewer workspace: queue → open the case.
- Walk the stepper: intake → catalog match (show the real approved-software
  catalog under **Vendors** — the actual export, not toy rows) → policy route
  with cited rules → parallel security + accessibility specialist findings →
  evidence tab (secure research provenance from the vendor's official domain)
  → composed packet with citations and the PDF.

> "Every claim in this packet resolves to a source: a policy rule with its
> version, a document the vendor uploaded, or a page fetched from the
> vendor's own domain. The AI drafts and compares — it cannot set the risk
> route, approve anything, or write anywhere."

### 5. People decide — and vendors can respond (≈75s)

- In the decision panel: write a vendor-visible comment ("The VPAT you
  provided is for version 2; please provide the current report."), add a next
  action, choose **Request changes**.
- Flip to the vendor tab and refresh: status shows **Changes requested** with
  the reviewer's comment and next steps — and the form is editable again with
  everything intact.

> "This is the loop that eats weeks today. The vendor's same link just
> reopened. They add the missing file and re-finalize — no new emails, no
> lost context."

- Re-finalize as the vendor; back as the reviewer, rerun the analysis
  ("creates a new immutable review version and invalidates my stale
  decision"), then **Approve**.

### 6. Close the loop (≈45s)

- Write-back preview: before/after diff, labeled **Simulated ServiceNow**.
- Second confirmation → commit. Show the approver, date, and packet
  attachment recorded.
- Switch to the Slack tab: the live notification for the completed review.

> "Approved-by-whom, when, and the evidence packet land back on the ticket —
> simulated here, contract-faithful for the day CSUB grants sandbox access.
> And the committee hears about it in Slack the second it happens."

### 7. Trust, and what's next (≈30s)

- Audit page: the end-to-end event trail for the case.
- Dashboard: every generated link and its live status.

> "Everything you watched is audited, versioned, and human-gated. Next:
> live ServiceNow write-back when the sandbox lands, deeper document
> content validation, and expiring-evidence re-review so approvals never
> silently go stale."

## Fallbacks

- **Backend hiccup:** restart terminal 1; state reseeds deterministically in
  seconds. The seeded cases (`TR-260714-014` LabArchives medium-risk,
  `TR-260714-018` low-risk, `TR-260714-011` safe escalation) are always
  available if the live-created case misbehaves.
- **Slack webhook fails:** the integration events log shows the truthful
  `simulated`/`failed` delivery — narrate the honesty story instead.
- **Catalog export missing:** the labeled synthetic sample set loads; say so.
- **Total failure:** play the recorded backup (record it Thursday evening).

## Q&A likely questions

- *"Is the ServiceNow integration real?"* — Simulated behind the same
  connector contract a live adapter implements; live intake/write-back is
  blocked only on CSUB sandbox credentials (issue #35).
- *"Can the AI approve something?"* — No. Deterministic rules route; models
  draft and compare with citations; only a signed-in reviewer can decide, and
  write-back needs a second confirmation.
- *"What about a vendor uploading garbage or malicious files?"* — Files are
  quarantined, size/type-capped, treated as untrusted, never executed, and
  content validation (PR #48) rejects stale or mismatched documents.
- *"Where does it run?"* — Fully serverless on campus AWS: CloudFront,
  API Gateway, Lambda, DynamoDB, S3/KMS, Cognito, SES, EventBridge; Bedrock
  models in live mode. Guarded CD deploys every main merge with canaries and
  automatic rollback.
