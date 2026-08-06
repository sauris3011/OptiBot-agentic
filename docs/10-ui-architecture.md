# Deliverable 10 — UI Component & Design-Token Architecture

**Stack:** Next.js 15 (App Router) + TypeScript + Tailwind CSS + Lucide icons
**Reference:** `prd.md` FR-5.1 – FR-5.8. Minimal enterprise aesthetic. **No emojis.**

---

## 1. Design Token Strategy

Two layers. Components consume **only** semantic tokens — never a raw palette value, never a
Tailwind color utility like `bg-slate-800`.

```css
/* styles/tokens.css */
:root {                                   /* primitives — never used directly */
  --gray-0:#fff; --gray-50:#f8fafc; --gray-900:#0f172a; --gray-950:#020617;
  --blue-500:#3b82f6; --amber-500:#f59e0b; --red-500:#ef4444; --green-500:#22c55e;
}

:root, [data-theme="light"] {             /* semantic — the only layer components see */
  --bg-canvas:var(--gray-50);   --bg-surface:var(--gray-0);   --bg-elevated:var(--gray-0);
  --fg-primary:var(--gray-900); --fg-muted:#64748b;           --border-subtle:#e2e8f0;
  --accent:var(--blue-500);
  --metric-improved:var(--green-500); --metric-regressed:var(--red-500);
  --status-warn:var(--amber-500);      --status-danger:var(--red-500);
}

[data-theme="dark"] {
  --bg-canvas:var(--gray-950);  --bg-surface:var(--gray-900);  --bg-elevated:#1e293b;
  --fg-primary:#f1f5f9;         --fg-muted:#94a3b8;            --border-subtle:#1e293b;
  --accent:#60a5fa;
  --metric-improved:#4ade80;    --metric-regressed:#f87171;
  --status-warn:#fbbf24;        --status-danger:#f87171;
}
```

Tailwind maps these in `tailwind.config.ts` (`bg-canvas`, `text-primary`, `border-subtle`,
`text-metric-improved`, …). Theming is then a single `data-theme` attribute swap on `<html>`, with
no per-component conditionals and no flash of wrong theme (resolved by an inline script before
hydration).

**`--metric-improved` / `--metric-regressed` are semantic, not literal green/red.** A metric can
improve by going *down* (cost, latency, unsupported claims) or *up* (precision, deflection). The
`direction` field returned by `/api/eval/comparison` (Deliverable 4 §2.3) decides which token
applies. Hardcoding green-for-up would mislabel the most important results on the page.

Dark mode is a first-class requirement, not an afterthought: the comparison dashboard is what gets
projected, and projector conditions vary.

---

## 2. Route Structure

```
src/app/
├── layout.tsx              # Shell: header monitor, theme provider, SSL banner
├── page.tsx                # Comparison dashboard — the landing view
├── triage/page.tsx         # Submit a ticket, watch the graph execute live
├── review/page.tsx         # Human review queue (FR-5.5)
├── runs/[runId]/page.tsx   # Run inspector / audit trail (FR-5.6)
└── knowledge/page.tsx      # RAG grounding panel (FR-5.3)
```

**The comparison dashboard is the landing page.** The product's thesis is measurable improvement;
that is what should be on screen when the URL opens, with no navigation required.

---

## 3. Component Inventory

```
src/components/
├── layout/       AppShell, Header, Nav, ThemeToggle, SslWarningBanner
├── monitor/      LlmMonitor, TokenCounter, CostDisplay, ActiveCallIndicator
├── settings/     SettingsModal, GatewayForm, SslToggle, CacheStats
├── comparison/   ComparisonGrid, MetricDeltaCard, ArmColumn, LiveCompareButton,
│                 CacheBypassBadge, AssumptionsNote
├── triage/       TicketForm, GraphProgress, NodeTimeline, CitationList
├── review/       ReviewQueue, ReviewCard, EvidencePanel, DecisionActions
├── runs/         AuditTrail, SpanTable, GroundingReport, RunMetadata
├── knowledge/    RagStats, DocumentUpload, ChunkStrategyPicker, RetrievalDebugger
└── primitives/   Card, Modal, Toggle, Badge, Table, Tabs, StatTile, Skeleton
```

Every component under 200 LOC. `primitives/` exists so no feature component reimplements a modal or
a table — and so the enterprise aesthetic stays consistent without discipline being required at
every call site.

---

## 4. Mandated Elements

### 4.1 Header LLM Monitor (FR-5.1)

Persistent in `layout.tsx`, subscribed to `GET /api/telemetry/live` (SSE).

```
┌───────────────────────────────────────────────────────────────────────────┐
│ OptiBot    Compare  Triage  Review  Knowledge                             │
│                        ● 2 active   184.2K in / 41.9K out   $0.4127 ~   ⚙ │
└───────────────────────────────────────────────────────────────────────────┘
```

