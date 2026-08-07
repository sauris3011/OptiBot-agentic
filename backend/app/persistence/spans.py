"""Span queries for the audit trail (FR-2.4)."""

from __future__ import annotations

import json

from app.persistence.db import query, query_one


def for_run(run_id: str) -> list[dict]:
    rows = query("SELECT * FROM spans WHERE run_id = ? ORDER BY created_at ASC", (run_id,))
    out = []
    for row in rows:
        span = dict(row)
        if span.get("chunk_ids"):
            try:
                span["chunk_ids"] = json.loads(span["chunk_ids"])
            except json.JSONDecodeError:
                span["chunk_ids"] = []
        out.append(span)
    return out


def cache_stats() -> dict:
    """Hit/miss over LLM spans, excluding bypassed benchmark runs.

    Bypassed spans are excluded from the ratio deliberately: including runs where
    the cache was switched off would understate the hit rate and describe a
    configuration nobody runs in production.
    """
    row = query_one(
        """
        SELECT
          SUM(CASE WHEN cache_status IN ('hit_exact','hit_semantic') THEN 1 ELSE 0 END) AS hits,
          SUM(CASE WHEN cache_status = 'miss'     THEN 1 ELSE 0 END) AS misses,
          SUM(CASE WHEN cache_status = 'bypassed' THEN 1 ELSE 0 END) AS bypassed
        FROM spans WHERE kind = 'llm'
        """
    )
    hits = (row["hits"] if row else 0) or 0
    misses = (row["misses"] if row else 0) or 0
    bypassed = (row["bypassed"] if row else 0) or 0
    total = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "bypassed": bypassed,
        "hit_rate": round(hits / total, 4) if total else 0.0,
    }


def node_breakdown(run_id: str) -> list[dict]:
    """Per-node cost and latency -- shows where the tokens actually went."""
    rows = query(
        """
        SELECT node, kind, tier, resolved_model,
               SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out,
               SUM(reasoning_tokens) AS reasoning_tokens,
               SUM(cost_usd) AS cost_usd, SUM(latency_ms) AS latency_ms
        FROM spans WHERE run_id = ? GROUP BY node, kind ORDER BY MIN(created_at)
        """,
        (run_id,),
    )
    return [dict(r) for r in rows]
