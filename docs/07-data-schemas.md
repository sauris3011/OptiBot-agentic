# Deliverable 7 — LanceDB & SQLite Schema Definitions

**Modules:** `backend/app/persistence/tables.py`, `backend/app/rag/store.py`
**Files on disk:** `data/optibot.db` (SQLite), `data/lancedb/` (LanceDB)

---

## 1. LanceDB — Vector Store

Single table `kb_chunks`, opened in-process. No daemon, no port (NFR-1.1, NFR-1.4).

| Column | Type | Purpose |
|---|---|---|
| `chunk_id` | string (PK) | Stable ID; **cited by every generated claim** |
| `vector` | fixed_size_list<float32, 384> | all-MiniLM-L6-v2 embedding |
| `text` | string | Chunk content |
| `doc_id` | string | Source document |
| `doc_title` | string | Display + citation label |
| `section` | string | Heading path, e.g. `VPN > Troubleshooting > MFA` |
| `chunk_index` | int32 | Ordinal within document |
| `category` | string | KB category — **metadata filter, optimized arm only** |
| `product` | string | Affected system |
| `strategy` | string | `fixed_512` or `structure_aware` |
| `corpus_version` | string | Hash of (documents + strategy + model) |
| `token_count` | int32 | Retrieved-context accounting |

### 1.1 Both chunking strategies coexist

`strategy` and `corpus_version` are columns, not separate tables. Both strategies are embedded and
stored simultaneously; retrieval filters by the strategy the active policy names.

This is what makes the retrieval comparison honest and instant: the two arms query the **same
table** under the same code path, differing only in a filter predicate. No re-indexing between arms,
so no possibility that one arm benefits from a fresher index. The RAG panel can switch strategies
live without a rebuild.

### 1.2 Retrieval by arm

| | `baseline` | `optimized` |
|---|---|---|
| Filter | `strategy = 'fixed_512'` | `strategy = 'structure_aware'` AND `category = <classified>` |
| top-k | 10 | 10 → rerank → 3 |

The metadata filter is only available to the optimized arm because `fixed_512` chunks carry no
meaningful `category` — the naive strategy discards structure. The advantage is a real consequence
of better ingestion, not a handicap imposed on the baseline.

### 1.3 Single-writer discipline

`rag/store.py` is the only module importing `lancedb`. A process-level write lock is held during
ingestion and re-indexing, so retrieval never races a writer. Shutdown releases the writer
explicitly (FR-7.5) — abrupt termination mid-write is the realistic corruption path.

---

## 2. SQLite — State, Audit, Cache, Checkpoints

`data/optibot.db`, WAL mode, opened once by `persistence/db.py`.

### 2.1 `runs` — one row per pipeline execution

```sql
CREATE TABLE runs (
  run_id            TEXT PRIMARY KEY,
  batch_id          TEXT,                    -- NULL for ad-hoc runs
  ticket_id         TEXT NOT NULL,
  policy            TEXT NOT NULL,           -- 'baseline' | 'optimized'
  cache_bypassed    INTEGER NOT NULL,        -- asserted per run, not assumed
  corpus_version    TEXT NOT NULL,
  prompt_version    TEXT NOT NULL,
  status            TEXT NOT NULL,           -- running|completed|failed|awaiting_review|quarantined
  decision          TEXT,                    -- auto_resolve|human_review|quarantine
  decision_reason   TEXT,
  -- rolled up from spans for fast dashboard reads (NFR-5.1)
  tokens_in         INTEGER DEFAULT 0,
  tokens_out        INTEGER DEFAULT 0,
  cost_usd          REAL    DEFAULT 0,
  cost_estimated    INTEGER DEFAULT 0,
  latency_ms        INTEGER,
  llm_call_count    INTEGER DEFAULT 0,
  retry_count       INTEGER DEFAULT 0,
  schema_violations INTEGER DEFAULT 0,
  unsupported_claims INTEGER,
  citation_coverage REAL,
  precision_at_k    REAL,
  started_at        TEXT NOT NULL,
  completed_at      TEXT
);
CREATE INDEX idx_runs_batch_policy ON runs(batch_id, policy);
CREATE INDEX idx_runs_ticket       ON runs(ticket_id);
```

Metrics are **rolled up onto the run row** as well as living in spans. Denormalisation is
deliberate: the comparison dashboard must render without aggregating thousands of span rows
(NFR-5.1). Spans remain the authoritative detail for the audit trail.

`cache_bypassed` and both version columns are stored per run so any historical comparison can prove
the conditions it ran under. A number without its conditions is not evidence.

### 2.2 `spans` — one row per LLM call or instrumented node (FR-2.4)

