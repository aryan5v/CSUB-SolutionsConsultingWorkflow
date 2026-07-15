# 0008 - Official-domain vendor research with SSRF and provenance controls

- Status: Accepted
- Date: 2026-07-15 (revised after independent review)
- Deciders: Review workflow agent, integration owner
- Related: [PRD](../PRD.md) (sec 3 non-goals, FR-4, FR-5, sec 6, sec 7), [PLAN](../../PLAN.md) (official-vendor research node), [ADR 0007](0007-institutional-source-normalization.md), GitHub issue #44

## Context

Public evidence research must never treat an arbitrary third-party document as
authoritative vendor evidence. CSUB asked whether the system would accept anyone
claiming a file was, for example, "Microsoft's VPAT"; the agreed boundary is the
verified vendor domain / trust center first (issue #44). A research tool that
fetches URLs is also a classic SSRF sink: without controls it can be steered at
`localhost`, cloud metadata endpoints, private networks, or an attacker's host
via redirects, DNS rebinding, credentialed URLs, or alternate numeric IP forms.

The PRD already forbids autonomous browsing outside configured official vendor
and standards domains (sec 3), requires vendor/product-scoped evidence with
source hashes (FR-4), grounds every factual claim in a captured source (FR-5),
treats retrieved content as untrusted (sec 7), and keeps provider calls behind
testable interfaces (sec 6). A model must not widen any of these limits
(AGENTS.md AI trust boundaries).

## Decision

Add `review_agent.research`: a deterministic, provider-abstracted capability
that fetches only official-domain evidence and captures full provenance.

1. **Fail-closed exact-host allowlist.** `DomainAllowlist.derive` takes the
   **exact** reviewer/vendor-confirmed host from the official (trust-center) URL
   and allows only that host and its subdomains, plus explicitly configured
   standards authorities (empty by default). There is deliberately **no**
   registrable-domain / public-suffix guessing: a "last two labels" fallback is
   unsafe for multi-tenant public suffixes (`github.io`, `appspot.com`), where it
   would let `attacker.github.io` reach `vendor.github.io`. Sibling hosts and the
   parent apex are treated as off-domain and quarantined for explicit human
   confirmation; unrecognized hosts are refused, never guessed.
2. **Per-destination SSRF controls (`ssrf.py`).** Every URL and every redirect
   hop must be HTTPS, carry no credentials, use an allow-listed port (443), have
   a DNS-name host (no IP literal in dotted/decimal/hex/octal/IPv6 form), and be
   on the allowlist. Every resolved DNS answer must be globally routable;
   loopback, link-local (including `169.254.169.254`), private, CGNAT, reserved,
   multicast, unspecified, and IPv4-mapped IPv6 addresses are refused. All
   answers are validated and one is pinned for the connection, and the transport
   must report connecting to that pinned address, which closes DNS-rebinding and
   resolution-drift windows.
3. **Deterministic limits enforced before every hop (`policy.py`).**
   `ResearchPolicy` holds redirect, response-size, download-count, per-request
   timeout, total deadline, port, and content-type limits. The download-count
   and total-deadline budgets are checked before *every* network call (initial
   request and each redirect), and each request timeout is clamped to the
   remaining deadline. They are operational tool-safety limits (not campus policy
   or risk tiers), env-overridable, and unreachable by a model.
4. **Redirects resolved safely.** A redirect `Location` is resolved with
   `urljoin` against the current URL, then fully re-validated. A same-host
   relative redirect is allowed; a protocol-relative (`//other`) or absolute
   off-domain redirect resolves to an off-allowlist host and is quarantined. Only
   2xx responses become evidence; 4xx/5xx (and any non-2xx) bodies are gaps for
   manual review, never findings.
5. **Provenance for every claim (`provenance.py`).** Each accepted source stores
   final URL, redirect chain, retrieval time, content SHA-256, MIME type, byte
   length, vendor/product scope, resolved IP, and source locator.
   `provenance_to_citation` projects a finding into the existing citation shape
   so `check_citations` rejects a cross-vendor/cross-product research finding
   exactly like any other claim.
6. **Provider interface with local fakes (`service.py`).** `Resolver` and
   `HttpTransport` are small interfaces; the stdlib `SystemResolver` /
   `GuardedHttpTransport` are the live seam (the transport injects an
   already-connected, IP-pinned TLS socket so `http.client` never reconnects or
   re-resolves, and closes the connection exactly once on every path) and fakes
   drive the tests. An AgentCore Browser provider would implement `HttpTransport`
   and is used only when `allow_agentcore_browser` is set for an approved
   account; the same boundary is enforced regardless of provider.
7. **Fail safe, never silently compliant.** Off-domain targets and off-domain
   redirect locations are quarantined for human confirmation and never promoted
   into findings; every other block or transport/DNS/HTTP error becomes a gap for
   manual review. Retrieved text is scanned for prompt-injection / tracking
   markers and flagged, never obeyed.
8. **Deterministic integration seam.** `VendorBackend` accepts an optional
   `research_provider` (the structural `VendorResearchProvider` interface, which
   `VendorResearchService` satisfies). During `run_intake_analysis`, when a
   provider is configured, the confirmed trust-center URL is researched and the
   provenance / gaps / quarantined links are recorded on the `intake.analyzed`
   integration event and retrievable via `intake_research(token)`. Research
   **annotates only**: deterministic coverage, unresolved questions, policy, and
   approval are unchanged, and with no provider configured research is honestly
   reported as not performed rather than fabricated.

Shared contracts are unchanged (the `Submission` schema is untouched; provenance
rides on the existing integration-event detail). The module reuses
`CitationScope` (`official_vendor` / `standards`) and the institutional
untrusted scanner read-only.

## Consequences

- The SSRF/DNS/redirect/HTTP-status controls, provenance/citation projection,
  and the vendor-intake integration are covered by 46 unit tests (adversarial,
  provenance, and integration) using synthetic hosts and a fake
  resolver/transport; no real network I/O runs in CI.
- Issue #44 acceptance is met on the review path: same-domain trust-center
  evidence enters intake analysis with resolvable provenance, and research
  failures (off-domain, private/metadata IP, DNS rebinding, redirect escape,
  oversized, unsupported content, 4xx/5xx, timeouts) surface as gaps/manual
  review and never become compliant findings. Binding research into the deeper
  LangGraph packet-composition flow remains available to the workflow owner via
  the same `ResearchResult`.
- `GuardedHttpTransport` is a documented seam exercised only against a live host
  (excluded from coverage).

## Assumptions and open questions

- ASSUMPTION: the exact reviewer-confirmed host (plus its subdomains) is the
  correct fail-closed research boundary for the prototype. Widening to a sibling
  host or parent apex is an explicit human decision, not a parsing heuristic; the
  full Public Suffix List is intentionally not adopted (it would break the
  dependency-free local slice and is unnecessary under the exact-host model).
- Open question (PRD sec 6): whether the approved AWS account permits AgentCore
  Browser. Until confirmed, `allow_agentcore_browser` stays `false` and the
  stdlib transport seam is the only live provider.
- Open question: which standards authorities (if any) an administrator will
  configure; the default is an empty list, so only the vendor's own confirmed
  host is researched.
