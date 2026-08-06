"""retrieve node -- LanceDB semantic search. No LLM.

Deterministic code doing work the baseline would ask a model to do. Replacing
LLM calls with arithmetic is itself a measurable optimization.
"""

from __future__ import annotations

from app.graph.state import TicketState
from app.observability.logging import get_logger
from app.observability.tracer import Span, emit
from app.rag import store
from app.utils.timing import Stopwatch

log = get_logger(__name__)

NODE = "retrieve"


def retrieve(state: TicketState) -> dict:
    policy = state["policy"]
    ticket = state["ticket"]
    classification = state.get("classification")
    watch = Stopwatch()

    # The metadata filter is available only when the chunks carry a category,
    # which fixed_512 chunks do not -- the naive strategy discarded the
    # structure it would come from. The advantage is a consequence of better
    # ingestion, not a handicap imposed on the baseline.
    category = None
    if policy.metadata_filter_enabled and classification:
        if classification.category != "Other":
            category = classification.category

    hits = store.search(
        ticket.as_query(),
        strategy=policy.chunking,
        top_k=policy.retrieval_top_k,
        category=category,
    )

    # A category filter that eliminates everything is worse than no filter. Fall
    # back rather than hand the draft node an empty context, which would make
    # every claim unsupported for a reason unrelated to grounding quality.
    if not hits and category:
        log.info("retrieve_filter_fallback", category=category)
        hits = store.search(
            ticket.as_query(), strategy=policy.chunking, top_k=policy.retrieval_top_k
        )

    emit(
        Span(
            run_id=state["run_id"],
            node=NODE,
            kind="retrieval",
            latency_ms=watch.stop(),
            chunk_ids=[h.chunk_id for h in hits],
        )
    )
    log.info("retrieved", count=len(hits), strategy=policy.chunking, category_filter=category)
    return {"retrieved": hits}