```sql
CREATE TABLE spans (
  span_id        TEXT PRIMARY KEY,
  run_id         TEXT NOT NULL REFERENCES runs(run_id),
  parent_span_id TEXT,
  node           TEXT NOT NULL,
  kind           TEXT NOT NULL,      -- llm | retrieval | rerank | deterministic
  tier           TEXT,
  resolved_model TEXT,
  tokens_in      INTEGER,
  tokens_out     INTEGER,
  reasoning_tokens INTEGER NOT NULL DEFAULT 0,   -- billed as output, absent from the body
  cost_usd       REAL,
  cost_estimated INTEGER DEFAULT 0,
  latency_ms     INTEGER NOT NULL,
  cache_status   TEXT,               -- hit_exact | hit_semantic | miss | bypassed
  retry_count    INTEGER DEFAULT 0,
  schema_valid   INTEGER,
  repair_attempted INTEGER DEFAULT 0,
  guardrail_verdict TEXT,
  chunk_ids      TEXT,               -- JSON array — grounding evidence
  prompt_hash    TEXT,               -- hash only; never raw prompt text
  error_code     TEXT,
  created_at     TEXT NOT NULL
);
CREATE INDEX idx_spans_run ON spans(run_id);
```

`prompt_hash` rather than prompt text: it gives reproducibility verification and cache correlation
without persisting content that redaction would then have to police (FR-2.5).

`reasoning_tokens` is separated from `tokens_out` because the two behave differently. Reasoning
tokens are billed but invisible in the response, and they are the dominant term in the tier cost
gap (measured 575–717 on tier1 versus 0 on tier3 for the same classification). Folding them into
`tokens_out` would still price correctly but would hide *why* the optimized arm is cheaper — which
is the one thing the comparison exists to explain.

### 2.3 `reviews` — human decisions (FR-2.6)

```sql
CREATE TABLE reviews (
  review_id       TEXT PRIMARY KEY,
  run_id          TEXT NOT NULL REFERENCES runs(run_id),
  reviewer        TEXT NOT NULL,
  decision        TEXT NOT NULL,     -- approve | reject
  reason          TEXT,
  escalation_cause TEXT NOT NULL,    -- unsupported_claims | low_confidence | policy | guardrail
  created_at      TEXT NOT NULL
);
```

Append-only. No `UPDATE` or `DELETE` path exists in `persistence/reviews.py` — the audit trail is
immutable by construction rather than by policy.

### 2.4 `llm_cache` — see Deliverable 8

```sql
CREATE TABLE llm_cache (
  cache_key    TEXT PRIMARY KEY,     -- sha256(model + prompt + schema + params)
  prompt_embedding BLOB,             -- for semantic matching
  response_json TEXT NOT NULL,
  tokens_in    INTEGER, tokens_out INTEGER, cost_usd REAL,
  model        TEXT NOT NULL,
  hit_count    INTEGER DEFAULT 0,
  created_at   TEXT NOT NULL,
  last_hit_at  TEXT
);
```

### 2.5 Supporting tables

| Table | Purpose |
|---|---|
| `batches` | Batch eval metadata: `batch_id`, sample size, cache posture, corpus/prompt versions, timestamps |
| `goldset` | `ticket_id`, `relevant_chunk_ids` (JSON) — hand-labelled, drives precision@k and citation coverage (FR-3.4) |
| `settings` | Runtime-mutable config (gateway URL, key **encrypted at rest**, SSL toggle); survives restart |
| `a2a_peers` | Peer identity, agent card URL, **hashed** token, granted skills, issued/revoked timestamps (FR-6.3) |
| `checkpoints` | LangGraph `SqliteSaver` tables — created and owned by the library (FR-1.8) |
| `documents` | `doc_id`, title, source, uploaded_at, chunk counts per strategy |

---

## 3. Metric Derivation

Business metrics (PRD §8.1) are computed from stored data, never entered by hand:

| Metric | Derivation |
|---|---|
| Deflection rate | `COUNT(decision='auto_resolve') / COUNT(*)` per policy |
| Handling time | `AVG(latency_ms)` + a fixed per-ticket human review cost constant |
| MTTR proxy | Handling time weighted by the escalation rate |
| Cost per ticket | `AVG(cost_usd)` per policy |
| Schema violation rate | `SUM(schema_violations) / SUM(llm_call_count)` |
| Unsupported claim rate | `AVG(unsupported_claims > 0)` |
| Cache hit rate | From `spans.cache_status`, **only over non-bypassed runs** |

The human review cost constant is a stated, visible assumption in the UI — not buried in a query.
Judges should be able to challenge the assumption and see the number move.

---

## 4. Integrity & Shutdown

WAL mode for concurrent reads during writes. Foreign keys enforced. Single connection owned by
`persistence/db.py`. Graceful shutdown commits, checkpoints WAL, and closes (FR-7.5).

Both stores live under `DATA_DIR`, verified writable by preflight, and are fully disposable —
deleting `data/` and re-running ingestion plus batch eval reproduces the entire demo from `seed/`.

**Constraint confirmation:** embedded and file-based ✓ · no daemons ✓ · SQLite dual-purpose
(state + cache) ✓ · audit trail immutable ✓ · no raw prompts or PII persisted ✓ · dashboard reads
are single-table ✓
