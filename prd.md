# OptiBot — Product Requirements Document

**Version:** 1.0
**Status:** Draft — pending approval
**Date:** 2026-08-06
**Source documents:** `genai_workflow_optimization_hackathon_problem_statement.md`, `AAgentic-development-master-prompt.md`
**Phase 1 decision record:** `.claude/plans/aagentic-development-master-prompt-md-quiet-corbato.md`

> **CRITICAL RULE:** Once approved, this document is the strict reference guide. All subsequent
> code generation, API design, schema definitions, and file layouts must align perfectly with the
> requirements established here. Deviations require an amendment to this document first.

---

## 1. Product Vision & Problem Statement

### 1.1 Problem

Enterprises deploy GenAI workflows that *work* but are not *governed*. A typical first-generation
internal assistant sends every request to the most capable available model, wraps it in a bloated
hand-tuned prompt, retrieves context with naive fixed-size chunking, validates nothing, caches
nothing, and logs nothing beyond an application error trace.

The result is predictable and well documented in the hackathon problem statement: unnecessary token
spend, inconsistent response quality, hallucinations presented with unwarranted confidence, no audit
trail, no human oversight gate, and — most damaging to continued investment — **no ability to prove
whether the system is getting better or worse.**

The organisation cannot answer the question its finance and risk functions actually ask: *what did
this cost, what did it get right, and how do you know?*

### 1.2 Vision

**OptiBot is an IT Service Desk triage assistant that is also its own measurement instrument.**

It resolves or escalates incoming support tickets using retrieval-grounded generation with
enforced guardrails and human oversight. Critically, it ships with a **built-in evaluation harness
that runs the identical workflow under two policy regimes — `baseline` and `optimized` — and
reports the delta across cost, latency, quality, trust, and governance dimensions.**

The product thesis: *an optimized GenAI workflow is not one that produces better answers; it is one
that can demonstrate it produces better answers, and show what that improvement cost.*

### 1.3 Why This Matters

The hackathon is scored on before/after evidence. Most submissions will demonstrate an AI that
works. OptiBot demonstrates an AI that **proves its own improvement under conditions a skeptic
would accept** — same graph, same tickets, cache disabled during measurement, baseline and
optimized arms differing only in declared policy.

---

## 2. Target Audience & Personas

| Persona | Role | Primary Need | How OptiBot Serves Them |
|---|---|---|---|
| **Priya — L1 Service Desk Agent** | Front-line ticket handler | Resolve more tickets per shift without guessing at policy | Receives drafted, citation-backed resolutions; reviews and approves rather than researching from scratch |
| **Marcus — Service Desk Manager** | Owns SLA and staffing | Reduce MTTR and backlog; justify headcount | Deflection rate, handling time, and human-review rate on the comparison dashboard |
| **Dana — AI Platform Owner** | Runs the GenAI platform | Control spend; prevent quality regressions | Per-run token/cost telemetry, model routing controls, cache hit rates, schema violation rate |
| **Raj — Risk & Compliance Officer** | Approves AI for production use | Auditability, grounding evidence, human oversight | Immutable run log, claim-level citations, unsupported-claim escalation gate, guardrail decisions |
| **Judging Panel** | Hackathon evaluator | Credible, verifiable before/after evidence | Batch comparison dashboard plus a live single-ticket run that reproduces the batch delta |

**Primary persona for the demo narrative:** Marcus and Dana jointly — the business metric and the
IT metric, which is precisely the stated business goal.

---

## 3. User Stories & Core Workflows

### 3.1 User Stories

**Ticket resolution**
- As Priya, I submit a ticket and receive a drafted resolution with inline citations to specific KB
  articles, so I can verify the answer before sending it.
- As Priya, when the system cannot ground a claim, I want it escalated to me rather than sent, so I
  am never asked to defend an answer the system invented.
- As Priya, I want to approve or reject a drafted resolution in one action, and have my decision
  recorded.

**Measurement and optimization**
- As Dana, I run a batch evaluation across a fixed ticket set under both policy regimes and see the
  cost, latency, and quality delta.
