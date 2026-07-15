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
- `/intake#token=<opaque>` public, file-first vendor intake (`src/PublicIntake.tsx`).
  The route consumes the fragment before React mounts, removes it from visible
  browser history, keeps it in memory, and sends it only as an Authorization
  bearer value. The token is never placed in an API path. Intake supports
  multiple evidence files, an HTTPS trust-center URL, adaptive unresolved
  questions, save/resume, evidence coverage, and finalization. File metadata is
  registered first; bytes use a presigned upload when the API returns one. If it
  does not, the page explicitly says that only metadata was saved and the bytes
  stayed in the browser.
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
`/app`, intake at `/intake`) and proxies `/api` to the local backend. Live API
mode is the default. Set `VITE_REVIEW_DATA_MODE=fixture` only when you
intentionally want the clearly labeled in-browser fixture adapter. Set
`VITE_API_BASE_URL` only when intentionally targeting another review API. Do
not put credentials or invitation tokens in frontend environment variables.

The connected core flow loads the review queue, creates vendor, product,
contact, case, and tracked invitation records, pauses for fuzzy or semantic
match confirmation, resumes deterministic analysis, displays the packet,
records reviewer edits and decisions, requests a simulated ServiceNow preview,
and performs the separately confirmed idempotent mock write. Broader PR #8
record and workflow pages remain sanitized prototype surfaces. Live API
failures stay visible and never switch to fixture records automatically.

### Vendor bearer-route compatibility

The browser intentionally calls token-free vendor paths under
`/vendor/invites/current` and sends the opaque invitation in the
`Authorization: Bearer` header. The shared OpenAPI file and current local Python
server on this branch still define `/vendor/invites/{token}` path routes. The
backend must add the bearer-token route before live vendor intake works. Do not
work around that gap by putting the token back into a path, query string, log,
or browser storage. The current backend also returns evidence metadata without
a presigned upload; the UI labels that fallback and leaves file bytes in the
browser.

## Verification

```bash
npm --prefix apps/reviewer-web run test
npm --prefix apps/reviewer-web run check
npm --prefix apps/reviewer-web run build
```

Dependencies are installed from `package-lock.json`; these checks are composed
into root `make verify`.
