"""Human review decisions (FR-2.6).

APPEND-ONLY. This module deliberately exposes no UPDATE or DELETE path, so the
audit trail is immutable by construction rather than by policy. Adding one would
defeat the governance guarantee the PRD makes.
"""

from __future__ import annotations

from app.persistence.db import execute, query, query_one
from app.utils.ids import new_review_id
from app.utils.timing import utc_now_iso


def record(
    *,
    run_id: str,
    reviewer: str,
    decision: str,
    reason: str | None,
    escalation_cause: str,
) -> str:
    if decision not in ("approve", "reject"):
        raise ValueError(f"decision must be 'approve' or 'reject', got {decision!r}")

    review_id = new_review_id()
    execute(
        "INSERT INTO reviews "
        "(review_id, run_id, reviewer, decision, reason, escalation_cause, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (review_id, run_id, reviewer, decision, reason, escalation_cause, utc_now_iso()),
    )
    return review_id


def for_run(run_id: str) -> dict | None:
    row = query_one(
        "SELECT * FROM reviews WHERE run_id = ? ORDER BY created_at DESC LIMIT 1", (run_id,)
    )
    return dict(row) if row else None


def history(limit: int = 100) -> list[dict]:
    rows = query("SELECT * FROM reviews ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def stats() -> dict:
    row = query_one(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN decision = 'approve' THEN 1 ELSE 0 END) AS approved "
        "FROM reviews"
    )
    total = (row["total"] if row else 0) or 0
    approved = (row["approved"] if row else 0) or 0
    return {
        "total": total,
        "approved": approved,
        "rejected": total - approved,
        "approval_rate": round(approved / total, 4) if total else 0.0,
    }
