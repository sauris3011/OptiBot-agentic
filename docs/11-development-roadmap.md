# Deliverable 11 — Development Roadmap

**Sequencing principle:** build the **evidence path** first. The submission is scored on
demonstrable before/after improvement, so the shortest route to a real measured delta comes before
polish, and before the A2A protocol work.

---

## Milestone 0 — Skeleton That Boots

**Exit criterion:** `./startup.sh --preflight` passes on a cold clone; backend serves
`/api/health` with resolved model tiers.

- `config/settings.py`, `config/model_registry.py`, `config/policy.py`
- `persistence/db.py` + `tables.py` (all tables, empty)
- `llm/tls.py`, `llm/client.py`, `llm/retry.py`, `llm/structured.py`, `llm/cost.py`
- `observability/logging.py`, `redaction.py`, `tracer.py`
- `main.py` with lifespan (startup TLS config, shutdown flush/close)

**Why first:** the TLS posture and the model-tier probe are the two environment risks that can
invalidate everything downstream. Resolve them before writing pipeline logic, not during the demo.

---

## Milestone 1 — Knowledge Base & Retrieval

**Exit criterion:** `POST /api/rag/search` returns different, visibly better results for
`structure_aware` than for `fixed_512`.

- `seed/kb_articles/` — synthetic IT KB corpus
- `rag/chunking.py` — both strategies
- `rag/embeddings.py`, `rag/store.py`, `rag/ingestion.py`, `rag/rerank.py`
- `scripts/ingest_kb.py` — embeds the corpus under **both** strategies
- `seed/goldset.json` — hand-labelled relevance judgements

**Why second:** retrieval quality is the input to grounding, and grounding is the input to the trust
metrics. A weak corpus caps every downstream number. The gold set is built here, while the corpus is
fresh in mind, rather than retrofitted to flatter the results.

---

## Milestone 2 — The Graph

**Exit criterion:** a single ticket runs end to end under both policies and produces different,
correctly-recorded spans.

- `graph/state.py`, `schemas/*`
- `prompts/baseline/` and `prompts/optimized/`
- Nodes in order: `ingest`, `classify`, `guardrail_pre`, `retrieve`, `rerank`, `draft`,
  `ground_check`, `guardrail_post`, `route`
- `graph/builder.py` with conditional edges and `SqliteSaver`
- `persistence/runs.py`, `spans.py`

**Highest-risk item:** `ground_check`. Build and hand-verify it against known-good and
known-hallucinated drafts before trusting any downstream trust metric. If this node is wrong, the
headline hallucination number is wrong, and that is the number most likely to be probed.

---

## Milestone 3 — Evaluation Harness

**Exit criterion:** `GET /api/eval/comparison` returns a real delta over ~50 tickets. **This is the
first point at which the submission exists.**

- `eval/seed.py` — ~50 synthetic tickets
- `eval/harness.py` — dual-arm batch, cache bypassed
- `eval/metrics.py`, `eval/goldset.py`
- `api/routes_eval.py`, `routes_tickets.py`

**Decision gate.** If the optimized arm shows a quality regression alongside its cost savings, stop
and retune tier assignments before building anything else. Better to discover this here than on
stage. The likeliest culprit is `classify` on `tier3`; the fix is promoting it to `tier2`, and the
cost story survives that easily.

---

## Milestone 4 — The Dashboard

**Exit criterion:** the comparison dashboard renders the Milestone 3 numbers. **Demo-viable from
here.**

- Token system, `AppShell`, `ThemeToggle`, primitives
- `ComparisonGrid`, `MetricDeltaCard`, `CacheBypassBadge`, `AssumptionsNote`
- `LlmMonitor` + `/api/telemetry/live`
- `SettingsModal`, `SslWarningBanner`

Everything after this milestone increases the score; nothing after it is required to *have* a
submission. That is a deliberate structural safety margin against the time risk flagged in the PRD.

---

## Milestone 5 — Governance Surface

**Exit criterion:** an escalated run pauses, appears in the queue, resumes on approval, and the
audit trail shows the complete record.

- `api/routes_review.py`, `persistence/reviews.py`
- `ReviewQueue`, `EvidencePanel`, `DecisionActions`
- `AuditTrail`, `SpanTable`, `GroundingReport`
- `RagStats`, `DocumentUpload`, `RetrievalDebugger`

**Why here:** Trust & Governance is one of four evaluation lenses, and a *working* human-in-the-loop
pause is far more persuasive than a described one. The retrieval debugger lands here because it is
the visual proof behind the precision number.

---

## Milestone 6 — Caching Measured

**Exit criterion:** `POST /api/eval/cache-bench` reports hit rates and cost avoided, displayed as a
separate row on the dashboard.

- `persistence/llm_cache.py` — exact + semantic
- `eval/cache_bench.py`
- Cache statistics in the settings modal

**Why this late:** the cache must not exist during Milestones 3–4, because a half-built cache
leaking into benchmark runs would silently corrupt the baseline numbers. Building it after the
headline comparison is locked removes that risk entirely.

---

## Milestone 7 — A2A Protocol

**Exit criterion:** peer discovery, authenticated registration, and streaming task updates all
demonstrable.

- `a2a/card.py`, `discovery.py` → **shed last**
- `a2a/auth.py` → **shed second**
- `a2a/jsonrpc.py` with `input-required` for human review
- `a2a/streaming.py` → **shed first if time compresses**

Sequenced last per the Phase 1 decision. Cards, discovery, and auth carry the interoperability story
on their own; streaming is the piece to drop if the schedule tightens.

---

## Milestone 8 — Hardening

- WireMock mappings + `scripts/mock_server.py` fallback
- Graceful shutdown verification: kill mid-batch, confirm no corruption and no lost spans
- Full cold-clone run: `startup.sh` → ingest → batch eval → dashboard
- Failure-path rehearsal: gateway down, TLS failure, budget exceeded — each showing an actionable
  error
- LOC audit against the 300–400 ceiling

---

## Critical Path

```
M0 ──▶ M1 ──▶ M2 ──▶ M3 ──▶ M4          ← submission exists at M4
                            │
                            ├──▶ M5     ← governance lens
                            ├──▶ M6     ← cost lens completed
                            └──▶ M7     ← interoperability
                                 │
                                 └──▶ M8
```

M5, M6, and M7 are independent after M4 and can be reordered or parallelised by available time.
M0–M4 are strictly sequential.

---

## Risk Checkpoints

| After | Verify | If it fails |
|---|---|---|
| M0 | Model tiers resolved; TLS posture confirmed | Fall back to the 2.5 pair; escalate CA bundle to IT |
| M1 | `structure_aware` visibly beats `fixed_512` | Improve chunking before proceeding — everything downstream depends on it |
| M2 | `ground_check` correctly flags planted hallucinations | Do not proceed; the trust metric is meaningless until this is right |
| M3 | Optimized arm improves cost **without** quality regression | Retune tiers, most likely promoting `classify` |
| M4 | Dashboard renders end to end | Freeze scope; ship what works |

---

## Definition of Done

Traced to PRD §8.4:

- [ ] Cold-clone preflight passes with no admin rights
- [ ] Batch comparison renders a credible delta across cost, latency, quality, trust, and business metrics
- [ ] Live single-ticket run reproduces a delta consistent with the batch
- [ ] Escalation pauses the graph, queues, and resumes on approval
- [ ] Audit trail complete for 100% of runs
- [ ] Zero resolutions released without grounding or human approval
- [ ] A2A discovery, auth, and streaming observable
- [ ] Graceful shutdown leaves SQLite and LanceDB uncorrupted
- [ ] No file exceeds 400 LOC
