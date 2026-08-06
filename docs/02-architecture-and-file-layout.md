# Deliverable 2 — Project Architecture & File Layout

**Reference:** `prd.md` (approved). Every path below traces to a PRD requirement.

---

## 1. Process Topology

Three user-space processes, no daemons, no containers, all on unprivileged ports.

| Process | Port | Purpose | Required |
|---|---|---|---|
| FastAPI / Uvicorn (backend) | `8787` | Pipeline, eval harness, A2A peers, all LLM traffic | Yes |
| Next.js (frontend) | `3939` | UI | Yes |
| WireMock (mock enterprise APIs) | `8181` | Ticket API, KB API, CMDB lookup | Yes |

LanceDB and SQLite are **in-process libraries**, not processes — satisfying NFR-1.1/1.4.

```
Browser ──▶ Next.js (3939) ──▶ FastAPI (8787) ──▶ LiteLLM ──▶ Gateway
                                    │
                                    ├──▶ LanceDB (embedded, ./data/lancedb)
                                    ├──▶ SQLite  (embedded, ./data/optibot.db)
                                    └──▶ WireMock (8181)
```

The browser never holds a gateway credential (NFR-2.1). The frontend's only upstream is FastAPI.

---

## 2. Repository Layout

```
OptiBot-agentic/
├── prd.md
├── startup.sh                      # Deliverable 3
├── startup.bat                     # Deliverable 3
├── .env.example
├── docs/                           # Deliverables 2–11
│
├── backend/
│   ├── requirements.txt
│   └── app/
│       ├── main.py                 # FastAPI assembly + lifespan only
│       │
│       ├── config/
│       │   ├── settings.py         # Pydantic Settings (FR-7.3)
│       │   ├── model_registry.py   # Tier→model resolution + startup probe
│       │   └── policy.py           # baseline / optimized policy objects
│       │
│       ├── api/
│       │   ├── deps.py
│       │   ├── routes_tickets.py
│       │   ├── routes_review.py
│       │   ├── routes_eval.py
│       │   ├── routes_rag.py
│       │   ├── routes_telemetry.py
│       │   ├── routes_settings.py
│       │   └── a2a/
│       │       ├── card.py         # Agent cards (FR-6.1)
│       │       ├── discovery.py    # Peer discovery (FR-6.2)
│       │       ├── auth.py         # Peer registration (FR-6.3)
│       │       ├── jsonrpc.py      # JSON-RPC task surface
│       │       └── streaming.py    # SSE task updates (FR-6.4)
│       │
│       ├── graph/
│       │   ├── state.py            # TicketState (typed)
│       │   ├── builder.py          # Graph assembly + conditional edges
│       │   └── nodes/
│       │       ├── ingest.py
│       │       ├── classify.py
│       │       ├── guardrail_pre.py
│       │       ├── retrieve.py
│       │       ├── rerank.py
│       │       ├── draft.py
│       │       ├── ground_check.py
│       │       ├── guardrail_post.py
│       │       └── route.py
│       │
│       ├── llm/
│       │   ├── client.py           # The ONLY module that calls LiteLLM
│       │   ├── tls.py              # CA-bundle-first resolution (NFR-2.2)
│       │   ├── retry.py            # Backoff + jitter + budget cap (FR-7.4)
│       │   ├── structured.py       # JSON enforcement + repair retry (FR-1.3/1.4)
│       │   └── cost.py             # Token→cost with fallback rates
│       │
│       ├── rag/
│       │   ├── chunking.py         # Fixed vs structure-aware strategies
│       │   ├── embeddings.py       # Local sentence-transformer
│       │   ├── store.py            # LanceDB open/query/upsert
│       │   ├── rerank.py
│       │   └── ingestion.py        # Document → chunks → vectors
│       │
│       ├── schemas/
│       │   ├── common.py
│       │   ├── classify.py
│       │   ├── guardrail.py
│       │   ├── draft.py            # Includes claim→chunk citations (FR-1.5)
│       │   ├── ground_check.py
│       │   ├── ticket.py
│       │   └── metrics.py
│       │
│       ├── prompts/
│       │   ├── loader.py
│       │   ├── baseline/           # Verbose, few-shot heavy
│       │   └── optimized/          # Compressed, schema-constrained
│       │
│       ├── persistence/
│       │   ├── db.py               # SQLite engine + session
│       │   ├── tables.py           # Schema definitions (Deliverable 7)
│       │   ├── runs.py             # Run repository
│       │   ├── spans.py            # Telemetry span repository
│       │   ├── reviews.py          # Human decisions (FR-2.6)
│       │   ├── llm_cache.py        # Exact + semantic cache (Deliverable 8)
│       │   └── checkpointer.py     # LangGraph SQLite checkpointer (FR-1.8)
│       │
│       ├── eval/                   # STRUCTURALLY INDEPENDENT (FR-3.6)
│       │   ├── harness.py          # Batch + live dual-arm execution
│       │   ├── metrics.py          # Derived metric computation
│       │   ├── goldset.py          # precision@k, citation coverage (FR-3.4)
│       │   ├── cache_bench.py      # Separate cache measurement (FR-3.3)
│       │   └── seed.py             # Seeded ticket set generator
│       │
│       ├── observability/
│       │   ├── logging.py          # structlog JSON config
│       │   ├── redaction.py        # Secret/PII scrubbing (FR-2.5)
│       │   ├── tracer.py           # Span emission → SQLite
│       │   └── mirror.py           # Optional Langfuse/AgentOps (NFR-3.2)
│       │
│       └── utils/
│           ├── ids.py
│           └── timing.py
│
├── frontend/                       # Deliverable 10
│   ├── package.json
│   └── src/
│       ├── app/
│       ├── components/
│       ├── lib/
│       └── styles/
│
├── mocks/wiremock/
│   ├── mappings/                   # Ticket, KB, CMDB stubs
│   └── __files/
│
├── data/                           # gitignored
│   ├── lancedb/
│   └── optibot.db
│
├── seed/
│   ├── tickets.json                # ~50 synthetic tickets
│   ├── kb_articles/                # Synthetic KB corpus
│   └── goldset.json                # Hand-labelled relevance judgements
│
└── scripts/
    ├── preflight.py                # Shared by both startup scripts
    ├── ingest_kb.py
    └── run_eval.py
```

