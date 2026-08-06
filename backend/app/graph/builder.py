"""Graph assembly (Deliverable 6 SS1).

ONE graph serves both measurement arms. Every behavioural difference comes from
the frozen Policy carried in state -- there is no `if policy.name == "baseline"`
anywhere in graph/, verifiable with:

    grep -rn 'name == "baseline"' backend/app/graph/

That property is what makes the comparison defensible: no code path exists
solely to make the baseline look bad.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, StateGraph

from app.graph.nodes.classify import classify
from app.graph.nodes.draft import draft
from app.graph.nodes.ground_check import ground_check
from app.graph.nodes.guardrail_post import guardrail_post
from app.graph.nodes.guardrail_pre import guardrail_pre
from app.graph.nodes.ingest import ingest
from app.graph.nodes.rerank import rerank
from app.graph.nodes.retrieve import retrieve
from app.graph.nodes.route import route, route_edge
from app.graph.nodes.terminal import auto_resolve, human_review, quarantine
from app.graph.state import TicketState
from app.observability.logging import get_logger

log = get_logger(__name__)


def guardrail_pre_edge(state: TicketState) -> str:
    """Short-circuit to quarantine when input screening blocks.

    Blocking early is the point: a social-engineering attempt must never reach
    the draft node, and skipping the remaining LLM calls is a real cost saving
    on exactly the tickets that deserve no spend.
    """
    verdict = state.get("guardrail_pre")
    if verdict is not None and verdict.blocked:
        return "quarantine"
    return "retrieve"


def build_graph() -> StateGraph:
    graph = StateGraph(TicketState)

    graph.add_node("ingest", ingest)
    graph.add_node("classify", classify)
    graph.add_node("guardrail_pre", guardrail_pre)
    graph.add_node("retrieve", retrieve)
    graph.add_node("rerank", rerank)
    graph.add_node("draft", draft)
    graph.add_node("ground_check", ground_check)
    graph.add_node("guardrail_post", guardrail_post)
    graph.add_node("route", route)
    graph.add_node("auto_resolve", auto_resolve)
    graph.add_node("human_review", human_review)
    graph.add_node("quarantine", quarantine)

    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "classify")
    graph.add_edge("classify", "guardrail_pre")

    graph.add_conditional_edges(
        "guardrail_pre",
        guardrail_pre_edge,
        {"retrieve": "retrieve", "quarantine": "quarantine"},
    )

    # rerank is always traversed; it no-ops when policy.rerank_enabled is False.
    # Keeping the node in the path rather than branching around it means both
    # arms walk an identical topology, so a span-count difference reflects
    # policy rather than graph shape.
    graph.add_edge("retrieve", "rerank")
    graph.add_edge("rerank", "draft")
    graph.add_edge("draft", "ground_check")
    graph.add_edge("ground_check", "guardrail_post")
    graph.add_edge("guardrail_post", "route")

    graph.add_conditional_edges(
        "route",
        route_edge,
        {
            "auto_resolve": "auto_resolve",
            "human_review": "human_review",
            "quarantine": "quarantine",
        },
    )

    graph.add_edge("auto_resolve", END)
    graph.add_edge("human_review", END)
    graph.add_edge("quarantine", END)

    return graph


@lru_cache(maxsize=1)
def get_compiled_graph():
    """Compile once with the SQLite checkpointer (FR-1.8).

    interrupt_before=["human_review"] is what makes the pause real: state
    persists to a checkpoint and execution stops until a decision resumes it.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    from app.persistence.db import get_db

    checkpointer = SqliteSaver(get_db())
    checkpointer.setup()

    compiled = build_graph().compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],
    )
    log.info("graph_compiled", interrupt_before=["human_review"])
    return compiled


@lru_cache(maxsize=1)
def get_uninterrupted_graph():
    """Compiled without the interrupt, for batch evaluation.

    Batch runs measure the routing DECISION, which route() has already recorded
    in state by the time the interrupt would fire. Pausing 50 tickets for human
    input would make unattended evaluation impossible, and resuming them would
    not change a single metric.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    from app.persistence.db import get_db

    checkpointer = SqliteSaver(get_db())
    checkpointer.setup()
    return build_graph().compile(checkpointer=checkpointer)
