# 0011 - Bounded model retries/timeouts and structured run metrics

- Status: Accepted
- Date: 2026-07-16
- Deciders: Workflow/LLM owner
- Related: [PRD](../PRD.md), [ADR 0003](0003-review-agent-local-slice.md), [ADR 0004](0004-bedrock-model-pinning.md), issue #50

## Context

Issue #50 hardens the review orchestration for real multi-document workflows.
Two of its acceptance items had no implementation yet: "bounded
retries/timeouts" for live model calls, and CloudWatch metrics carrying
"correlation/run/step/model/profile/evidence versions, latency, token/cost,
retry, failure, and citation metrics ... without prompts or document bodies."

The existing `invoke_structured` (issue #27) already gives one bounded
structural-repair pass for malformed model replies and never substitutes the
deterministic fixture for a failed live call. That is a different failure
mode from a *transient* one (Bedrock throttling, a hung `converse` call) and
needed its own bounded-retry contract rather than overloading the repair pass.
`ReviewGraphState` also had no identifier tying one analysis attempt's audit
events and metrics together across a pause/resume/restart cycle.

## Decision

1. **`RetryPolicy` + `_call_with_retry`** (`adapters/model.py`): a per-call
   bounded retry (`max_attempts`, exponential backoff, default 3 attempts) and
   per-attempt timeout, run through a throwaway single-worker
   `ThreadPoolExecutor` so a synchronous `ModelClient.complete_json` call can
   still be time-bounded. Only transient failures retry — timeouts and
   Bedrock/botocore throttling-style error codes (duck-typed off a
   `ClientError`-shaped `.response`, no hard `botocore` import) — everything
   else propagates immediately into the existing structural-repair path.
   Retries never consume repair-pass budget and vice versa; they are separate,
   independently bounded mechanisms.
2. **Structured metrics via CloudWatch Embedded Metric Format (EMF)**
   (`observability/metrics.py`): a `MetricsEmitter` protocol,
   `EmbeddedMetricsEmitter` (writes one EMF JSON line per metric through
   stdlib `logging`, which CloudWatch Logs parses automatically once the
   process runs under Lambda/ECS with a subscribed log group), and
   `InMemoryMetricsSink` for tests. No `PutMetricData` calls, no extra IAM
   permissions, no live-AWS dependency in the local slice — same
   stdlib-logging-first shape as `audit/log.py`.
3. **Dimensions vs. properties is a deliberate cardinality/cost boundary.**
   Only low-cardinality fields (`workflow_version`, `step`, `model`,
   `simulated`) are CloudWatch *dimensions*. Per-case/run/correlation
   identifiers are EMF *properties* only: they still appear in the log line
   for correlation (and are greppable/Insights-queryable), but never multiply
   a CloudWatch metric stream per case. Both emitters share `audit/log.py`'s
   forbidden-key guard (`prompt`, `body`, `content`, `secret`, ...) so metric
   properties can never carry prompts or document bodies.
4. **`ReviewGraphState.run_id`**: an immutable identifier minted once per
   analysis run (`ReviewWorkflow._ensure_run_id`, injectable `id_factory` for
   deterministic tests) and carried in `to_dict()` for checkpoint durability.
   `lambda_api._review_state` round-trips it on restart-resume, so a run
   recovered from a durable checkpoint keeps its identity instead of minting a
   new one. It is threaded into every audit event as `AuditEvent.correlation_id`
   (a field the contract already had, previously unpopulated).
5. **Wiring**: `ReviewWorkflow` takes optional `metrics`/`retry_policy`
   constructor args (default `NullMetricsEmitter`/`DEFAULT_RETRY_POLICY`) and
   threads them into `run_security`/`run_accessibility` →
   `invoke_structured`. `run_specialists` emits wall-clock
   `specialists.latency_ms` and a `specialists.failure` count before
   re-raising; `check_and_repair` emits `citations.rejected_count` with the
   pass/fail outcome as a property. `review-graph-state.schema.json` gained an
   optional `run_id` field (shared contract, per AGENTS.md).

## Consequences

- A hung or throttled live Bedrock call now fails predictably within
  `max_attempts * timeout_seconds` instead of blocking a specialist run
  indefinitely; the eventual failure is still the existing reviewable
  `ModelStructureError`, never a silent fixture substitution.
- Every model invocation, specialist run, and citation check now has a metric
  trail keyed by run/case (as properties) without adding CloudWatch dimension
  cardinality per case — an operator dashboard can alert on
  `model.invoke.failure`/`specialists.failure` rates by step/model without a
  metrics explosion.
- `run_id` gives every audit event for one analysis attempt a shared
  `correlation_id`, and that identity now survives a Lambda cold start via the
  existing checkpoint round-trip.
- A timed-out call's underlying thread is not forcibly killed (Python cannot
  interrupt a running thread); the executor is shut down without waiting so
  the caller isn't blocked on it. This bounds *caller-observed* latency, not
  Bedrock-side resource usage — acceptable for the prototype's request volume,
  called out here rather than left implicit.

## Assumptions and open questions

- ASSUMPTION: `RetryPolicy` defaults (3 attempts, 0.5s base backoff, 30s
  per-attempt timeout) are reasonable for the camp sandbox's Bedrock quotas;
  revisit once a real throttling profile is observed.
- Open question (tracked in issue #50, not resolved here): durable
  checkpoints beyond `InMemoryCheckpointer`/DynamoDB-backed Lambda state,
  DLQ/manual recovery for exhausted retries, idempotent step replay, and the
  12-case evaluation gate are still outstanding.
