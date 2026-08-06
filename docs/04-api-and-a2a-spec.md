# Deliverable 4 — Backend API Architecture & A2A Endpoint Specs

**Base URL:** `http://127.0.0.1:8787`
**Reference:** `prd.md` FR-1.x, FR-2.x, FR-3.x, FR-5.x, FR-6.x

---

## 1. API Design Principles

1. **The browser never contacts the LLM gateway** (NFR-1.5). Every LLM interaction is server-side.
2. **Every response body is a Pydantic model.** No ad-hoc dicts cross the API boundary.
3. **Long-running work streams.** Pipeline runs and batch evaluations emit SSE progress; the UI never
   polls blindly.
4. **Read paths never trigger LLM calls.** The comparison dashboard reads pre-computed SQLite rows
   (NFR-5.1), so it loads instantly and costs nothing.
5. **`run_id` is the universal correlation key** across API responses, spans, logs, and the audit
   trail.

---

## 2. REST Surface

### 2.1 Tickets & Pipeline — `routes_tickets.py`

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/tickets` | Submit a ticket for triage. Body: `{ticket, policy: "baseline"\|"optimized"}`. Returns `run_id` immediately. |
| `GET` | `/api/tickets/inbox` | Fetch open tickets from the WireMock ticket API (FR-1.1) |
| `GET` | `/api/runs/{run_id}` | Full run record: state, draft, citations, routing decision |
| `GET` | `/api/runs/{run_id}/stream` | **SSE** — per-node progress as the graph executes |
| `GET` | `/api/runs/{run_id}/audit` | Complete audit trail: every LLM call, model, tokens, latency, cache status, guardrail verdict, retrieved chunk IDs (FR-2.4, FR-5.6) |
| `GET` | `/api/runs` | Paginated run list with filters (policy, outcome, date) |

**SSE event sequence** for `/api/runs/{run_id}/stream`:

```
event: node_start   data: {"node":"classify","model":"gemini/gemini-2.5-flash"}
event: node_end     data: {"node":"classify","latency_ms":412,"tokens_in":180,"tokens_out":24,"cache":"miss"}
...
event: routed       data: {"decision":"human_review","reason":"unsupported_claims","count":2}
event: run_complete data: {"run_id":"...","total_cost_usd":0.0031,"total_latency_ms":4820}
```

### 2.2 Human Review — `routes_review.py`

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/review/queue` | Pending escalations with draft, citations, escalation reason (FR-5.5) |
| `POST` | `/api/review/{run_id}/decision` | Body: `{decision: "approve"\|"reject", reason, reviewer}`. Resumes the paused LangGraph checkpoint (FR-1.8) |
| `GET` | `/api/review/history` | Decisions with reviewer, reason, timestamp (FR-2.6) |

The decision endpoint is the **resume trigger**. The graph genuinely pauses at a SQLite checkpoint;
this is not a simulated approval step.

### 2.3 Evaluation — `routes_eval.py`

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/eval/batch` | Run the seeded set through both arms, cache bypassed (FR-3.1). Returns `batch_id` |
| `GET` | `/api/eval/batch/{batch_id}/stream` | **SSE** — per-ticket progress |
| `GET` | `/api/eval/comparison` | **The headline endpoint.** Paired metrics with deltas and % change (FR-5.4) |
| `POST` | `/api/eval/live` | Single ticket through both arms, cache bypassed (FR-3.2) |
| `POST` | `/api/eval/cache-bench` | Cache effectiveness, measured separately with cache enabled (FR-3.3) |
| `GET` | `/api/eval/goldset` | Retrieval precision@k and citation coverage (FR-3.4) |

`GET /api/eval/comparison` response shape:

```jsonc
{
  "sample_size": 50,
  "cache_bypassed": true,          // asserted in the payload, not just in docs
  "metrics": [
    { "key": "cost_per_ticket_usd", "baseline": 0.0412, "optimized": 0.0067,
      "delta": -0.0345, "pct_change": -83.7, "direction": "lower_is_better" },
    { "key": "unsupported_claim_rate", "baseline": 0.22, "optimized": 0.02,
      "delta": -0.20, "pct_change": -90.9, "direction": "lower_is_better" }
    // ... tokens, latency, schema_violation_rate, precision_at_k,
    //     citation_coverage, deflection_rate, handling_time_s
  ]
}
```

`cache_bypassed` is returned as data so the UI can display it as an assertion to the judging panel.

### 2.4 RAG — `routes_rag.py`

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/rag/stats` | Chunk count, dimension, corpus version hash, active chunking strategy (FR-5.3) |
| `POST` | `/api/rag/documents` | Upload and embed a document |
| `POST` | `/api/rag/reindex` | Re-embed the corpus under a named chunking strategy |
| `POST` | `/api/rag/search` | Debug retrieval — returns chunks and scores without generating |

`/api/rag/search` exists for the demo: it shows *why* the optimized arm retrieves better, rather
than asking the audience to take the precision number on faith.

