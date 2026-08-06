# Deliverable 8 — Caching Strategy

**Module:** `backend/app/persistence/llm_cache.py`, invoked only from `llm/client.py`

---

## 1. The Governing Rule

**The cache is bypassed during every benchmark run** (FR-3.1, FR-3.2), and its value is measured
**separately** with cache enabled (FR-3.3).

This is the single most important decision in the deliverable, and it costs headline numbers to
make. If baseline runs first and warms the cache, the optimized arm replays it and reports near-zero
cost and near-zero latency. That number is an artifact of run order, not of optimization, and any
reviewer who asks "did you run them in the same session?" will find it.

So the comparison reports two honest figures instead of one inflated one:

1. **Optimization delta** — cache off in both arms. Attributable entirely to routing, prompting, and
   retrieval.
2. **Cache effectiveness** — measured on its own, reported as steady-state hit rate and the
   incremental saving on repeat traffic.

The API returns `cache_bypassed: true` as data in the comparison payload (Deliverable 4 §2.3), and
the UI displays it. The claim is auditable, not asserted.

---

## 2. Two-Tier Cache

### Tier 1 — Exact match

Key: `sha256(resolved_model + prompt_text + schema_name + temperature + max_tokens)`.

Every component matters. Omitting the model would serve a `tier3` response to a `tier1` request;
omitting the schema would serve a classification where a draft was requested. Sub-millisecond
lookup by primary key.

### Tier 2 — Semantic match

On an exact miss, embed the prompt with the same local sentence-transformer used for RAG (already
loaded, so no extra cost or dependency) and search cached prompt embeddings for cosine similarity
above threshold.

**Similarity threshold: 0.97, deliberately conservative.**

Reasoning: for service desk tickets, "cannot connect to VPN" and "cannot connect to VPN**N**" are
near-identical vectors and legitimately share an answer, while "reset my password" and "reset my
MFA token" sit closer in embedding space than their answers do. A loose threshold turns the cache
into a hallucination source — and it would be a hallucination the grounding check cannot catch,
because the cached answer *is* well-grounded, just for a different question.

A cache miss costs tokens. A wrong cache hit costs trust. The threshold is set accordingly, and it
is configurable and logged so the trade-off is inspectable rather than hidden.

**Semantic matching is restricted to `classify` and `guardrail_*` nodes.** `draft` and
`ground_check` use exact matching only. A drafted resolution is ticket-specific; serving a
near-neighbour's resolution would put unverified content in front of a user under the guise of a
grounded answer. The nodes where semantic reuse is safe are precisely the ones producing constrained
labels rather than prose.

---

## 3. Node-Level Cache Policy

| Node | Exact | Semantic | Rationale |
|---|---|---|---|
| `classify` | Yes | Yes (0.97) | Constrained label set; near-duplicates share a class |
| `guardrail_pre` | Yes | Yes (0.97) | Binary safety verdict on similar input |
| `draft` | Yes | **No** | Ticket-specific prose; near-miss reuse is unsafe |
| `ground_check` | Yes | **No** | Must verify *this* draft against *these* chunks |
| `guardrail_post` | Yes | **No** | Must screen actual generated output |

Corpus version is folded into the key for retrieval-dependent nodes: re-indexing invalidates
affected entries automatically, so a stale cache cannot mask a retrieval change.

---

## 4. Why SQLite Rather Than LiteLLM Disk Cache

LiteLLM ships a disk cache that would satisfy the raw requirement. SQLite was chosen because:

1. **Hit/miss statistics are queryable.** FR-5.2 requires live ratios in the settings modal, and
   §8.2 requires cache hit rate as a reported metric. An opaque disk cache would need parallel
   bookkeeping.
2. **Cache state joins to run state.** `cache_status` per span, correlated to `run_id`, is what
   makes the audit trail complete and lets `cache_bypassed` be proven per run rather than claimed.
3. **One store, one shutdown path.** SQLite already holds state, spans, checkpoints, and audit.
   Adding a second persistence mechanism means a second corruption surface at shutdown (FR-7.5) for
   no benefit.
4. **The master prompt explicitly sanctions SQLite's dual purpose** — application state plus
   persistent prompt/response pairs.

Trade-off accepted: slightly more code than enabling a library flag. Bought: full observability of
the cache, which is a deliverable rather than an implementation detail.

---

## 5. Invalidation

| Trigger | Scope |
|---|---|
| Corpus re-index | Entries keyed to the old `corpus_version` |
| Prompt template change | Entries keyed to the old `prompt_version` |
| Model tier re-resolution | Entries for the previously resolved model |
| Manual flush (settings modal) | All |
| TTL | None — the demo lifetime is short; entries are evicted by version change, not by age |

No TTL is intentional. Version-based invalidation is precise; time-based invalidation would evict
valid entries mid-demo and add unexplained variance to the numbers.

---

## 6. What Gets Measured

`POST /api/eval/cache-bench` (FR-3.3):

1. Run the seeded ticket set with cache **enabled**, cold cache → records misses and true cost.
2. Replay a realistic repeat-traffic mix (duplicates and near-duplicates, reflecting real service
   desk patterns where the same issues recur).
3. Report:

| Metric | Meaning |
|---|---|
| Exact hit rate | Identical repeat requests served from cache |
| Semantic hit rate | Near-duplicate requests served from cache |
| Cost avoided | Tokens not spent, priced at the resolved model's rate |
| Latency avoided | Mean saved per hit |
| Semantic near-miss count | Above 0.90 but below threshold — shows what conservatism costs |

The last row is included on purpose. It quantifies what the safety margin costs, so the threshold
choice is presented as a defensible trade-off rather than an unexamined default.

**Constraint confirmation:** embedded SQLite dual-purpose ✓ · benchmark integrity preserved by
bypass ✓ · cache value reported honestly and separately ✓ · semantic reuse restricted to safe nodes ✓ ·
version-based invalidation ✓ · live hit/miss stats available to the settings modal ✓
