# Deliverable 5 — LiteLLM & Telemetry Integration Strategy

**Modules:** `backend/app/llm/{client,tls,retry,structured,cost}.py`, `backend/app/observability/*`

---

## 1. The Single Chokepoint

**`llm/client.py` is the only module in the codebase that imports `litellm`.** This is enforced by
convention and checkable with a one-line grep in CI.

Everything that must apply to *every* LLM call — TLS posture, retry policy, budget enforcement,
cache lookup, cost accounting, span emission, redaction — applies here, once. There is no path by
which a node can accidentally bypass telemetry or caching, because nodes cannot reach LiteLLM at all.

```
node → llm.client.complete(tier, prompt, schema, policy, ctx)
          │
          ├── 1. resolve tier → concrete model id (from data/resolved_models.json)
          ├── 2. cache lookup (skipped when policy.cache_enabled is False)
          ├── 3. budget check → TOKEN_BUDGET_EXCEEDED if exceeded
          ├── 4. litellm.completion(...) wrapped in retry
          ├── 5. structured validation + bounded repair retry
          ├── 6. cost computation
          ├── 7. span emission → SQLite (+ optional mirror)
          └── 8. cache write
        returns validated Pydantic model
```

The signature carries `policy` deliberately: **cache-enabled, model tier, and prompt variant are all
policy-driven**, which is what lets one graph serve both measurement arms.

---

## 2. Model Tier Indirection

No code anywhere references a concrete model ID. Nodes request a **tier**; `config/model_registry.py`
resolves it from `data/resolved_models.json`, written by preflight against the gateway's real model
list.

| Tier | Role | Baseline usage | Optimized usage |
|---|---|---|---|
| `tier1` | Most capable | Every node | `ground_check` only |
| `tier2` | Mid | — | `draft` |
| `tier3` | Lite | — | `classify`, `guardrail_pre`, `guardrail_post` |

This indirection is what makes the PRD §9 model-availability risk survivable: if the 3.x models are
absent, tiers collapse onto the confirmed 2.5 pair at startup, the run continues, and the
comparison remains valid — the *shape* of the optimization (spend where quality matters) is
preserved even if the specific models change.

---

## 3. TLS Handling (NFR-2.2 – 2.5)

`llm/tls.py` mirrors the preflight resolution order exactly, so what preflight validates is what
runtime uses:

```python
def configure_tls() -> TlsPosture:
    # 1. Corporate CA bundle — the correct fix, tried first
    bundle = settings.requests_ca_bundle or settings.ssl_cert_file
    if bundle and Path(bundle).exists():
        os.environ["REQUESTS_CA_BUNDLE"] = bundle
        os.environ["SSL_CERT_FILE"] = bundle
        return TlsPosture(verifying=True, mode="ca_bundle", detail=bundle)

    # 2. Explicit opt-out — verification off, loudly
    if not settings.ssl_verify:
        litellm.ssl_verify = False
        return TlsPosture(verifying=False, mode="bypass",
                          detail="MITM protection disabled for all gateway traffic")

    # 3. Default — system trust store
    return TlsPosture(verifying=True, mode="system", detail="system trust store")
```

**Design decisions and their reasons:**

- **CA bundle before bypass.** The master prompt offers the bypass directly; going straight there
  would be the easy path and the wrong one. Most corporate interception is solved correctly by
  trusting the corporate CA, which keeps verification intact. Bypass is the documented fallback.
- **`litellm.ssl_verify = False` over `NODE_TLS_REJECT_UNAUTHORIZED=0` / process-global flags.**
  It scopes the bypass to LiteLLM's client rather than disabling verification for every outbound
  request the process makes — including the optional telemetry mirror and the WireMock calls.
  Narrower blast radius for the same demo outcome.
- **`ssl_security_level = "DEFAULT@SECLEVEL=1"`** is available as a separate, milder setting for
  proxies presenting legacy ciphers. It weakens cipher requirements without disabling identity
  verification — strictly preferable to full bypass when it suffices, and tried before it.
- **Posture is returned, not just applied.** `TlsPosture` surfaces through `/api/health` and
  `/api/settings` to drive the persistent UI warning (FR-5.8). A silent bypass is the actual danger;
  a visible one is a managed risk.