- As Dana, I run a single ticket live through both arms to confirm the batch numbers are real.
- As Dana, I adjust the LLM gateway URL, key, and SSL verification without restarting the system.
- As Dana, I see cumulative token consumption and estimated cost in the header at all times.

**Governance**
- As Raj, I inspect any completed run and see every LLM call it made: model, tokens, latency,
  cache status, guardrail verdicts, and retrieved chunks.
- As Raj, I confirm that no resolution reached a user without either full grounding or human
  approval.

**Knowledge management**
- As Marcus, I upload new KB documents and see them embedded and reflected in retrieval statistics.
- As Dana, I re-embed the corpus under a different chunking strategy and compare retrieval
  precision before and after.

### 3.2 Core Workflow — Ticket Triage (Happy Path)

1. Ticket arrives (WireMock ticket API, or manual submission via UI).
2. **ingest** — normalise into typed `TicketState`; assign run ID; open telemetry span.
3. **classify** — category, urgency, and intent extracted as validated JSON.
4. **guardrail_pre** — prompt-injection and PII screening. Fail → quarantine, escalate, stop.
5. **retrieve** — semantic search over LanceDB KB corpus.
6. **rerank** — narrow candidates to the highest-relevance set (optimized arm only).
7. **draft** — compose a resolution constrained to retrieved context, emitting claim→chunk mappings.
8. **ground_check** — verify every claim maps to a retrieved chunk; emit `unsupported_claim_count`.
9. **guardrail_post** — output safety and policy screening.
10. **Conditional route:**
    - `unsupported_claim_count == 0` **and** confidence ≥ threshold → **auto_resolve**
    - otherwise → **human_review** (graph pauses at checkpoint)
11. Run record, all spans, and metrics persist to SQLite.

### 3.3 Core Workflow — Human-in-the-Loop Review

1. Escalated run appears in the review queue with draft, citations, and the reason for escalation.
2. Priya reviews grounded evidence alongside the draft.
3. Approve → resolution finalised, graph resumes to completion. Reject → run closed as rejected,
   with reason captured.
4. Decision, reviewer identity, and timestamp are written to the immutable run log.

### 3.4 Core Workflow — Before/After Evaluation

1. Dana triggers batch evaluation over the seeded ticket set (~50 tickets).
2. Harness executes each ticket through `baseline`, then `optimized`. **Cache is bypassed for
   both arms.**
3. Every run's metrics land in SQLite.
4. Dashboard renders paired metrics with computed deltas and percentage change.
5. Dana triggers a live single-ticket comparison; the observed delta is consistent with the batch.
6. Separately, cache effectiveness is measured by replaying traffic **with cache enabled** and
   reported as its own metric — never folded into the headline optimization delta.

---

## 4. AI & System Architecture

### 4.1 Agent Topology

A **supervised linear pipeline with conditional branches**, implemented as a single LangGraph with
a typed `TicketState`. Role-delegating multi-agent crews were rejected: non-deterministic step
counts make token comparisons unreproducible, which defeats the product's core purpose.

```
ingest → classify → guardrail_pre → retrieve → rerank → draft
       → ground_check → guardrail_post → { auto_resolve | human_review }
```

**Both measurement arms execute this same graph.** Only the injected policy object differs. Separate
baseline and optimized codebases would permit the objection that the baseline is a strawman; a
shared graph makes the comparison structurally honest.

### 4.2 Policy Regimes

| Lever | `baseline` | `optimized` |
|---|---|---|
| Model routing | Most capable model at every node | Tiered by node role |
| Prompts | Verbose, few-shot heavy, unpinned | Compressed, schema-constrained |
| Chunking | Fixed 512 tokens, no metadata | Structure-aware, metadata-enriched |
| Retrieval | top-k = 10, no rerank | top-k = 10 → rerank → top-k = 3 |
| Cache | Disabled | Exact + semantic |
| Guardrails | None | Pre, post, and ground_check |
| Escalation | Always human | Confidence + grounding gated |

### 4.3 Model Mapping

| Node | `baseline` | `optimized` | Rationale |
|---|---|---|---|
| classify | Tier-1 (most capable) | Tier-3 (lite) | Constrained-label classification; a lite model suffices |
| guardrail_pre / post | Tier-1 | Tier-3 | Binary safety verdicts |
| draft | Tier-1 | Tier-2 (mid) | Quality-sensitive but heavily context-constrained |
| ground_check | Tier-1 | **Tier-1 (retained)** | Trust-critical; deliberately not downgraded |

