"""Real LangGraph binding for the review workflow (PRD sec 5, ADR 0003).

The Tuesday slice ran the node methods as a deterministic sequential runner and
promised that the *same* functions would bind 1:1 to a LangGraph ``StateGraph``.
This module delivers that: each graph node wraps a ``ReviewWorkflow`` method, and
conditional edges route to ``END`` at the three human-interrupt boundaries
(awaiting match confirmation, escalation, awaiting review). Behavior is identical
to ``ReviewWorkflow.run_until_review`` — the graph only makes the topology and
interrupts explicit and gives LangGraph's checkpointer a place to attach.

``langgraph`` is an optional (``aws`` extra) dependency imported here at module
top; the stdlib local slice and CI never import this module, so they stay
dependency-free. Durable cross-process persistence is handled by the workflow's
own ``Checkpointer`` (ADR 0006), which its node methods call at each boundary;
LangGraph's compiled checkpointer handles in-run thread state.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ..contracts.graph_state import ReviewGraphState, WorkflowStatus
from .graph import ReviewWorkflow


class GraphState(TypedDict):
    """Single opaque channel carrying the workflow's ``ReviewGraphState``.

    Carrying one object (rather than exploding every field into a channel) keeps
    the locked ``ReviewGraphState`` contract as the source of truth and avoids
    reducer bugs; routing reads ``state.status``.
    """

    state: ReviewGraphState


# Routing labels for conditional edges.
_INTERRUPT = "interrupt"
_CONTINUE = "continue"


def build_review_graph(workflow: ReviewWorkflow, *, checkpointer: Any | None = None) -> Any:
    """Compile a LangGraph graph whose nodes are ``workflow``'s methods.

    ``checkpointer`` is an optional LangGraph ``BaseCheckpointSaver`` (e.g.
    ``MemorySaver``) for in-run thread state; pass ``None`` for a pure run.
    """
    builder: StateGraph = StateGraph(GraphState)

    def _node(method):
        def run(gs: GraphState) -> GraphState:
            return {"state": method(gs["state"])}

        return run

    builder.add_node("validate_intake", _node(workflow.validate_intake))
    builder.add_node("lookup_software", _node(workflow.lookup_software))
    builder.add_node("evaluate_policy", _node(workflow.evaluate_policy))
    builder.add_node("run_specialists", _node(workflow.run_specialists))
    builder.add_node("check_and_repair", _node(workflow.check_and_repair))
    builder.add_node("compose", _node(workflow.compose))

    builder.add_edge(START, "validate_intake")
    builder.add_edge("validate_intake", "lookup_software")

    # Human interrupt: a fuzzy/semantic match awaits reviewer confirmation.
    builder.add_conditional_edges(
        "lookup_software",
        lambda gs: _INTERRUPT
        if gs["state"].status is WorkflowStatus.AWAITING_MATCH_CONFIRMATION
        else _CONTINUE,
        {_INTERRUPT: END, _CONTINUE: "evaluate_policy"},
    )
    # Human interrupt: deterministic policy escalated the case.
    builder.add_conditional_edges(
        "evaluate_policy",
        lambda gs: _INTERRUPT
        if gs["state"].status is WorkflowStatus.ESCALATED
        else _CONTINUE,
        {_INTERRUPT: END, _CONTINUE: "run_specialists"},
    )
    builder.add_edge("run_specialists", "check_and_repair")
    builder.add_edge("check_and_repair", "compose")
    # compose sets AWAITING_REVIEW and checkpoints; that is the final interrupt.
    builder.add_edge("compose", END)

    return builder.compile(checkpointer=checkpointer)


def run_review_graph(
    workflow: ReviewWorkflow, state: ReviewGraphState, *, checkpointer: Any | None = None
) -> ReviewGraphState:
    """Run a case through the compiled graph to its first human interrupt.

    Mirrors ``ReviewWorkflow.run_until_review`` but via a real LangGraph graph.
    When ``checkpointer`` is set, the run is threaded on ``state.case_id`` so
    LangGraph can resume it.
    """
    app = build_review_graph(workflow, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": state.case_id}} if checkpointer else None
    result = app.invoke({"state": state}, config=config)
    return result["state"]
