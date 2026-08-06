"""SQLite schema (Deliverable 7).

DDL only. Repository logic lives in sibling modules. Every statement is
idempotent so startup can run this unconditionally.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

#: Executed in order at startup by persistence/db.py.
DDL: tuple[str, ...] = (
    # -- runs: one row per pipeline execution ------------------------------
    # Metrics are rolled up here as well as living in `spans`. The
    # denormalisation is deliberate: the comparison dashboard must render
    # without aggregating thousands of span rows (NFR-5.1).
    """
    CREATE TABLE IF NOT EXISTS runs (
      run_id             TEXT PRIMARY KEY,
      batch_id           TEXT,
      ticket_id          TEXT NOT NULL,
      policy             TEXT NOT NULL,
      -- Stored per run so any historical comparison can prove the conditions
      -- it ran under. A number without its conditions is not evidence.
      cache_bypassed     INTEGER NOT NULL DEFAULT 0,
      corpus_version     TEXT NOT NULL DEFAULT '',
      prompt_version     TEXT NOT NULL DEFAULT '',
      status             TEXT NOT NULL,
      decision           TEXT,
      decision_reason    TEXT,
      tokens_in          INTEGER NOT NULL DEFAULT 0,
      tokens_out         INTEGER NOT NULL DEFAULT 0,
      cost_usd           REAL    NOT NULL DEFAULT 0,
      cost_estimated     INTEGER NOT NULL DEFAULT 0,
      latency_ms         INTEGER,
      llm_call_count     INTEGER NOT NULL DEFAULT 0,
      retry_count        INTEGER NOT NULL DEFAULT 0,
      schema_violations  INTEGER NOT NULL DEFAULT 0,
      unsupported_claims INTEGER,
      citation_coverage  REAL,
      precision_at_k     REAL,
      started_at         TEXT NOT NULL,
      completed_at       TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_runs_batch_policy ON runs(batch_id, policy)",
    "CREATE INDEX IF NOT EXISTS idx_runs_ticket ON runs(ticket_id)",
    "CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)",

    # -- spans: one row per LLM call or instrumented node (FR-2.4) ---------
    # prompt_hash, never prompt text: reproducibility and cache correlation
    # without persisting content that redaction would then have to police.
    """
    CREATE TABLE IF NOT EXISTS spans (
      span_id           TEXT PRIMARY KEY,
      run_id            TEXT NOT NULL REFERENCES runs(run_id),
      parent_span_id    TEXT,
      node              TEXT NOT NULL,
      kind              TEXT NOT NULL,
      tier              TEXT,
      resolved_model    TEXT,
      tokens_in         INTEGER,
      tokens_out        INTEGER,
      cost_usd          REAL,
      cost_estimated    INTEGER NOT NULL DEFAULT 0,
      latency_ms        INTEGER NOT NULL,
      cache_status      TEXT,
      retry_count       INTEGER NOT NULL DEFAULT 0,
      schema_valid      INTEGER,
      repair_attempted  INTEGER NOT NULL DEFAULT 0,
      guardrail_verdict TEXT,
      chunk_ids         TEXT,
      prompt_hash       TEXT,
      error_code        TEXT,
      created_at        TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_spans_run ON spans(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_spans_cache ON spans(cache_status)",

    # -- reviews: human decisions (FR-2.6) ---------------------------------
    # Append-only. persistence/reviews.py exposes no UPDATE or DELETE path, so
    # the audit trail is immutable by construction rather than by policy.
    """
    CREATE TABLE IF NOT EXISTS reviews (
      review_id        TEXT PRIMARY KEY,
      run_id           TEXT NOT NULL REFERENCES runs(run_id),
      reviewer         TEXT NOT NULL,
      decision         TEXT NOT NULL,
      reason           TEXT,
      escalation_cause TEXT NOT NULL,
      created_at       TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_reviews_run ON reviews(run_id)",

    # -- llm_cache: exact + semantic (Deliverable 8) -----------------------
    """
    CREATE TABLE IF NOT EXISTS llm_cache (
      cache_key        TEXT PRIMARY KEY,
      node             TEXT NOT NULL,
      prompt_embedding BLOB,
      response_json    TEXT NOT NULL,
      tokens_in        INTEGER,
      tokens_out       INTEGER,
      cost_usd         REAL,
      model            TEXT NOT NULL,
      corpus_version   TEXT,
      prompt_version   TEXT,
      hit_count        INTEGER NOT NULL DEFAULT 0,
      created_at       TEXT NOT NULL,
      last_hit_at      TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cache_node ON llm_cache(node)",

    # -- batches: eval run metadata ----------------------------------------
    """
    CREATE TABLE IF NOT EXISTS batches (
      batch_id       TEXT PRIMARY KEY,
      sample_size    INTEGER NOT NULL,
      cache_bypassed INTEGER NOT NULL,
      corpus_version TEXT NOT NULL DEFAULT '',
      prompt_version TEXT NOT NULL DEFAULT '',
      status         TEXT NOT NULL,
      started_at     TEXT NOT NULL,
      completed_at   TEXT
    )
    """,

    # -- goldset: hand-labelled relevance judgements (FR-3.4) --------------
    """
    CREATE TABLE IF NOT EXISTS goldset (
      ticket_id          TEXT PRIMARY KEY,
      relevant_chunk_ids TEXT NOT NULL,
      notes              TEXT
    )
    """,

    # -- documents ---------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS documents (
      doc_id       TEXT PRIMARY KEY,
      title        TEXT NOT NULL,
      source       TEXT,
      category     TEXT,
      chunk_counts TEXT NOT NULL DEFAULT '{}',
      uploaded_at  TEXT NOT NULL
    )
    """,

    # -- settings: runtime-mutable config, survives restart ----------------
    """
    CREATE TABLE IF NOT EXISTS settings (
      key        TEXT PRIMARY KEY,
      value      TEXT,
      encrypted  INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL
    )
    """,

    # -- a2a_peers: tokens stored hashed, never in clear (FR-6.3) ----------
    """
    CREATE TABLE IF NOT EXISTS a2a_peers (
      peer_id        TEXT PRIMARY KEY,
      name           TEXT NOT NULL,
      agent_card_url TEXT,
      token_hash     TEXT NOT NULL,
      granted_skills TEXT NOT NULL DEFAULT '[]',
      issued_at      TEXT NOT NULL,
      revoked_at     TEXT
    )
    """,

    # -- schema_meta: migration marker -------------------------------------
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
      version    INTEGER PRIMARY KEY,
      applied_at TEXT NOT NULL
    )
    """,
)

#: LangGraph's SqliteSaver owns its own checkpoint tables and creates them
#: itself against the same connection (FR-1.8). They are intentionally absent
#: from DDL above -- the library owns that schema.
