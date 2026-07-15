# Reviewer web application

React/Vite TypeScript requester and reviewer workspace. It owns presentation,
browser-side state, accessibility behavior, and the typed client in `src/api.ts`.
It does not calculate risk tiers, embed AWS credentials, or call ServiceNow
directly.

## Local development

Start the deterministic backend from the repository root in one terminal:

```bash
PYTHONPATH=services/review-agent/src python3 -m review_agent.server --port 8787
```

Then install and start the frontend in another terminal:

```bash
npm --prefix apps/reviewer-web ci
npm --prefix apps/reviewer-web run dev
```

Vite serves the workspace at `http://127.0.0.1:5173` and proxies `/api` to the
local backend. Set `VITE_API_BASE_URL` only when intentionally targeting another
review API. Do not put credentials in frontend environment variables.

The connected core flow loads the review queue, creates sanitized cases, pauses
for fuzzy/semantic match confirmation, resumes deterministic analysis, displays
the packet, records reviewer edits and decisions, requests a simulated
ServiceNow preview, and performs the separately confirmed idempotent mock write.
The broader PR #8 record/workflow pages remain sanitized local prototype
surfaces. If the backend is unavailable, the shell visibly labels and retains
its offline demo fallback; it does not pretend an external write succeeded.

## Verification

```bash
npm --prefix apps/reviewer-web run test
npm --prefix apps/reviewer-web run check
npm --prefix apps/reviewer-web run build
```

Dependencies are installed from `package-lock.json`; these checks are composed
into root `make verify`.