**Trade-off, stated plainly:** disabling verification means the client cannot distinguish the
sanctioned corporate proxy from any other interceptor. Credentials and prompt content become
readable by anything positioned on the path. This is acceptable here because the data is synthetic
and the deployment is loopback-only. It is not acceptable in production and must never be enabled
for a path carrying real credentials or personal data.

---

## 4. Retry & Budget (FR-7.4)

`llm/retry.py`:

- Retries on `429`, `500`, `502`, `503`, `504`, and connection/timeout errors.
- **Never** retries `400`, `401`, `403` — a bad request or bad key does not improve with repetition.
- Exponential backoff with full jitter: `min(base * 2**attempt, 30s) * random()`. Jitter matters
  because the batch evaluation issues many concurrent calls; unjittered backoff would resynchronise
  them into a thundering herd.
- Honours `Retry-After` when the gateway supplies it.
- Max attempts from `LLM_MAX_RETRIES` (default 4).

**Token budget cap.** A process-lifetime counter checked before every call. On breach, calls raise
`TOKEN_BUDGET_EXCEEDED` rather than proceeding. Rationale: a retry storm during an unattended batch
evaluation is exactly how a hackathon quota disappears. The cap makes that failure loud and bounded.

**Retries are counted, not hidden.** Retry count and total retry latency are recorded per span and
reported as a reliability metric — the baseline arm's higher schema-violation rate produces more
repair retries, and that cost belongs in the comparison.

---

## 5. Structured Output Enforcement (FR-1.3, FR-1.4)

`llm/structured.py`:

1. Request JSON mode with the Pydantic model's JSON Schema attached.
2. Parse and validate against the model.
3. **On failure — one bounded repair retry**: resend with the raw output and the specific validation
   error appended, asking for correction. Exactly one attempt; unbounded repair loops are a cost
   sink.
4. On second failure — deterministic fallback (a safe default object, e.g. lowest-confidence
   classification), the run is flagged, and it is routed to human review.

**Every outcome increments a counter.** `schema_violation_rate` is a headline before/after metric
(PRD §8.2): the baseline's verbose unpinned prompts produce measurably more malformed JSON than the
optimized arm's schema-constrained ones. This is one of the cleanest quality deltas in the demo
because it is objectively countable — no judge model, no interpretation.

---

## 6. Cost Accounting

`llm/cost.py` computes cost from token counts and a rate table, in priority order:

1. Rates from LiteLLM's model cost map when the model is known.
2. Configured override rates.
3. **Documented fallback rates** for unknown models (FR-5.1), with the response flagged
   `cost_estimated: true`.

The header monitor and the comparison dashboard both display the estimate flag rather than
presenting an approximation as exact. Cost credibility depends on being explicit about which
numbers are measured and which are inferred.

---

## 7. Telemetry (NFR-3.1, NFR-3.2)

**SQLite is authoritative.** Every span is written synchronously to SQLite within the call. The UI,
the audit trail, and the before/after report read exclusively from SQLite.

**The SaaS mirror is optional and non-blocking.** `observability/mirror.py` forwards spans to
Langfuse or AgentOps when `TELEMETRY_MIRROR_ENABLED=true`, on a background task with a short
timeout and swallowed exceptions.

Reason: behind an intercepting proxy, an outbound SaaS call may hang or fail. If telemetry were
primary, the demo would be hostage to the corporate network. Making SQLite authoritative means a
blocked mirror costs you a dashboard you were not going to demo anyway, and costs the actual
submission nothing.

**Span fields:** `run_id`, `node`, `tier`, `resolved_model`, `tokens_in/out`, `cost_usd`,
`cost_estimated`, `latency_ms`, `cache_status`, `retry_count`, `schema_valid`, `repair_attempted`,
`policy`, `timestamp`.

---

## 8. Constraint Confirmation

Backend-only LLM routing, single chokepoint ✓ · client never sees a gateway key ✓ ·
CA-bundle-before-bypass with narrow-scope fallback ✓ · TLS posture visible in UI ✓ ·
backoff with jitter plus hard budget cap ✓ · strict JSON with bounded repair ✓ ·
SQLite authoritative, SaaS optional ✓ · every module single-purpose and well under the LOC ceiling ✓