Tier-1/2/3 resolve to concrete gateway models at startup via the model-list probe (§7.4). Retaining
the most capable model on the trust-critical node is intentional and central to the narrative:
optimization means **spending where quality matters**, not cutting uniformly.

### 4.4 RAG Strategy

- **Vector store:** LanceDB, in-process against a local directory. No daemon, no port.
- **Embeddings:** local sentence-transformer, in-process. Zero gateway cost, zero TLS exposure,
  free re-embedding when comparing chunking strategies.
- **Grounding scope:** applied at `retrieve`, `draft`, and `ground_check`. The master prompt's §5
  universal-injection rule was formally retired in Phase 1 as not applicable to this use case.
- **Citations:** every generated claim carries a chunk-level reference. A claim without one is by
  definition an unsupported claim and triggers escalation.
- **Retrieval quality measurement:** precision@k and citation coverage scored against a small
  hand-labelled gold set.

### 4.5 Structured Output

Every LLM boundary returns strict JSON validated by a Pydantic schema before entering graph state.
On validation failure: one bounded repair retry, then a deterministic fallback. **Schema violation
rate is a first-class reliability metric**, charted before/after.

### 4.6 Interoperability (A2A)

Full A2A protocol support: agent cards, discovery, authenticated peer registration, and streaming
task updates. Two peers — the **triage pipeline** and the **evaluator** — communicate over the
protocol. This doubles as the architectural boundary guaranteeing that measurement code stays
independent of the code being measured.

---

## 5. Functional Requirements

### 5.1 Triage Pipeline

| ID | Requirement |
|---|---|
| FR-1.1 | Accept tickets via REST endpoint and via WireMock-served ticket API |
| FR-1.2 | Execute the full graph with a selectable policy regime (`baseline` \| `optimized`) |
| FR-1.3 | Validate every LLM response against a Pydantic schema before state entry |
| FR-1.4 | Apply one bounded repair retry, then a deterministic fallback, on validation failure |
| FR-1.5 | Emit claim→chunk citation mappings for every drafted resolution |
| FR-1.6 | Compute `unsupported_claim_count` at `ground_check` |
| FR-1.7 | Route to `human_review` when unsupported claims exist or confidence is below threshold |
| FR-1.8 | Persist a LangGraph checkpoint at `human_review` and resume on decision |

### 5.2 Guardrails & Governance

| ID | Requirement |
|---|---|
| FR-2.1 | Pre-generation screening for prompt injection and PII |
| FR-2.2 | Post-generation screening for output safety and policy compliance |
| FR-2.3 | Quarantine and escalate on any guardrail failure; never silently continue |
| FR-2.4 | Record an immutable run log: every LLM call, model, tokens, latency, cache status, guardrail verdict, retrieved chunk IDs |
| FR-2.5 | Redact secrets and PII automatically from all structured logs |
| FR-2.6 | Capture reviewer identity, decision, reason, and timestamp on every human review |

### 5.3 Evaluation Harness

| ID | Requirement |
|---|---|
| FR-3.1 | Batch-execute a seeded ticket set (~50) through both arms, cache bypassed |
| FR-3.2 | Execute a single ticket live through both arms on demand, cache bypassed |
| FR-3.3 | Measure cache effectiveness separately, with cache enabled, on replayed traffic |
| FR-3.4 | Score retrieval precision@k and citation coverage against a labelled gold set |
| FR-3.5 | Persist all paired results to SQLite for instant dashboard load |
| FR-3.6 | Exist as a module structurally independent of the pipeline it measures |

### 5.4 Metrics Captured Per Run

Input tokens, output tokens, estimated cost, end-to-end latency, per-node latency, model used per
node, cache hit/miss, schema violation count, `unsupported_claim_count`, retrieval precision@k,
citation coverage, human-review triggered (bool), guardrail verdicts, and derived business metrics:
deflection rate, average handling time, MTTR proxy.

### 5.5 Mandated UI Elements

