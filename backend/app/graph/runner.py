"""Run orchestration: open the run, invoke the graph, roll up the metrics.

Thin by design. The graph owns the workflow; this owns bookkeeping, so neither
concern leaks into the other.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.policy import Policy, PolicyName, get_policy
from app.graph.builder import get_compiled_graph, get_uninterrupted_graph
from app.graph.state import TicketState
from app.observability.logging import clear_run_context, get_logger
from app.persistence import runs
from app.prompts.loader import prompt_version
from app.rag import store
from app.schemas.ticket import Ticket
from app.utils.ids import new_run_id

log = get_logger(__name__)


@dataclass
class RunResult:
    run_id: str
    state: TicketState
    interrupted: bool


def _corpus_version() -> str:
    info = store.stats().get("by_strategy", {})
    for entry in info.values():
        if entry.get("corpus_version"):
            return entry["corpus_version"]
    return ""


def run_ticket(
    ticket: Ticket,
    policy_name: PolicyName,
    *,
    bypass_cache: bool = False,
    batch_id: str | None = None,
    allow_interrupt: bool = True,
) -> RunResult:
    """Execute one ticket through the graph under one policy."""
    policy: Policy = get_policy(policy_name, bypass_cache=bypass_cache)
    run_id = new_run_id()
    variant = policy.prompt_variant

    runs.open_run(
        run_id=run_id,
        ticket_id=ticket.ticket_id,
        policy=policy.name,
        cache_bypassed=not policy.cache_enabled,
        corpus_version=_corpus_version(),
        prompt_version=prompt_version(variant),
        batch_id=batch_id,
    )

    initial: TicketState = {
        "run_id": run_id,
        "policy": policy,
        "ticket": ticket,
        "corpus_version": _corpus_version(),
        "prompt_version": prompt_version(variant),
        "retrieved": [],
        "errors": [],
        "degraded": False,
    }

    graph = get_compiled_graph() if allow_interrupt else get_uninterrupted_graph()
    config = {"configurable": {"thread_id": run_id}}

    try:
        final = graph.invoke(initial, config)
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
        runs.mark_failed(run_id, f"{type(exc).__name__}: {exc}")
        log.error("run_failed", run_id=run_id, error=str(exc)[:300])
        clear_run_context()
        raise

    # The graph pauses BEFORE human_review, so an interrupted run has its
    # decision recorded but has not reached a terminal node.
    snapshot = graph.get_state(config)
    interrupted = bool(snapshot.next)

    runs.rollup(
        run_id,
        final,
        status="awaiting_review" if interrupted else "completed",
    )
    clear_run_context()

    return RunResult(run_id=run_id, state=final, interrupted=interrupted)


def resume_run(run_id: str, *, approved: bool) -> RunResult:
    """Resume a paused run after a reviewer decision (FR-1.8)."""
    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": run_id}}

    graph.update_state(
        config,
        {"decision_reason": f"human review: {'approved' if approved else 'rejected'}"},
    )
    final = graph.invoke(None, config)
    runs.rollup(run_id, final, status="completed" if approved else "rejected")
    clear_run_context()
    return RunResult(run_id=run_id, state=final, interrupted=False)
