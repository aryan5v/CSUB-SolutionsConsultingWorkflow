# Review agent

Python workspace for the CSUB Technology Review Agent: ingestion, deterministic
policy, bounded LLM orchestration, mock ServiceNow write-back, and structured
audit. Deterministic policy, orchestration, provider adapters, and document
extraction live in separate modules, and every model/tool/AWS boundary is a
small interface with a local fake.

## Local vertical slice and browser API

The slice runs on the **standard library only** with **no live AWS** and no
institutional data. Deterministic fakes stand in for Bedrock, S3, and
ServiceNow so the whole flow is reproducible in CI. `review_agent.api` composes
the same workflow and connector behind the public application routes;
`review_agent.server` exposes them to `apps/reviewer-web` for local development.
See [ADR 0003](../../docs/decisions/0003-review-agent-local-slice.md) for the
workflow rationale and
[ADR 0005](../../docs/decisions/0005-local-review-api.md) for the local adapter.

```bash
# From this workspace:
make test                                  # deterministic unit/API tests (105)
PYTHONPATH=src python3 -m review_agent.demo
PYTHONPATH=src python3 -m review_agent.server --port 8787
PYTHONPATH=src python3 -m review_agent.ingestion.software_workbook --dry-run /path/to/export.xlsx
```

The CLI demo runs a low-risk, a medium-risk, and a safe-escalation case, then a
simulated ServiceNow before/after preview and an idempotent commit with a packet
attachment. The HTTP adapter additionally provides guided intake, queue/state,
human match confirmation, packet edits and decisions, preview concurrency, and
second-confirmation commit behavior for the browser. Every write remains
labeled `Simulated ServiceNow`.

## Layout

```text
src/review_agent/
  contracts/       Dataclasses mirroring packages/contracts JSON Schemas
  ingestion/       Source manifest + lossless workbook normalization (FR-2)
  institutional/   Dev-time source classification, scope separation, untrusted scan
  policy/          Deterministic engine, versioned rules, conflict registry (FR-3)
  lookup/          Approved-software lookup with disclosed match method (FR-2)
  specialists/     Parallel security/accessibility nodes + citation checker (FR-5)
  research/        Official-domain vendor research: SSRF/DNS/redirect + provenance (FR-4/5)
  packet/          Low- and medium-risk packet composition (FR-6)
  orchestration/   Workflow runner, node functions, checkpointer (sec 5)
  vendor/          Workspace-scoped repository interfaces, invite/intake service, immutable runs
  profiles/        Cited draft/fixture-test/activate/rollback profile lifecycle
  adapters/        model (Bedrock), storage (S3), servicenow (mock) interfaces + fakes
  audit/           Structured audit log that rejects sensitive content (sec 7)
  config.py        Env-driven config (region, model IDs) with no secrets
  samples.py       Synthetic sanitized fixtures for the slice and tests
  demo.py          Runnable CLI vertical slice
  api.py           In-memory application API over the existing workflow
  server.py        Standard-library HTTP/SSE adapter for local browser use
tests/             Deterministic unit, workflow, connector, and HTTP API tests
```

## Institutional source normalization (dev-time slice)

`review_agent.institutional` classifies each supplied Box source and keeps the
institutional policy corpus separate from case and vendor evidence. It answers
three questions per source, using only the file's path and name:

- Which review category it belongs to.
- Whether it is institutional policy, case/vendor evidence, or excluded.
- Whether it may be activated into the working policy set.

The signed TAAP and everything under `Example Documents/` are excluded from the
institutional policy corpus; the example documents are treated as case/vendor
evidence in a separate retrieval scope. Both `SC decision tree` files are marked
draft and unconfirmed, so `assert_activatable` refuses to activate them until a
human confirms them (FR-3 places a decision-tree draft below any formal
process). A file with no matching rule is left unresolved and flagged for human
classification rather than guessed at.

Document text is untrusted. `scan_untrusted_text` reports two things and acts on
neither: URLs that carry tracking or AI-provenance markers (for example a
`chatgpt.com` link or a `utm_source=chatgpt.com` parameter, which is present in
one supplied workbook), and instruction-like phrases that resemble prompt
injection. Findings become extraction warnings so a reviewer can judge them.

The core API reads no bytes and stores no document body. A content hash is
optional and, when supplied, is runtime-only, so no source content or hash tied
to downloadable contents is committed. A developer aid walks a local corpus
directory and prints a metadata-only summary; it persists nothing by default:

```bash
# Corpus lives outside Git; nothing below is committed.
PYTHONPATH=src python3 -m review_agent.institutional "/path/to/Solutions Consulting"
```