| ID | Requirement |
|---|---|
| FR-5.1 | **Global header LLM monitor** — active call count, cumulative input/output tokens, estimated cost (LiteLLM fallback rates when the model is unknown) |
| FR-5.2 | **Settings gear modal** — configure gateway URL, port, and API key; iOS-style toggle for "Disable SSL Verification"; live cache hit/miss statistics |
| FR-5.3 | **RAG grounding panel** — embedding statistics, dynamic document upload and re-embed, chunking-strategy selection |
| FR-5.4 | **Before/After comparison view** — paired metrics with deltas and percentage change across all dimensions |
| FR-5.5 | **Human review queue** — pending escalations with draft, citations, escalation reason, approve/reject |
| FR-5.6 | **Run inspector** — full audit trail for any completed run |
| FR-5.7 | **Theme toggle** — explicit light/dark via CSS variables and semantic tokens |
| FR-5.8 | Active visual warning whenever SSL verification is disabled |

### 5.6 A2A Endpoints

| ID | Requirement |
|---|---|
| FR-6.1 | Serve a spec-compliant agent card for each peer |
| FR-6.2 | Support peer discovery |
| FR-6.3 | Support authenticated peer registration |
| FR-6.4 | Support streaming task status updates |

### 5.7 Operations

| ID | Requirement |
|---|---|
| FR-7.1 | Cross-platform startup scripts (`startup.sh`, `startup.bat`) |
| FR-7.2 | Preflight: venv, Python version, Node version, env vars, DB directory writability, port availability, gateway reachability, model-list probe, embedding model cache — each failing fast with a distinct, actionable message |
| FR-7.3 | Boot-time environment validation via Pydantic settings schema |
| FR-7.4 | Exponential backoff with jitter on 429/5xx, under a hard token budget cap |
| FR-7.5 | Graceful SIGINT/SIGTERM: flush spans, close SQLite, release LanceDB writers |

---

## 6. Non-Functional Requirements

### 6.1 Environment (Non-Negotiable)

| ID | Requirement |
|---|---|
| NFR-1.1 | User-space execution only — zero Docker, zero root/admin, zero system-wide daemons |
| NFR-1.2 | Python 3.x via `venv`; Node.js 22.x for the Next.js frontend |
| NFR-1.3 | All local servers bind unprivileged ports (> 1024) |
| NFR-1.4 | All storage local, file-based, and embedded in-process |
| NFR-1.5 | All LLM traffic routes through LiteLLM on the backend; the client never contacts the gateway |

### 6.2 Security & Trust

| ID | Requirement |
|---|---|
| NFR-2.1 | Gateway credentials remain server-side; never exposed to the browser |
| NFR-2.2 | Startup attempts the corporate CA bundle (`REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE`) **before** any TLS bypass |
| NFR-2.3 | TLS verification defaults to **enabled**, with explicit opt-out only |
| NFR-2.4 | Disabled verification surfaces an active, persistent UI warning |
| NFR-2.5 | All data is synthetic and anonymized; no real personal information enters the system |

**TLS trade-off, stated explicitly:** disabling certificate verification removes MITM protection
wholesale — it cannot distinguish the sanctioned corporate proxy from any other interceptor.
This is acceptable for a sandboxed prototype operating on synthetic data. It is **not** acceptable
in production, and must never be enabled for any path handling real credentials or personal data.

### 6.3 Observability

| ID | Requirement |
|---|---|
| NFR-3.1 | SQLite is the authoritative telemetry store; UI and reports read only from it |
| NFR-3.2 | SaaS telemetry (Langfuse/AgentOps) is an optional mirror behind a feature flag; its failure degrades observability without breaking the system |
| NFR-3.3 | Structured JSON logging for every agent action and LLM call, with automatic secret/PII redaction |

### 6.4 Code Quality

| ID | Requirement |
|---|---|
| NFR-4.1 | Hard ceiling of 300–400 lines per file |
| NFR-4.2 | Strict separation of concerns: agents/tools, API & A2A routes, RAG services, prompts & schemas, persistence & cache, shared utilities |
| NFR-4.3 | Composition over monolithic design; simplest architecture satisfying all constraints |

### 6.5 Performance

