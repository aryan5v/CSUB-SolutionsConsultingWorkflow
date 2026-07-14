# 0007 - LangGraph StateGraph binding

- Status: Accepted
- Date: 2026-07-14
- Deciders: AWS/integration owner
- Related: [PRD](../PRD.md), [ADR 0003](0003-review-agent-local-slice.md), [ADR 0006](0006-durable-checkpointer.md)

## Context

ADR 0003 built the workflow as node methods over `ReviewGraphState` and promised
the same functions would bind 1:1 to a LangGraph graph. With the model, storage,
and a durable checkpointer wired, this closes the orchestration seam: make the
topology and the human-interrupt boundaries explicit as a real LangGraph
`StateGraph`, without changing node behavior or the locked state contract.

## Decision

1. **A real `StateGraph` wraps the existing `ReviewWorkflow` methods.**
   `orchestration/langgraph_app.py` adds one graph node per method
   (`validate_intake` → `lookup_software` → `evaluate_policy` → `run_specialists`
   → `check_and_repair` → `compose`) with conditional edges to `END` at the three
   human interrupts (awaiting match confirmation, escalation, awaiting review).
2. **State is carried as one opaque channel.** `GraphState` is a `TypedDict` with
   a single `state: ReviewGraphState` field. Carrying the whole object keeps the
   locked contract as the source of truth and avoids per-field reducer bugs;
   routing reads `state.status`.
3. **`langgraph` is an optional `aws`-extra dependency, imported only here.** The
   stdlib local slice, demo, and CI never import this module. The parity tests
   are guarded with `skipUnless(find_spec("langgraph"))` and import the module
   lazily, so CI (no langgraph) skips them with no collection error.
4. **Checkpointing stays layered.** LangGraph's compiled checkpointer (optional
   `MemorySaver`) handles in-run thread state; durable cross-process pause/resume
   remains the workflow's own `DynamoDbCheckpointer` (ADR 0006), which the node
   methods call at each boundary.

## Consequences

- The orchestration seam from ADR 0003 is fully realized. Parity tests assert the
  graph produces byte-for-byte the same `ReviewGraphState.to_dict()` as the
  sequential `run_until_review` for every sample case, so the binding is a
  behavior-preserving refactor, not a rewrite.
- CI stays stdlib-only and green (74 tests, 4 skipped without langgraph).

## Assumptions and open questions

- ASSUMPTION: whole-object state channel is adequate; if future nodes need
  parallel fan-out with independent field merges, split channels then.
- Follow-on: LangGraph-native resume via `Command`/`interrupt` and a DynamoDB
  `BaseCheckpointSaver` (vs. the current app-level durable snapshot) if per-thread
  checkpoint history is needed; full `ReviewGraphState.from_dict` rehydration to
  continue a resumed run.