See [ADR 0007](../../docs/decisions/0007-institutional-source-normalization.md).

## Official-domain vendor research (SSRF and provenance)

`review_agent.research` fetches public evidence only from the vendor's confirmed
official host (and configured standards authorities) and captures resolvable
provenance for every accepted source (issue #44, FR-4/FR-5). The deterministic
control flow lives outside any model prompt:

- `DomainAllowlist.derive` uses the **exact** confirmed host from the
  trust-center URL; only that host, its subdomains, and explicitly configured
  standards authorities (empty by default) are fetchable. There is no
  registrable-domain / public-suffix guessing (which would be unsafe for
  multi-tenant suffixes such as `github.io`): sibling hosts and the parent apex
  require explicit human confirmation and are quarantined, and unrecognized
  hosts are refused (fail-closed).
- Every URL and redirect hop is validated (`ssrf.py`): HTTPS only, no
  credentialed URLs, allow-listed ports, DNS-name hosts (no dotted/decimal/hex/
  octal/IPv6 IP literals), and on-allowlist. Every resolved DNS answer must be
  globally routable; loopback, link-local (including `169.254.169.254`),
  private, CGNAT, reserved, multicast, unspecified, and IPv4-mapped IPv6
  addresses are refused. All answers are validated and one is pinned, and the
  transport must connect to that pinned IP, closing DNS-rebinding / drift.
- Redirects are resolved with `urljoin` against the current URL and fully
  re-validated: same-host relative redirects are followed; protocol-relative or
  absolute off-domain redirects are quarantined. Only 2xx responses become
  evidence; 4xx/5xx bodies are gaps.
- `ResearchPolicy` (`policy.py`) holds env-overridable redirect / size /
  download-count / timeout / deadline / content-type limits. The download-count
  and total-deadline budgets are enforced before every hop and the per-request
  timeout is clamped to the remaining budget. These are tool safety limits, not
  campus policy.
- `ProvenanceRecord` stores final URL, redirect chain, retrieval time, content
  hash, MIME type, vendor/product scope, resolved IP, and source locator.
  `provenance_to_citation` feeds findings through the existing citation checker
  so cross-vendor/product research is rejected like any other claim.
- Provider calls sit behind `Resolver` / `HttpTransport` interfaces with local
  fakes; `GuardedHttpTransport` injects an IP-pinned TLS socket (never
  reconnects/re-resolves) and closes exactly once. An AgentCore Browser provider
  would implement the same interface and is used only when
  `allow_agentcore_browser` is enabled for an approved account.
- Off-domain targets and redirect escapes are quarantined for human
  confirmation and never promoted; all other blocks/errors become gaps for
  manual review, so research never silently produces a compliant finding.
  Retrieved text is scanned for prompt-injection markers and flagged, never
  obeyed.

`VendorBackend` accepts an optional `research_provider`; when configured,
`run_intake_analysis` researches the confirmed trust-center URL and records
provenance / gaps / quarantined links on the `intake.analyzed` event (retrievable
via `intake_research(token)`). Research annotates only -- coverage, unresolved
questions, policy, and approval are unchanged, and with no provider configured
research is honestly reported as not performed. See
[ADR 0008](../../docs/decisions/0008-official-domain-vendor-research.md).

## Trust boundaries

The model may extract, summarize, compare, and draft. It must not establish
rules, change risk tiers, confirm fuzzy/semantic matches, approve, sign a TAAP,
select ServiceNow fields, or write back. Policy evaluation is a pure function of
structured inputs; disputed thresholds escalate rather than being resolved by a
model. Every write requires a recorded approved `HumanDecision`, a second
confirmation, matching record version, and is idempotent on
`case_id + decision_version`.

The standard-library HTTP server is a local adapter, not an authentication
boundary. Production API Gateway wiring must derive reviewer/admin identity from
Cognito and move invitation bearer tokens out of access-logged URL paths (or
redact those paths) before deployment. By default no local route browses a
submitted trust-center URL; browsing happens only through the guarded,
opt-in `research_provider` (see the official-domain research section), which
enforces the SSRF/DNS/redirect/provenance boundary and stores only validated
metadata and content hashes.

## Demo assumptions

The two active local review profiles are sanitized, explicitly labeled fixture
criteria (`fixture:security-profile` and `fixture:accessibility-profile`); they
are not CSUB policy and establish no thresholds or approval rules. The seeded
`csub-demo-import-v1` ServiceNow field mapping and request are deterministic
mock configuration for contract testing only. An administrator must replace
both fixtures with source-approved profile versions and a reviewed field map
before any deployed use; models cannot create criteria, mappings, approvals, or
field selections.
