# 0008 - Official-domain vendor research with SSRF and provenance controls

- Status: Accepted
- Date: 2026-07-15
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

1. **Approved allowlist from confirmed identity.** `DomainAllowlist.derive`
   computes the registrable domain (eTLD+1) of the reviewer/vendor-confirmed
   official (trust-center) URL. Fetches are allowed only for that domain and its
   subdomains, plus explicitly configured standards authorities (empty by
   default; the agent invents no external domains).
2. **Per-destination SSRF controls (`ssrf.py`).** Every URL and every redirect
   hop must be HTTPS, carry no credentials, use an allow-listed port (443), have
   a DNS-name host (no IP literal in dotted/decimal/hex/octal/IPv6 form), and be
   on the allowlist. Every resolved DNS answer must be globally routable;
   loopback, link-local (including `169.254.169.254`), private, CGNAT, reserved,
   multicast, unspecified, and IPv4-mapped IPv6 addresses are refused. All
   answers are validated and one is pinned for the connection, and the transport
   must report connecting to that pinned address, which closes DNS-rebinding and
   resolution-drift windows.
3. **Deterministic limits outside prompts (`policy.py`).** `ResearchPolicy`
   holds redirect, response-size, download-count, per-request timeout, total
   deadline, port, and content-type limits. They are operational tool-safety
   limits (not campus policy or risk tiers), env-overridable, and unreachable by
   a model.
4. **Provenance for every claim (`provenance.py`).** Each accepted source stores
   final URL, redirect chain, retrieval time, content SHA-256, MIME type, byte
   length, vendor/product scope, resolved IP, and source locator.
   `provenance_to_citation` projects a finding into the existing citation shape
   so `check_citations` rejects a cross-vendor/cross-product research finding
   exactly like any other claim.
5. **Provider interface with local fakes (`service.py`).** `Resolver` and
   `HttpTransport` are small interfaces; the stdlib `SystemResolver` /
   `GuardedHttpTransport` are the live seam and fakes drive the tests. An
   AgentCore Browser provider would implement `HttpTransport` and is used only
   when `allow_agentcore_browser` is set for an approved account; the same
   boundary is enforced regardless of provider.
6. **Fail safe, never silently compliant.** Off-domain targets and off-domain
   redirect locations are quarantined for human confirmation and never promoted
   into findings; every other block or transport/DNS error becomes a gap for
   manual review. Retrieved text is scanned for prompt-injection / tracking
   markers and flagged, never obeyed.

Shared contracts are unchanged. The module reuses `CitationScope`
(`official_vendor` / `standards`) and the institutional untrusted scanner
read-only.

## Consequences

- The SSRF/DNS/redirect controls and the provenance/citation projection are
  covered by 32 adversarial and provenance unit tests using synthetic hosts and
  a fake resolver/transport; no real network I/O runs in CI.
- The capability is not yet wired into the LangGraph packet flow. Binding a
  research node into `ReviewGraphState` and the packet composer touches
  workflow-owned files and is deferred to the workflow owner, who can consume
  `ResearchResult` findings (provenance-backed citations), gaps, and quarantined
  links directly.
- `GuardedHttpTransport` is a documented seam exercised only against a live host
  (excluded from coverage). The deployed environment should adopt the full
  Public Suffix List in place of the small built-in multi-label suffix set.

## Assumptions and open questions

- ASSUMPTION: registrable-domain matching with a small built-in multi-label
  public-suffix set is a conservative boundary for the prototype; it can only
  widen to a shorter suffix, never cross to an unrelated registrable domain.
- Open question (PRD sec 6): whether the approved AWS account permits AgentCore
  Browser. Until confirmed, `allow_agentcore_browser` stays `false` and the
  stdlib transport seam is the only live provider.
- Open question: which standards authorities (if any) an administrator will
  configure; the default is an empty list, so only the vendor's own domain is
  researched.