---

## 3. Layering Rules (NFR-4.2)

Dependencies flow **downward only**. A violation is an architectural defect, not a style issue.

```
api/  ─────────┐
               ▼
eval/ ──▶  graph/  ──▶  llm/ , rag/ , prompts/
               │            │
               ▼            ▼
          persistence/ , schemas/ , observability/
                            │
                            ▼
                         config/ , utils/
```

Enforced constraints:

| Rule | Rationale |
|---|---|
| Only `llm/client.py` imports `litellm` | Single chokepoint for TLS, retry, cost, cache, telemetry (NFR-1.5) |
| Only `rag/store.py` imports `lancedb` | Single writer; enables clean shutdown (FR-7.5) |
| Only `persistence/db.py` opens SQLite connections | Prevents lock contention and corruption |
| `graph/nodes/*` never import from `api/` or `eval/` | Keeps the measured code free of measuring code |
| `eval/` imports `graph/` but **never** the reverse | FR-3.6 — measurement independence |
| Every node returns a Pydantic-validated object | FR-1.3 |

**The `eval/` ↔ `graph/` rule is the load-bearing one.** If the pipeline could see the harness, a
judge could reasonably ask whether the pipeline behaves differently when observed. It cannot.

---

## 4. How the Two Arms Share One Graph

`config/policy.py` defines a frozen `Policy` object. `builder.py` compiles **one** graph; each node
reads its behaviour from the policy in state.

```python
# config/policy.py  (shape, not implementation)
class Policy(BaseModel):
    name: Literal["baseline", "optimized"]
    model_tier_by_node: dict[str, ModelTier]
    prompt_variant: Literal["baseline", "optimized"]
    chunking: Literal["fixed_512", "structure_aware"]
    retrieval_top_k: int
    rerank_enabled: bool
    rerank_top_k: int | None
    cache_enabled: bool
    guardrails_enabled: bool
    escalation: Literal["always_human", "confidence_gated"]
```

No `if arm == "baseline"` branches inside node logic. Nodes read policy fields. This keeps nodes
small, keeps the comparison honest, and means adding a lever is a policy field rather than a code
fork.

---

## 5. File Size Discipline (NFR-4.1)

The 300–400 LOC ceiling is met by decomposition, not by compression:

- **One node per file.** Nine nodes, nine files, each well under 100 LOC.
- **One concern per `llm/` module.** TLS, retry, structured output, and cost are separate.
- **One repository per table group** in `persistence/`.
- **Prompts live in files, not code.** `prompts/baseline/` and `prompts/optimized/` hold templates
  loaded at runtime — this is what makes prompt compression a measurable, diffable lever rather
  than a code change.

Highest-risk files for the ceiling: `graph/builder.py`, `llm/client.py`, `eval/harness.py`. Each has
a designated split point documented in its own deliverable.

---

## 6. Configuration Surface

`.env.example` (validated at boot by `config/settings.py`, FR-7.3):

```
LITELLM_GATEWAY_URL=
LITELLM_API_KEY=
BACKEND_PORT=8787
FRONTEND_PORT=3939
WIREMOCK_PORT=8181
SSL_VERIFY=true                  # NFR-2.3 — defaults to enabled
REQUESTS_CA_BUNDLE=              # NFR-2.2 — tried before any bypass
DATA_DIR=./data
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
TELEMETRY_MIRROR_ENABLED=false   # NFR-3.2 — off by default
TOKEN_BUDGET_CAP=                # FR-7.4
```

Settings are runtime-mutable via `routes_settings.py` for gateway URL, key, and SSL toggle (FR-5.2),
persisted to SQLite so a restart preserves them. Everything else is boot-time only.

---

## 7. Assumptions & Risks

**Assumptions:**
1. WireMock runs as a standalone JAR under a user-space JRE. If no JRE is available, the fallback is
   a second lightweight FastAPI app serving the same stubs on `8181` — same contract, same HTTP
   surface, no change to pipeline code.
2. Ports 8787/3939/8181 are free; preflight verifies and reports clearly.
3. The sentence-transformer model can be cached locally before the demo.

**Risks:**
- `graph/builder.py` accreting policy branching over time. Mitigation: the no-branching rule in §4.
- LanceDB writer conflicts if ingestion runs concurrently with retrieval. Mitigation: single-writer
  discipline via `rag/store.py` plus a write lock during re-embedding.

**Constraint confirmation:** user-space only ✓ · unprivileged ports ✓ · embedded LanceDB + SQLite ✓ ·
backend-only LLM routing ✓ · A2A surface present ✓ · TLS handled at a single chokepoint ✓ ·
300–400 LOC ceiling structurally achievable ✓
