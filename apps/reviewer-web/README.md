# Reviewer web application

React/Vite TypeScript application that owns every browser surface: the public
landing page, the public vendor intake, and the authenticated reviewer
workspace. It owns presentation, browser-side state, accessibility behavior, and
the typed client in `src/api.ts`. It does not calculate risk tiers, embed AWS
credentials, or call ServiceNow directly.

## Routes

One Vite build serves all surfaces. `src/main.tsx` selects the surface from the
pathname without a router dependency:

- `/` public landing (`src/Landing.tsx`), the Paper conveyor marketing page.
- `/intake` public, file-first vendor intake (`src/PublicIntake.tsx`). Every
  path is simulated; the typed boundary in that file is a local placeholder for
  the backend intake contract owned by issue #19.
- `/app` and `/app/*` the authenticated reviewer workspace (`src/App.tsx`),
  themed with the Advent of Code dark terminal palette.

Any host serving the production build must fall back to `index.html` for unknown
paths. Vite's dev server does this by default; configure the CDN or static host
the same way for deploys.

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

Vite serves the app at `http://127.0.0.1:5173` (landing at `/`, workspace at
`/app`, intake at `/intake`) and proxies `/api` to the local backend. Set
`VITE_API_BASE_URL` only when intentionally targeting another review API. Do not
put credentials in frontend environment variables.

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