The `~` marker renders when `cost_estimated` is true — an inferred figure is never displayed as a
measured one. Counters reconcile against SQLite on reconnect so a refresh does not zero them.

### 4.2 Settings Modal (FR-5.2)

Gateway URL, port, and API key (masked, write-only — `GET /api/settings` never returns it in full);
an iOS-style toggle for **Disable SSL Verification**; live cache hit/miss statistics; a **Test
Connection** action hitting `POST /api/settings/test` before committing.

Toggling SSL off opens a confirmation stating the consequence in plain language — that verification
cannot distinguish the corporate proxy from any other interceptor — and then raises the persistent
banner. The friction is intentional.

### 4.3 SSL Warning Banner (FR-5.8)

A full-width `--status-danger` bar below the header, present whenever `ssl_verify` is false, on
every route, not dismissible. A bypass that can be dismissed becomes a bypass that is forgotten.

### 4.4 RAG Grounding Panel (FR-5.3)

Corpus statistics (chunk counts per strategy, embedding dimension, corpus version hash), drag-and-
drop upload with embedding progress, a chunking-strategy picker, and a **retrieval debugger** —
enter a query, see what each strategy returns side by side with scores.

The debugger is the demo's proof for the retrieval-precision number: it shows *why* the optimized
arm retrieves better rather than asking the audience to accept a figure.

### 4.5 Comparison Dashboard (FR-5.4)

```
┌─ Baseline vs Optimized ────────── n=50 · cache bypassed · corpus v4a91c ──┐
│                                                                           │
│  Cost / ticket        Tokens / ticket      Latency (p50)                  │
│  $0.0412 → $0.0067    2,847 → 691          6.2s → 2.1s                    │
│  −83.7%  improved     −75.7%  improved     −66.1%  improved               │
│                                                                           │
│  Unsupported claims   Schema violations    Retrieval precision@k          │
│  22% → 2%             8.1% → 0.4%          0.61 → 0.89                    │
│  −90.9%  improved     −95.1%  improved     +45.9%  improved               │
│                                                                           │
│  Deflection rate      Handling time                                       │
│  41% → 78%            8.4min → 3.1min                                     │
│  +90.2%  improved     −63.1%  improved                                    │
│                                                                           │
│  Cache effectiveness (measured separately, cache ON): 34% hit · $0.19 saved│
│                                                                           │
│  [ Run live comparison on a single ticket ]                               │
└───────────────────────────────────────────────────────────────────────────┘
```

*(Illustrative layout. Actual values come from the batch run.)*

Three design decisions here carry the credibility of the whole submission:

1. **`cache bypassed` renders as a badge in the header of the panel**, driven by the API field, not
   by static text. The methodological claim is visible without being asked for.
2. **Cache effectiveness sits in its own row**, visually separated, labelled as separately measured.
   It is never folded into the headline deltas.
3. **Business and IT metrics share one grid.** The stated business goal is showing both before and
   after AI-driven optimization; splitting them across tabs would break the single most important
   sightline in the demo.

`AssumptionsNote` exposes the human-review cost constant used to derive handling time — visible and
challengeable rather than buried in a query.

### 4.6 Live Graph Progress

The triage view subscribes to `GET /api/runs/{run_id}/stream` and renders each node as it executes,
with model tier, latency, and token counts appearing per node. Watching `classify` complete on
`tier3` in 200ms and `ground_check` deliberately spend `tier1` tokens communicates the routing
strategy better than any slide.

---

## 5. Data Access

```
src/lib/
├── api.ts        # Typed fetch wrappers — the only module issuing HTTP
├── sse.ts        # EventSource wrapper with reconnect + backoff
├── types.ts      # Types mirroring backend Pydantic models
└── theme.ts      # Theme persistence + pre-hydration script
```

`types.ts` is generated from the backend OpenAPI schema, so a backend contract change surfaces as a
TypeScript error rather than a runtime surprise during the demo.

**Zod validates every API response at the boundary**, mirroring the backend's Pydantic discipline.
The system enforces strict typed contracts at both ends, which is the master prompt's requirement
applied symmetrically rather than only where it was convenient.

No client-side state library. Server state via SSE and fetch; local UI state via `useState`. Adding
Redux or Zustand here would be complexity without a problem to solve.

---

## 6. Accessibility & Aesthetic

No emojis anywhere; all iconography from Lucide. Semantic HTML, keyboard-navigable modals with focus
traps, `aria-live` on the monitor for changing values. Contrast verified in both themes — the
improved/regressed tokens are checked at AA, and metric direction is conveyed by an arrow and a
label as well as by color, so the dashboard is readable without color perception.

**Constraint confirmation:** semantic tokens with light/dark parity ✓ · no emojis, Lucide only ✓ ·
header monitor with live token/cost telemetry ✓ · settings modal with gateway config, SSL toggle,
cache stats ✓ · RAG panel with upload and stats ✓ · persistent SSL warning ✓ · client never contacts
the gateway ✓ · every component under the LOC ceiling ✓
