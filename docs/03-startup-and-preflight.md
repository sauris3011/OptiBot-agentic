# Deliverable 3 — Startup Automation & Preflight

**Artifacts:** `startup.sh`, `startup.bat`, `scripts/preflight.py`, `.env.example`

---

## 1. Design Principle

**A failed demo must fail at second 5, not minute 5.** Every environmental assumption is verified
before a single process starts, and each failure produces one distinct, actionable sentence naming
the fix.

`scripts/preflight.py` deliberately uses **only the Python standard library**, so it runs on bare
CPython before `pip install` has happened. A missing dependency then produces a clear preflight
message rather than an import traceback.

---

## 2. Startup Sequence

Both scripts follow an identical seven-step sequence:

| Step | Action | Failure Mode |
|---|---|---|
| 1 | Create/activate `.venv` | Abort — Python not installed or not on PATH |
| 2 | Install backend deps (stamped; skipped when `requirements.txt` is unchanged) | Abort — dependency resolution failed |
| 3 | Load and verify `.env` exists | Abort — instructs user to copy `.env.example` |
| 4 | **Run preflight** | Abort on any blocking failure |
| 5 | Start mock API (WireMock JAR, or Python fallback) | Non-fatal — fallback engages automatically |
| 6 | Start FastAPI/Uvicorn on `127.0.0.1:8787` | Abort |
| 7 | Start Next.js on `127.0.0.1:3939` (unless `--no-ui`) | Abort |

**Flags:** `--no-ui` (skip frontend and its Node check), `--offline` (skip gateway and model probe),
`--preflight` (validate and exit — useful in CI or as a pre-demo smoke test).

Binding is explicitly to `127.0.0.1`, not `0.0.0.0`: nothing is exposed beyond the machine.

---

## 3. Preflight Checks (FR-7.2)

| Check | Blocking | What it catches |
|---|---|---|
| Python version ≥ 3.11 | Yes | Syntax/typing features used by the backend |
| Virtual environment active | Yes | Accidental global installs polluting the user's system |
| Node.js ≥ 22.x | Yes (unless `--no-ui`) | Frontend build failures |
| Required env vars present | Yes | Missing gateway URL/key |
| Data directory writable | Yes | Read-only or permission-denied paths; probes with a real write |
| Ports free **and** > 1024 | Yes | Port collisions, and any violation of NFR-1.3 |
| TLS posture | No | Reports the active posture; warns loudly when verification is off |
| Gateway reachability | Yes | Network, DNS, auth, and TLS interception failures — distinguished from one another |
| **Model tier resolution** | Yes | The PRD §9 risk: unconfirmed model IDs |
| Embedding model cached | No | Warns that first run will download ~90MB |

### 3.1 Model Tier Resolution — the check that matters most

The gateway is queried for its actual served model list, and each tier resolves to the first
candidate genuinely present:

```python
MODEL_TIERS = {
    "tier1": ("gemini/gemini-3.5-flash",      "gemini/gemini-2.5-pro"),
    "tier2": ("gemini/gemini-2.5-flash",),
    "tier3": ("gemini/gemini-3.1-flash-lite", "gemini/gemini-2.5-flash"),
}
```

This directly retires the open risk carried from Phase 1. If `gemini-3.5-flash` and
`gemini-3.1-flash-lite` do not exist on your gateway, tiers fall back to the confirmed 2.5 pair
**automatically and visibly** — the resolution is printed and written to
`data/resolved_models.json`, which the backend then reads. No code references a model ID directly;
everything references a tier.

The failure message names every model the gateway *does* serve, so a mismatch is diagnosable in one
glance rather than by trial and error.

### 3.2 TLS Resolution Order (NFR-2.2, NFR-2.3)

`_ssl_context()` establishes the posture used by preflight and mirrored by `llm/tls.py`:

1. `REQUESTS_CA_BUNDLE` or `SSL_CERT_FILE` set and present on disk → **verify against that bundle**
2. Otherwise, `SSL_VERIFY=false` → unverified context, with a loud warning
3. Otherwise → **verify against the system trust store** (the default)

Verification is on unless explicitly disabled. A TLS failure against the gateway produces a message
that names the corporate-interception cause and offers the CA-bundle fix *first*, with the bypass as
the stated fallback and its consequence spelled out.

---

## 4. Graceful Shutdown (FR-7.5)

`startup.sh` traps `EXIT`, `INT`, and `TERM`, sends `SIGTERM` to every child, and waits for each to
exit. The backend's FastAPI lifespan handler then flushes telemetry spans, commits and closes the
SQLite connection, and releases the LanceDB writer — preventing the file corruption that an abrupt
kill can cause.

Windows lacks POSIX signal semantics for detached `start` windows. `startup.bat` launches each
process in its own titled window so it can be closed individually, and a companion `shutdown.bat`
sends a clean stop. This is a genuine platform limitation, not an oversight: on Windows the
authoritative graceful path is stopping the backend window, which triggers the same lifespan
handler.

---

## 5. Mock API Fallback

WireMock requires a JRE. Rather than making that a hard dependency in a zero-admin environment,
startup detects `java` plus a `mocks/wiremock-*.jar` and falls back to `scripts/mock_server.py` —
a small Python server exposing the **same HTTP contract** on the same port.

Pipeline code is unaffected either way: it makes real HTTP calls to `WIREMOCK_BASE_URL`. This
preserves the "tool calls are real HTTP, not stubbed functions" property from the PRD while removing
a demo-day failure mode.

---

## 6. Constraint Confirmation

User-space only ✓ · no Docker ✓ · no admin ✓ · no system services ✓ · all ports > 1024 and verified ✓ ·
venv isolation enforced ✓ · fail-fast with actionable messages ✓ · CA-bundle-before-bypass ✓ ·
graceful shutdown on POSIX, documented limitation on Windows ✓
