#!/usr/bin/env bash
# OptiBot startup (Deliverable 3, FR-7.1)
# User-space only: no sudo, no docker, no system services.
#
# Usage:
#   ./startup.sh              full stack (backend + frontend + wiremock)
#   ./startup.sh --no-ui      backend + wiremock only
#   ./startup.sh --offline    skip gateway/model preflight checks
#   ./startup.sh --preflight  run checks and exit

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

ARGS=("$@")
has_arg() { for a in "${ARGS[@]:-}"; do [[ "$a" == "$1" ]] && return 0; done; return 1; }

NO_UI=false;  has_arg --no-ui   && NO_UI=true
PREFLIGHT_ONLY=false; has_arg --preflight && PREFLIGHT_ONLY=true

PIDS=()

cleanup() {
  echo ""
  echo "Shutting down..."
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      # SIGTERM lets the backend flush spans and close SQLite/LanceDB cleanly (FR-7.5)
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  for pid in "${PIDS[@]:-}"; do wait "$pid" 2>/dev/null || true; done
  echo "All processes stopped."
}
trap cleanup EXIT INT TERM

# --- 1. Python venv -------------------------------------------------------
if [[ ! -d .venv ]]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv || { echo "ERROR: could not create venv. Is python3 installed?"; exit 1; }
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# --- 2. Dependencies ------------------------------------------------------
DEP_STAMP=".venv/.deps-installed"
if [[ ! -f "$DEP_STAMP" || backend/requirements.txt -nt "$DEP_STAMP" ]]; then
  echo "Installing backend dependencies..."
  pip install --quiet --upgrade pip
  pip install --quiet -r backend/requirements.txt
  touch "$DEP_STAMP"
fi

# --- 3. Environment file --------------------------------------------------
if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill in gateway settings."
  exit 1
fi
set -a; source .env; set +a

BACKEND_PORT="${BACKEND_PORT:-8787}"
FRONTEND_PORT="${FRONTEND_PORT:-3939}"
WIREMOCK_PORT="${WIREMOCK_PORT:-8181}"

# --- 4. Preflight (fail fast, FR-7.2) ------------------------------------
python scripts/preflight.py "${ARGS[@]:-}" || exit 1
$PREFLIGHT_ONLY && { trap - EXIT; exit 0; }

# --- 5. WireMock ----------------------------------------------------------
WIREMOCK_JAR="$(ls mocks/wiremock-*.jar 2>/dev/null | head -n1 || true)"
if [[ -n "$WIREMOCK_JAR" ]] && command -v java >/dev/null 2>&1; then
  echo "Starting WireMock on :$WIREMOCK_PORT"
  java -jar "$WIREMOCK_JAR" --port "$WIREMOCK_PORT" --root-dir mocks/wiremock \
    --disable-banner >logs/wiremock.log 2>&1 &
  PIDS+=($!)
else
  echo "Starting mock API fallback on :$WIREMOCK_PORT (no JRE/JAR found)"
  python -m scripts.mock_server --port "$WIREMOCK_PORT" >logs/wiremock.log 2>&1 &
  PIDS+=($!)
fi

# --- 6. Backend -----------------------------------------------------------
echo "Starting backend on :$BACKEND_PORT"
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$BACKEND_PORT" &
PIDS+=($!)

# --- 7. Frontend ----------------------------------------------------------
if ! $NO_UI; then
  if [[ ! -d frontend/node_modules ]]; then
    echo "Installing frontend dependencies..."
    (cd frontend && npm install --silent)
  fi
  echo "Starting frontend on :$FRONTEND_PORT"
  (cd frontend && npm run dev -- --port "$FRONTEND_PORT") &
  PIDS+=($!)
fi

echo ""
echo "OptiBot is running."
echo "  Backend   http://127.0.0.1:$BACKEND_PORT"
$NO_UI || echo "  Frontend  http://127.0.0.1:$FRONTEND_PORT"
echo "  Mocks     http://127.0.0.1:$WIREMOCK_PORT"
echo ""
echo "Press Ctrl+C to stop."

wait
