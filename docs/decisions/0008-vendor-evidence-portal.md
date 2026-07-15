# 0008 - Vendor evidence portal (link, notify, research, gaps)

- Status: Accepted
- Date: 2026-07-14
- Deciders: AWS/integration owner
- Related: [PRD](../PRD.md), [PLAN](../../PLAN.md), [ADR 0004](0004-bedrock-model-pinning.md), [ADR 0005](0005-s3-and-dynamodb-persistence.md)

## Context

After intake, the internal tool needs to collect compliance evidence from the
vendor and measure it against CSUB's requirements. PLAN.md frames this as the
*official-vendor research* and *evidence specialist* nodes plus the stretch
*case-scoped vendor document-upload link*. The flow: mint a link, notify the
vendor and the committee, research the vendor's public posture, let the vendor
drop evidence into a bucket, then find the gap versus what policy requires.

## Decision

1. **Case-scoped, tokenized upload link.** `mint_invite` derives an unguessable
   token from `case_id` + a per-invite nonce (injected for test determinism; a
   high-entropy secret in production) and a `raw/<case_id>/vendor-upload/` prefix
   so evidence never crosses a case boundary (FR-4). `S3PresignedUploadIssuer`
   hands out presigned **SigV4** PUT URLs with SSE-KMS baked in; the local issuer
   returns deterministic placeholders.
2. **Notify both parties, simulated and labeled.** `MockNotifier` records what
   would be sent to the vendor and each committee member. Real SES/SNS delivery
   stays out of scope until a channel and identities are approved — the same
   discipline as the ServiceNow write-back.
3. **Research is advisory, never authoritative.** `ModelVendorResearch` (Bedrock
   via the `ModelClient` seam) summarizes the vendor's publicly documented
   posture, cites to the `official_vendor` scope with `verified=False`, and always
   discloses uncertainty. It does not assert compliance, set a risk tier, or
   approve. The local fake returns obviously-synthetic output.
4. **Gap analysis is deterministic and human-confirmed.** `analyze_gaps` compares
   the vendor's provided evidence types against `PolicyResult.required_evidence`
   (from the deterministic policy engine) as a pure set operation, filtered to the
   case. `EvidenceGapReport.requires_human_confirmation` stays `True`; the tool
   surfaces the gap, a human clears it. A model may help classify an upload's type
   upstream, but never decides what is required or whether a case is satisfied.
5. **Config-driven factory.** `build_vendor_portal` wires local fakes by default
   and live AWS (presigned S3 + Bedrock research) when `USE_LOCAL_FAKES=false`.

## Consequences

- The full path — link → notify vendor+committee → research → drop to bucket →
  gaps — runs end to end. Verified live in us-west-2: presigned SSE-KMS PUT
  (HTTP 200), Bedrock research with disclosed uncertainty, and a deterministic
  `missing: [soc2]` gap, with cleanup. CI stays stdlib-only (11 new tests over
  fakes; no boto3/network).
- Two incidental S3 fixes needed for real presigned uploads: force **SigV4** and
  **virtual-hosted regional addressing** so a vendor's PUT is signed correctly and
  does not bounce through a 307 redirect.
- Fixed `AppConfig.from_env`, which had been clobbering the pinned Bedrock model
  defaults with `None` when the env vars were unset.

## Assumptions and open questions

- ASSUMPTION: notifications remain simulated for the prototype; a real channel
  needs SES/SNS, verified identities, and Secrets Manager credentials.
- ASSUMPTION: upstream classification assigns each upload an `EvidenceType`; a
  model-assisted classifier (advisory, human-confirmed) is a follow-on.
- Open question: link TTL and evidence retention follow the case retention policy,
  still a PRD open question.