### 2.5 Telemetry & Settings

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/telemetry/live` | **SSE** — active call count, cumulative tokens, running cost (FR-5.1) |
| `GET` | `/api/telemetry/cache` | Hit/miss ratios (FR-5.2) |
| `GET` | `/api/settings` | Current config. **API key returned masked, never in full** |
| `PATCH` | `/api/settings` | Update gateway URL, port, key, SSL toggle. Persisted to SQLite |
| `POST` | `/api/settings/test` | Probe the gateway with the supplied settings before committing |
| `GET` | `/api/health` | Liveness plus resolved model tiers and TLS posture |

`GET /api/settings` returns `ssl_verify` so the UI can render the persistent warning banner
required by FR-5.8.

---

## 3. A2A Protocol Surface (FR-6.x)

Two peers, both served by the same FastAPI process on distinct route prefixes. They are separate
**protocol identities**, which is what enforces the measurement-independence boundary of FR-3.6.

| Peer | Prefix | Role |
|---|---|---|
| `optibot-triage` | `/a2a/triage` | Executes ticket triage |
| `optibot-evaluator` | `/a2a/evaluator` | Scores runs; drives dual-arm comparison |

### 3.1 Agent Cards (FR-6.1)

`GET /a2a/{peer}/.well-known/agent-card.json`

```jsonc
{
  "name": "optibot-triage",
  "description": "IT service desk ticket triage with grounded resolution and human escalation",
  "version": "1.0.0",
  "url": "http://127.0.0.1:8787/a2a/triage",
  "capabilities": { "streaming": true, "pushNotifications": false },
  "authentication": { "schemes": ["bearer"] },
  "defaultInputModes": ["application/json"],
  "defaultOutputModes": ["application/json"],
  "skills": [
    { "id": "triage_ticket",
      "name": "Triage Ticket",
      "description": "Classify, ground, draft, and route an IT support ticket",
      "inputModes": ["application/json"], "outputModes": ["application/json"] }
  ]
}
```

The evaluator card advertises `score_run` and `compare_arms`.

### 3.2 Discovery (FR-6.2)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/a2a/discovery/peers` | All known peers with cards and liveness |
| `POST` | `/a2a/discovery/resolve` | Resolve a peer URL to its agent card |

### 3.3 Authenticated Registration (FR-6.3)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/a2a/auth/register` | Register a peer; returns a bearer token bound to peer identity |
| `POST` | `/a2a/auth/revoke` | Revoke a token |

Tokens are stored hashed in SQLite with issue time, peer identity, and granted skills. Every
`/a2a/*` task call requires a valid bearer token; unauthenticated calls receive `401`. Every
authentication event is written to the audit log — peer-to-peer traffic is as auditable as user
traffic (FR-2.4).

### 3.4 Task Execution (JSON-RPC 2.0)

`POST /a2a/{peer}/rpc`

```jsonc
{ "jsonrpc": "2.0", "id": "req-1", "method": "message/send",
  "params": { "message": { "role": "user",
                           "parts": [{ "kind": "data",
                                       "data": { "skill": "triage_ticket",
                                                 "ticket": { "...": "..." },
                                                 "policy": "optimized" } }] } } }
```

Response carries a `Task` with `id`, `status` (`submitted` → `working` → `input-required` |
`completed` | `failed`), and `artifacts`.

**`input-required` is how A2A expresses human review.** When the graph escalates, the task enters
`input-required` rather than completing — the protocol state machine and the graph's pause state
are the same thing, not two parallel mechanisms.

### 3.5 Streaming (FR-6.4)

`POST /a2a/{peer}/rpc` with `method: "message/stream"` returns SSE:

```
event: task_status_update    data: {"taskId":"...","status":"working","node":"retrieve"}
event: task_artifact_update  data: {"taskId":"...","artifact":{...}}
event: task_status_update    data: {"taskId":"...","status":"input-required","reason":"unsupported_claims"}
```

---

## 4. Error Handling

Uniform envelope on every non-2xx:

```jsonc
{ "error": { "code": "GATEWAY_UNREACHABLE",
             "message": "LLM gateway did not respond within 30s",
             "remediation": "Check the gateway URL in Settings, or run startup.sh --preflight",
             "run_id": "..." } }
```

| Code | HTTP | Meaning |
|---|---|---|
| `GATEWAY_UNREACHABLE` | 502 | Gateway down or unroutable |
| `GATEWAY_TLS_FAILURE` | 502 | Certificate verification failed — remediation names the CA bundle fix |
| `SCHEMA_VALIDATION_FAILED` | 422 | Repair retry exhausted (FR-1.4) |
| `GUARDRAIL_BLOCKED` | 403 | Pre/post guardrail rejected the content (FR-2.3) |
| `TOKEN_BUDGET_EXCEEDED` | 429 | Hard cap reached (FR-7.4) |
| `MODEL_TIER_UNRESOLVED` | 503 | Startup probe found no served model for a tier |

Every error carries `remediation`. An error the user cannot act on is an incomplete error.

---

## 5. Module Size Control (NFR-4.1)

Seven route modules plus five A2A modules, each single-purpose and comfortably under 200 LOC.
`api/deps.py` holds shared dependencies (DB session, policy resolution, auth) so route handlers stay
thin — handlers validate, delegate, and serialize; they contain no business logic.

**Constraint confirmation:** backend-only LLM routing ✓ · A2A discovery + auth + streaming ✓ ·
audit trail on every run and every peer call ✓ · dashboard reads cost nothing ✓ · every error
actionable ✓
