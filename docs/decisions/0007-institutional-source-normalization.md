# 0007 - Institutional source normalization slice

- Status: Accepted
- Date: 2026-07-15
- Deciders: Data/policy agent, integration owner
- Related: [PRD](../PRD.md) (sec 1, sec 5, FR-2, FR-3), [PLAN](../../PLAN.md), [ADR 0003](0003-review-agent-local-slice.md)

## Context

The supplied Box corpus mixes several kinds of material: formal process
flowcharts, an approved-software export, blank templates, data-classification
guidance, two draft decision trees, a signed (completed) TAAP, and a folder of
vendor evidence examples. Wednesday's plan needs campus policy and vendor
evidence kept in distinct retrieval scopes, requires human confirmation before a
source drives decisions, and treats every document as untrusted.

Two constraints shape this work. Institutional files, the normalized corpus, and
any hash tied to downloadable contents must stay out of Git (PRD sec 1, sec 7).
And a model must not decide which sources are authoritative, which are drafts, or
how to resolve provenance (AGENTS.md AI trust boundaries).

One supplied workbook contains a URL with `utm_source=chatgpt.com`. That marker
means the surrounding text was likely pasted from ChatGPT, so it cannot be
treated as an authoritative institutional source and the link should not be
fetched.

## Decision

Add `review_agent.institutional`, a development-time slice that normalizes
source metadata without ingesting document bodies.

1. **Path-based classification.** `classify(relative_path)` maps each source to a
   category, a corpus membership (institutional policy, case/vendor evidence,
   excluded, or unresolved), a confirmation status, a retrieval scope, and an
   activation flag. It matches on filenames already published in the PRD source
   inventory, so the rule table carries no institutional content or hashes.
2. **Scope separation.** Everything under `Example Documents/` is case/vendor
   evidence in the case-evidence scope. The signed TAAP is an excluded completed
   example. Formal processes, data classification, templates, the catalog, and
   recommendations are institutional policy. `CorpusNormalizationResult` keeps
   these in separate collections and `assert_scope_separation` fails if either
   scope leaks into the other.
3. **Drafts cannot be activated.** Both decision trees are draft and
   unconfirmed with FR-3 decision-tree-draft precedence. `assert_activatable`
   raises for any draft, example, excluded, or unresolved source, so only a
   human-confirmed institutional source can be activated.
4. **Untrusted text is detected, never obeyed.** `scan_untrusted_text` reports
   tracking / AI-provenance URLs and instruction-like phrases as findings that
   become extraction warnings. It fetches nothing and follows no embedded
   instruction.
5. **No committed content.** The core API reads no bytes and stores no body. A
   content hash is optional and runtime-only. A stdlib walker can print a
   metadata-only summary of a local corpus for developers; it persists nothing
   by default.

Shared contracts and existing policy rules are unchanged. The slice reuses
`SourceCoordinates`, `CitationScope`, and `SourcePrecedence` read-only.

## Consequences

- Classification, scope separation, activation blocking, and untrusted detection
  are covered by 22 unit tests that use synthetic fixtures only. No corpus file
  is read in tests.
- Unknown files surface as unresolved with a warning instead of a guess, which
  keeps source authority a human decision (PRD open question).
- The slice normalizes metadata only. Lossless extraction of document bodies,
  hashing of real bytes for the `SourceManifest`, and the KMS-encrypted S3
  upload (`raw/<box-file-id>/<sha256>/...`) are deferred to the AWS ingestion
  work and are out of scope here.

## Assumptions and open questions

- ASSUMPTION: the filename inventory in the PRD is stable enough to key
  classification on; a renamed source falls through to unresolved and is caught.
- Open question (PRD): which Box artifacts are authoritative versus examples or
  drafts. The two decision trees stay draft until a partner confirms them.
