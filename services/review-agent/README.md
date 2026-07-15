# Review agent

Python workspace for the CSUB Technology Review Agent: ingestion, deterministic
policy, bounded LLM orchestration, mock ServiceNow write-back, and structured
audit. Deterministic policy, orchestration, provider adapters, and document
extraction live in separate modules, and every model/tool/AWS boundary is a
small interface with a local fake.

## Tuesday local vertical slice

The slice runs on the **standard library only** with **no live AWS** and no
institutional data. Deterministic fakes stand in for Bedrock, S3, and
ServiceNow so the whole flow is reproducible in CI. See
[ADR 0003](../../docs/decisions/0003-review-agent-local-slice.md) for the
rationale and the Wednesday wiring plan.

```bash
# From this workspace:
make test                     # deterministic unit tests (44)
PYTHONPATH=src python3 -m review_agent.demo   # low + medium + escalation + mock write-back
```

The demo runs a low-risk, a medium-risk, and a safe-escalation case, then a
simulated ServiceNow before/after preview and an idempotent commit with a packet
attachment (labeled `Simulated ServiceNow`).

## Layout

```text
src/review_agent/
  contracts/       Dataclasses mirroring packages/contracts JSON Schemas
  ingestion/       Source manifest + lossless workbook normalization (FR-2)
  policy/          Deterministic engine, versioned rules, conflict registry (FR-3)
  lookup/          Approved-software lookup with disclosed match method (FR-2)
  specialists/     Parallel security/accessibility nodes + citation checker (FR-5)
  packet/          Low- and medium-risk packet composition (FR-6)
  orchestration/   Workflow runner, node functions, checkpointer (sec 5)
  adapters/        model (Bedrock), storage (S3), servicenow (mock) interfaces + fakes
  audit/           Structured audit log that rejects sensitive content (sec 7)
  config.py        Env-driven config (region, model IDs) with no secrets
  samples.py       Synthetic sanitized fixtures for the slice and tests
  demo.py          Runnable vertical slice (python -m review_agent.demo)
tests/             Deterministic unit tests (policy, lookup, mock connector, slice)
```

## Trust boundaries

The model may extract, summarize, compare, and draft. It must not establish
rules, change risk tiers, confirm fuzzy/semantic matches, approve, sign a TAAP,
select ServiceNow fields, or write back. Policy evaluation is a pure function of
structured inputs; disputed thresholds escalate rather than being resolved by a
model. Every write requires a recorded approved `HumanDecision`, a second
confirmation, matching record version, and is idempotent on
`case_id + decision_version`.
