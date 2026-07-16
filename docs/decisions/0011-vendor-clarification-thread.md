# ADR 0011: Case-scoped vendor clarification thread

- Status: Accepted
- Date: 2026-07-16
- Owner: CSUB VETTED integration owner
- Region: `us-west-2` (the approved VETTED sandbox stack region)
- Related: [PRD](../PRD.md), [PLAN](../../PLAN.md) (Wednesday vendor workflow), GitHub issue #41; builds on #37 reminders and #38 status

## Context

CSUB asked for a place on the vendor form where a vendor can ask what a
requested document means, report that a document cannot be obtained, or share an
ETA or concern, and asked that reminders point to the same feedback path. ADR
0010 (issue #37) intentionally deferred a monitored question/reply channel: its
reminder copy could invite a reply, but no inbound workflow was claimed. This
ADR adds that channel as a bounded, case-scoped thread rather than an untracked
free-text field or a real inbound-email pipeline.

## Decision

A new immutable `ThreadMessage` record is stored per workspace and case, behind
the existing `VendorRepository` seam, and round-trips through the durable
snapshot exactly like every other vendor record. Each message carries an author
role (vendor or reviewer), a category, sanitized body, timestamp, the
submission id/version it was written against, and an optional requirement id.
Message body, author, and timestamp are write-once history; only the mutable
`read_by_reviewer` and `resolved` flags are updated, by whole-record replacement.

Trust boundary:

- Vendor messages are accepted through the existing case-scoped invitation
  token (the same bearer/`/intake` surface as evidence). Posting is allowed
  while the link is live or after submission — a vendor may still ask questions
  during review — but revoked and expired links are rejected. Cross-case and
  cross-workspace access is impossible: a message id from another case is not
  reachable through a case's reviewer routes, and a second case's token cannot
  read the first case's thread.
- Message text is treated as untrusted data. It is length-bounded
  (`MAX_THREAD_BODY_CHARS`), rate-limited per case (`MAX_VENDOR_THREAD_MESSAGES`),
  and stripped of control characters (newlines/tabs preserved). It is stored and
  rendered as inert text — React escapes it on the client — and never alters
  policy criteria, requirements, agent instructions, or any deterministic route.
- Reviewers reply publicly (visible to the vendor through the scoped portal) or
  add internal notes (never serialized to the vendor). The vendor projection
  omits reviewer identity and internal visibility entirely, so a vendor sees
  only public replies and never which reviewer authored them. Reviewer identity
  for a reply is derived from the authenticated session server-side.

Surfacing and integration:

- A reviewer inbox (`GET /thread-inbox`) lists unresolved vendor questions
  across cases, one row per case, with contact, product, and
  outstanding-requirement context and no findings/policy/risk.
- The #38 vendor status projection gains a vendor-safe `thread` summary (counts
  and a "has a reviewer reply" flag) so the status view can link to the thread.
- The #37 reminder copy points the vendor at the same secure link for questions,
  satisfying "reminders provide the same feedback path" without a new transport.

No new AWS resource is introduced: the thread reuses the case Lambda, the
workspace snapshot store, and the existing scoped-link and JWT boundaries. Data
classification is **internal operational metadata plus untrusted vendor text**;
no document bytes or reviewer-only content enter the vendor projection, and audit
events record thread actions without copying reviewer notes into vendor-visible
records.

## Consequences and teardown

- Reviewers gain a triage inbox and per-message resolve/reply/mark-read
  controls; the public vendor status and scoped invitation behavior are
  otherwise unchanged.
- No schema migration or new table is required; thread messages live in the
  existing per-workspace snapshot and are removed with it under the existing
  stack/data retention policy.
- Rollback is the normal guarded PlatformStack rollback.

Issue #41 remains intentionally limited. VETTED does **not** implement inbound
email parsing, attachments on thread messages, vendor-to-vendor visibility, or a
real-time notification transport beyond the existing scoped link and the safe
outcome/reminder emails. A "safe email notification" to the vendor is limited to
pointing at the scoped portal; the thread itself is the system of record. Those
extensions require confirmed campus ownership and design before implementation.
