"""rerank node -- narrow the shortlist. No LLM, optimized arm only."""

from __future__ import annotations

from app.graph.state import TicketState
from app.observability.logging import get_logger
from app.observability.tracer import Span, emit
from app.rag import rerank as reranker
from app.utils.timing import Stopwatch

log = get_logger(__name__)

NODE = "rerank"


def rerank(state: TicketState) -> dict:
    policy = state["policy"]

    if not policy.rerank_enabled or not policy.rerank_top_k:
        return {"reranked": None}

    hits = state.get("retrieved", [])
    if not hits:
        return {"reranked": []}

    watch = Stopwatch()
    narrowed = reranker.rerank(state["ticket"].as_query(), hits, top_k=policy.rerank_top_k)

    emit(
        Span(
            run_id=state["run_id"],
            node=NODE,
            kind="rerank",
            latency_ms=watch.stop(),
            chunk_ids=[h.chunk_id for h in narrowed],
        )
    )
    log.info("reranked", before=len(hits), after=len(narrowed))
    return {"reranked": narrowed}
