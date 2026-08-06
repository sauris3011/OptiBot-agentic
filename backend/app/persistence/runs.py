"""Run repository and span rollup (Deliverable 7 SS2.1)."""

from __future__ import annotations

from app.graph.state import TicketState
from app.persistence.db import execute, query, query_one
from app.utils.timing import utc_now_iso


def open_run(
    *,
    run_id: str,
    ticket_id: str,
    policy: str,
    cache_bypassed: bool,
    corpus_version: str,
    prompt_version: str,
    batch_id: str | None = None,
) -> None:
    """Insert the run row. cache_bypassed and both versions are recorded per run
    so any historical comparison can prove the conditions it ran under."""
    execute(
        """
        INSERT OR REPLACE INTO runs
          (run_id, batch_id, ticket_id, policy, cache_bypassed, corpus_version,
           prompt_version, status, started_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            batch_id,
            ticket_id,
            policy,
            int(cache_bypassed),
            corpus_version,
            prompt_version,
            "running",
            utc_now_iso(),
        ),
    )


def rollup(run_id: str, state: TicketState, *, status: str = "completed") -> None:
    """Aggregate spans onto the run row.

    Denormalised deliberately: the comparison dashboard must render without
    aggregating thousands of span rows (NFR-5.1). Spans remain the authoritative
    detail for the audit trail.
    """
    totals = query_one(
        """
        SELECT
          COALESCE(SUM(tokens_in), 0)         AS tokens_in,
          COALESCE(SUM(tokens_out), 0)        AS tokens_out,
          COALESCE(SUM(reasoning_tokens), 0)  AS reasoning_tokens,
          COALESCE(SUM(cost_usd), 0)          AS cost_usd,
          MAX(cost_estimated)                 AS cost_estimated,
          COALESCE(SUM(latency_ms), 0)        AS latency_ms,
          COALESCE(SUM(retry_count), 0)       AS retry_count,
          SUM(CASE WHEN kind = 'llm' THEN 1 ELSE 0 END)                  AS llm_calls,
          SUM(CASE WHEN kind = 'llm' AND schema_valid = 0 THEN 1 ELSE 0 END) AS violations
        FROM spans WHERE run_id = ?
        """,
        (run_id,),
    )

    grounding = state.get("grounding")
    execute(
        """
        UPDATE runs SET
          status = ?, decision = ?, decision_reason = ?,
          tokens_in = ?, tokens_out = ?, reasoning_tokens = ?, cost_usd = ?,
          cost_estimated = ?, latency_ms = ?, llm_call_count = ?, retry_count = ?,
          schema_violations = ?, unsupported_claims = ?, citation_coverage = ?,
          completed_at = ?
        WHERE run_id = ?
        """,
        (
            status,
            state.get("decision"),
            state.get("decision_reason"),
            totals["tokens_in"],
            totals["tokens_out"],
            totals["reasoning_tokens"],
            round(totals["cost_usd"], 8),
            totals["cost_estimated"] or 0,
            totals["latency_ms"],
            totals["llm_calls"] or 0,
            totals["retry_count"],
            totals["violations"] or 0,
            grounding.unsupported_claim_count if grounding else None,
            grounding.citation_coverage if grounding else None,
            utc_now_iso(),
            run_id,
        ),
    )


def mark_failed(run_id: str, error: str) -> None:
    execute(
        "UPDATE runs SET status = 'failed', decision_reason = ?, completed_at = ? WHERE run_id = ?",
        (error[:500], utc_now_iso(), run_id),
    )


def get_run(run_id: str) -> dict | None:
    row = query_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    return dict(row) if row else None


def list_runs(*, batch_id: str | None = None, limit: int = 100) -> list[dict]:
    if batch_id:
        rows = query(
            "SELECT * FROM runs WHERE batch_id = ? ORDER BY started_at DESC LIMIT ?",
            (batch_id, limit),
        )
    else:
        rows = query("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def pending_review() -> list[dict]:
    rows = query(
        "SELECT * FROM runs WHERE decision = 'human_review' AND status = 'awaiting_review' "
        "ORDER BY started_at ASC"
    )
    return [dict(r) for r in rows]
