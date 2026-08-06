# Deliverable 9 — Logging & Observability Strategy

**Modules:** `backend/app/observability/{logging,redaction,tracer,mirror}.py`

---

## 1. Three Distinct Channels

These are often conflated, which is why observability requirements are usually half-met. They are
kept separate here because they have different consumers, retention needs, and failure tolerances.

| Channel | Store | Consumer | If it fails |
|---|---|---|---|
| **Spans** | SQLite `spans` | Dashboard, audit trail, metrics | System is broken — this is the product |
| **Logs** | stdout, JSON lines | Developer debugging | Degraded debuggability only |
| **Mirror** | Langfuse / AgentOps | Optional external view | No impact — off by default |

The span channel is not "monitoring." It is the deliverable: the before/after evidence *is* the span
data aggregated.

---

## 2. Spans (NFR-3.1)

Written **synchronously** to SQLite inside `llm/client.py` before the call returns. Not batched, not
async, not fire-and-forget.

Reason: a crash mid-batch must leave every completed run measurable. Async batching risks losing the
tail of a run — and the tail is where failures cluster, which is exactly the data worth keeping. The
write cost is negligible against LLM latency; at ~1ms per span against ~500ms per call it is
invisible.

Every span carries `run_id`, and `run_id` appears in the API response, the SSE stream, the log
lines, and the audit view. One identifier correlates everything.

**Rollup on completion.** Span aggregates are written to the `runs` row when a run finishes
(Deliverable 7 §2.1), so dashboard reads never aggregate span tables (NFR-5.1).

---

## 3. Structured Logging (NFR-3.3)

`structlog`, JSON lines to stdout, bound context so `run_id`, `policy`, and `node` appear on every
line within a run without being passed explicitly.

```json
{"ts":"2026-08-06T09:14:22.481Z","level":"info","event":"llm_call_complete",
 "run_id":"run_7f2a","policy":"optimized","node":"draft","tier":"tier2",
 "model":"gemini/gemini-2.5-flash","tokens_in":842,"tokens_out":211,
 "latency_ms":1204,"cache_status":"miss","retry_count":0,"schema_valid":true}
```

Required fields on every agent action and LLM call, per the master prompt §3: latency, token usage,
model used, cache hit/miss — all present above.

`LOG_FORMAT=console` switches to human-readable output for local development. JSON is the default so
logs are machine-parseable without a second code path.

---

## 4. Redaction (FR-2.5)

`observability/redaction.py` applies to logs, spans, and mirror payloads alike — a single processor
in the pipeline rather than three separate call sites, because a redaction rule applied in two of
three places is a leak.

| Pattern | Action |
|---|---|
| API keys, bearer tokens | Replace with `[REDACTED:key]` |
| Email addresses | Hash, retain domain (`[EMAIL:acme.com]`) — supports grouping without exposure |
| IP addresses | Mask final octet |
| Employee/ticket identifiers | Retained — synthetic, and needed for correlation |
| Prompt bodies | **Never logged in full.** `prompt_hash` only |
| Model responses | Truncated preview in logs; full text only in the `runs` record the audit view reads |

**Prompts are hashed, not stored.** This removes the largest PII surface entirely rather than trying
to scrub it. The hash still supports reproducibility verification and cache correlation, which is
everything the prompt text was needed for.

Domain-preserving email hashing is a deliberate middle path: full redaction destroys the ability to
notice that all failures came from one tenant; full retention is a compliance problem.

---

## 5. Optional SaaS Mirror (NFR-3.2)

Off by default. When `TELEMETRY_MIRROR_ENABLED=true`, spans forward to Langfuse or AgentOps on a
background task with a 2-second timeout and swallowed exceptions.

The failure mode this guards against is specific: behind an intercepting proxy, an outbound SaaS
call can hang rather than fail fast. If telemetry were on the critical path, every LLM call would
inherit that hang, and the demo would stall for reasons unrelated to the system being demonstrated.

Mirror failures increment a counter surfaced in the settings modal — degraded silently is still
degraded, so it is visible even though it is non-fatal.

---

## 6. The Audit Trail (FR-2.4)

`GET /api/runs/{run_id}/audit` assembles the complete governance record for one run:

- Ticket input and classification
- Every LLM call: node, tier, resolved model, tokens, cost, latency, cache status, retry count,
  schema validity
- Retrieved `chunk_ids` with the text that was actually retrieved
- Guardrail verdicts, pre and post
- Every claim with its cited chunk and the grounding verdict
- Routing decision and its reason
- Human decision with reviewer, reason, and timestamp
- Corpus version, prompt version, policy, and cache posture

This satisfies the PRD §8.3 target of 100% of runs having a complete audit trail, and it is what
Raj (Risk & Compliance) opens. It answers three questions a compliance reviewer actually asks:
*what did it say, what evidence did it have, and who approved it.*

Because spans are append-only and `reviews` has no update path, the record cannot be revised after
the fact.

---

## 7. Live Telemetry Feed (FR-5.1)

`GET /api/telemetry/live` (SSE) drives the persistent header monitor:

```
event: telemetry data: {"active_calls":2,"tokens_in":184203,"tokens_out":41882,
                        "cost_usd":0.4127,"cost_estimated":false,
                        "cache_hits":38,"cache_misses":112}
```

Counters are process-lifetime, held in memory and reconciled against SQLite on reconnect so a page
refresh does not reset them. `cost_estimated` propagates the fallback-rate flag from Deliverable 5
§6 — the header shows an estimate marker rather than presenting an inferred number as measured.

---

## 8. What Is Deliberately Not Built

- **No OpenTelemetry / OTLP exporter.** It implies a collector, which implies a daemon. Excluded by
  NFR-1.1.
- **No log shipping or rotation.** stdout captured to `logs/` by the startup scripts. Demo lifetime
  does not warrant more.
- **No alerting.** No one is on call for a hackathon prototype.
- **No distributed tracing.** Single process. `run_id` correlation is sufficient and simpler.

Each exclusion follows from the zero-admin constraint or from the prototype's actual lifespan.
Building them would add operational surface with no demonstrable value.

**Constraint confirmation:** structured JSON logging on every agent action and LLM call ✓ ·
latency, tokens, model, cache status recorded ✓ · automatic secret/PII redaction across all three
channels ✓ · SQLite authoritative ✓ · SaaS mirror optional and non-blocking ✓ · complete immutable
audit trail per run ✓ · zero additional daemons ✓
