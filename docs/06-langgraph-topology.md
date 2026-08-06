# Deliverable 6 — LangGraph Topology & Workflow Definition

**Modules:** `backend/app/graph/{state,builder}.py`, `backend/app/graph/nodes/*.py`

---

## 1. Graph

```
                        ┌──────────┐
                        │  ingest  │
                        └────┬─────┘
                             ▼
                        ┌──────────┐
                        │ classify │
                        └────┬─────┘
                             ▼
                     ┌───────────────┐   blocked   ┌──────────────┐
                     │ guardrail_pre ├────────────▶│  quarantine  │──▶ END
                     └───────┬───────┘             └──────────────┘
                             ▼ pass
                        ┌──────────┐
                        │ retrieve │
                        └────┬─────┘
                             ▼
                        ┌──────────┐   (skipped when policy.rerank_enabled is False)
                        │  rerank  │
                        └────┬─────┘
                             ▼
                        ┌──────────┐
                        │  draft   │
                        └────┬─────┘
                             ▼
                     ┌──────────────┐
                     │ ground_check │
                     └──────┬───────┘
                            ▼
                    ┌────────────────┐  blocked  ┌──────────────┐
                    │ guardrail_post ├──────────▶│  quarantine  │──▶ END
                    └───────┬────────┘           └──────────────┘
                            ▼ pass
                        ┌───────┐
                        │ route │
                        └───┬───┘
                  ┌─────────┴─────────┐
                  ▼                   ▼
          ┌──────────────┐    ┌──────────────┐
          │ auto_resolve │    │ human_review │  ◀── interrupt (SQLite checkpoint)
          └──────┬───────┘    └──────┬───────┘
                 │                   │ resume on decision
                 ▼                   ▼
                END                 END
```

**One graph, two arms.** `builder.py` compiles this once. Behaviour differences between `baseline`
and `optimized` come entirely from the `Policy` object carried in state.

---

## 2. State

```python
class TicketState(TypedDict):
    # Identity
    run_id: str
    policy: Policy                    # frozen; drives every node's behaviour

    # Input
    ticket: Ticket

    # Node outputs (each Pydantic-validated before entry)
    classification: Classification | None
    guardrail_pre: GuardrailVerdict | None
    retrieved: list[Chunk]
    reranked: list[Chunk] | None
    draft: Draft | None               # includes claim -> chunk_id citations
    grounding: GroundingReport | None
    guardrail_post: GuardrailVerdict | None

    # Routing
    decision: Literal["auto_resolve", "human_review", "quarantine"] | None
    decision_reason: str | None

    # Human-in-the-loop
    review: ReviewDecision | None

    # Accumulated metrics (append-only)
    spans: list[SpanRef]
```

State is append-only per node. No node mutates a prior node's output — this keeps the audit trail
truthful and makes any run reconstructible from its spans alone.

---

## 3. Nodes

| Node | LLM | Tier (baseline → optimized) | Output schema | Purpose |
|---|---|---|---|---|
| `ingest` | No | — | `Ticket` | Normalise, assign `run_id`, open root span |
| `classify` | Yes | tier1 → **tier3** | `Classification` | Category, urgency, intent |
| `guardrail_pre` | Yes | tier1 → **tier3** | `GuardrailVerdict` | Prompt injection, PII |
| `retrieve` | No | — | `list[Chunk]` | LanceDB semantic search |
| `rerank` | No | — | `list[Chunk]` | Cross-encoder narrowing (optimized only) |
| `draft` | Yes | tier1 → **tier2** | `Draft` | Resolution + claim→chunk citations |
| `ground_check` | Yes | tier1 → **tier1 (retained)** | `GroundingReport` | Verify every claim maps to a chunk |
| `guardrail_post` | Yes | tier1 → **tier3** | `GuardrailVerdict` | Output safety/policy |
| `route` | No | — | — | Deterministic branch |

**Only five nodes call an LLM.** `retrieve`, `rerank`, and `route` are deterministic code. That is
itself an optimization: the baseline's habit of asking a model to do work that arithmetic can do is
a real and common enterprise failure, and replacing it is measurable.

`route` being deterministic is deliberate — an LLM deciding whether to escalate would be
unauditable and non-reproducible. The escalation gate is code:

```python
def route(state) -> str:
    if state["grounding"].unsupported_claim_count > 0:
        return "human_review"
    if state["policy"].escalation == "always_human":
        return "human_review"
    if state["draft"].confidence < CONFIDENCE_THRESHOLD:
        return "human_review"
    return "auto_resolve"
```

---

## 4. `ground_check` — the load-bearing node

This single node produces the trust metric, the governance control, and the escalation gate.

`draft` is required to emit each claim with a `chunk_id`. `ground_check` then verifies, per claim,
that the cited chunk actually supports it — catching both uncited claims and *miscited* ones, where
a citation exists but does not say what the draft asserts. The second case is the more dangerous
hallucination in practice, because it survives a superficial "has citations" check.

```python
class GroundingReport(BaseModel):
    claims: list[ClaimVerdict]        # {claim, chunk_id, supported: bool, rationale}
    unsupported_claim_count: int
    citation_coverage: float          # fraction of claims with a supporting chunk
```

`unsupported_claim_count > 0` forces human review. **No resolution reaches a user unless it is
fully grounded or a human approved it** (PRD §8.3). This is a structural guarantee of the graph, not
a policy someone must remember to apply.

`ground_check` keeps `tier1` in the optimized arm. Downgrading the node that detects hallucinations
in order to save tokens would be optimizing away the thing being optimized for.

---

## 5. Human-in-the-Loop (FR-1.8)

`human_review` is a LangGraph `interrupt`. The graph state persists to a SQLite checkpoint and
execution genuinely stops.

```python
graph = builder.compile(
    checkpointer=SqliteSaver(conn),
    interrupt_before=["human_review"],
)
```

Resume path: `POST /api/review/{run_id}/decision` → decision written to `reviews` table →
`graph.update_state(...)` → `graph.invoke(None, config)` continues to `END`.

The A2A task state machine reflects this natively as `input-required` (Deliverable 4 §3.4). The
protocol state and the graph state are the same fact, not two mechanisms kept in sync.

---

## 6. No Branching on Arm Name

**Rule: no node contains `if policy.name == "baseline"`.** Nodes read policy *fields*.

```python
# graph/nodes/retrieve.py  — correct
chunks = store.search(query, top_k=state["policy"].retrieval_top_k)

# wrong — forbidden
if state["policy"].name == "baseline":
    chunks = store.search(query, top_k=10)
else:
    chunks = store.search(query, top_k=3)
```

Two reasons. It keeps nodes small (NFR-4.1). More importantly, it keeps the comparison defensible:
with no arm-name branching, there is no code path that exists only to make the baseline look bad.
A reviewer can verify this with a single grep, which is a stronger assurance than a claim in a
slide.

Adding a new optimization lever means adding a `Policy` field, not forking a node.

---

## 7. Failure Handling

| Failure | Behaviour |
|---|---|
| Schema validation exhausted | Deterministic fallback, run flagged, forced to `human_review` |
| Guardrail blocked | Straight to `quarantine`; never silently continues (FR-2.3) |
| Retrieval returns nothing | `draft` receives empty context; every claim is then unsupported; escalates |
| Gateway unreachable after retries | Run marked `failed`, partial spans retained, error surfaced with remediation |
| Token budget exceeded | Run halts, partial state checkpointed, batch reports how far it got |

Every failure path terminates in either a human or a recorded, inspectable failure. Nothing fails
open.

---

## 8. Determinism for Measurement

To make the comparison reproducible: `temperature=0` on every node, fixed seed on the ticket set,
pinned prompt templates (file-based, version-hashed), corpus version hash recorded per run, and
cache bypassed during benchmarking.

A run is therefore reproducible to the limits of gateway non-determinism, and any residual variance
is attributable to the model rather than to the harness. When a judge asks "would you get the same
numbers again," the answer is yes, and the reason is structural.

**Constraint confirmation:** deterministic reproducible topology ✓ · one graph two arms, no arm
branching ✓ · only 5 of 9 nodes use an LLM ✓ · escalation gate is auditable code ✓ · genuine
checkpointed HITL ✓ · nothing fails open ✓ · one node per file, all well under the LOC ceiling ✓