| ID | Requirement |
|---|---|
| NFR-5.1 | Comparison dashboard loads from pre-computed SQLite results without live LLM calls |
| NFR-5.2 | Live single-ticket dual-arm comparison completes within a demo-acceptable window |
| NFR-5.3 | Token budget cap prevents retry storms from silently consuming spend |

---

## 7. Out of Scope (Anti-Goals)

Explicitly excluded to prevent scope creep:

1. **Production authentication and RBAC.** A single demo identity. A2A peer auth is in scope; end-user identity management is not.
2. **Real ITSM integration.** WireMock only. No ServiceNow/Jira/Zendesk connectors.
3. **Multi-tenancy.** Single-tenant, single-user.
4. **Model fine-tuning or training.** Optimization is achieved through routing, prompting, retrieval, and caching — not weight updates.
5. **Horizontal scale, HA, clustering.** Single-process, single-machine by constraint.
6. **Real personal or customer data.** Synthetic only.
7. **Conversational multi-turn chat.** Ticket-in / resolution-out. Chat would reintroduce the non-determinism that undermines measurement.
8. **Automated ticket closure in a real system.** `auto_resolve` marks a resolution ready; it does not write back to a system of record.
9. **Mobile-native applications.** Responsive web only.
10. **Cost optimization beyond the LLM layer.** No infrastructure or compute cost modelling.

---

## 8. Success Metrics

### 8.1 Product Success (Business Lens)

| Metric | Target |
|---|---|
| Deflection rate (auto-resolved without human review) | Materially higher in `optimized`, with grounding intact |
| Average handling time per ticket | Measurable reduction |
| MTTR proxy | Measurable reduction |
| Human-review rate | Reduced, while unsupported-claim escalations remain at 100% capture |

### 8.2 Technical Success (IT Lens)

| Metric | Target |
|---|---|
| Cost per ticket | Substantial reduction, cache bypassed |
| Total tokens per ticket | Substantial reduction, cache bypassed |
| End-to-end latency | Reduction |
| Schema violation rate | Reduction toward zero |
| `unsupported_claim_count` | Reduction toward zero |
| Retrieval precision@k | Improvement |
| Citation coverage | Improvement |
| Cache hit rate (measured separately) | Reported honestly as a distinct steady-state figure |

### 8.3 Governance Success (Trust Lens)

| Metric | Target |
|---|---|
| Runs with complete audit trail | 100% |
| Resolutions released without grounding **or** human approval | 0 |
| Guardrail failures silently continuing | 0 |
| Human decisions recorded with reviewer, reason, timestamp | 100% |

### 8.4 Demonstration Success

- Preflight passes from a cold clone with no admin rights.
- Batch comparison dashboard renders a credible, statistically meaningful delta.
- Live single-ticket run reproduces a delta consistent with the batch.
- An escalation visibly pauses the graph, appears in the queue, and resumes on approval.
- A2A peer discovery, authentication, and streaming updates are observable.
- Graceful shutdown leaves SQLite and LanceDB uncorrupted.

---

## 9. Known Risks

| Risk | Impact | Mitigation |
|---|---|---|
| `gemini-3.5-flash` / `gemini-3.1-flash-lite` unconfirmed on the gateway | Model tiering fails at demo time | Startup model-list probe fails fast with a clear message; tiering falls back to the confirmed 2.5 pair |
| Full A2A spec competes with dashboard build time | Scoring-critical path at risk | A2A built only after the comparison dashboard is functional; streaming sheds first if time compresses |
| Corporate network blocks the embedding model download | RAG unavailable | Preflight detects and reports explicitly; model cached ahead of the demo |
| Optimized arm shows quality regression alongside cost savings | Undermines the narrative | `ground_check` and gold-set scoring surface this early; tier assignment is tunable per node |
| Cache warming inflates the optimized arm | Judges reject the numbers | Cache bypassed during all benchmark runs; effectiveness reported as a separate metric |

---

## 10. Approval

This PRD requires explicit approval before Deliverable 2 (project architecture and file layout) and
any code generation proceeds.

| | |
|---|---|
| **Prepared by** | AI Software Architect |
| **Status** | Awaiting approval |
