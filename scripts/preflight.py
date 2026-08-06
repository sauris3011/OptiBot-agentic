"""Preflight validation for OptiBot (Deliverable 3, FR-7.2).

Runs on bare CPython using only the standard library, so it can execute *before*
backend dependencies are installed and still produce actionable errors.

Each check fails fast with a distinct, actionable message. Exit code 0 = all
required checks passed. Exit code 1 = at least one required check failed.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

MIN_PYTHON = (3, 11)
MIN_NODE_MAJOR = 22

REQUIRED_ENV = ("LITELLM_GATEWAY_URL", "LITELLM_API_KEY")

# Tier -> candidate model ids, most preferred first. The probe resolves each
# tier to the first candidate the gateway actually serves (PRD §4.3, §9).
MODEL_TIERS: dict[str, tuple[str, ...]] = {
    "tier1": ("gemini/gemini-3.5-flash", "gemini/gemini-2.5-pro"),
    "tier2": ("gemini/gemini-2.5-flash",),
    "tier3": ("gemini/gemini-3.1-flash-lite", "gemini/gemini-2.5-flash"),
}


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    required: bool = True


results: list[Result] = []


def record(name: str, ok: bool, detail: str, required: bool = True) -> bool:
    results.append(Result(name, ok, detail, required))
    return ok


# --------------------------------------------------------------------------
# Environment file
# --------------------------------------------------------------------------

def load_dotenv() -> None:
    """Populate os.environ from .env without overriding an existing value."""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

def check_python() -> bool:
    actual = sys.version_info[:2]
    if actual < MIN_PYTHON:
        return record(
            "Python version",
            False,
            f"Found {actual[0]}.{actual[1]}, need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}. "
            "Install a newer Python and recreate the venv.",
        )
    return record("Python version", True, f"{actual[0]}.{actual[1]}")


def check_venv() -> bool:
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if not in_venv:
        return record(
            "Virtual environment",
            False,
            "Not running inside a venv. Run: python -m venv .venv  then activate it. "
            "The startup scripts do this for you.",
        )
    return record("Virtual environment", True, sys.prefix)


def check_node() -> bool:
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        return record(
            "Node.js",
            False,
            f"node not found on PATH. Node {MIN_NODE_MAJOR}.x is required for the frontend.",
        )
    try:
        raw = subprocess.run(
            [node, "--version"], capture_output=True, text=True, timeout=15, check=True
        ).stdout.strip()
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return record("Node.js", False, f"Could not run `node --version`: {exc}")

    major = int(raw.lstrip("v").split(".")[0])
    if major < MIN_NODE_MAJOR:
        return record(
            "Node.js",
            False,
            f"Found {raw}, need >= {MIN_NODE_MAJOR}.x. Upgrade Node or skip the UI with --no-ui.",
        )
    return record("Node.js", True, raw)


def check_env_vars() -> bool:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        return record(
            "Environment variables",
            False,
            f"Missing: {', '.join(missing)}. Copy .env.example to .env and fill them in.",
        )
    return record("Environment variables", True, f"{len(REQUIRED_ENV)} present")


def check_data_dirs() -> bool:
    data_dir = Path(os.environ.get("DATA_DIR", REPO_ROOT / "data"))
    targets = [data_dir, data_dir / "lancedb"]
    for target in targets:
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            return record(
                "Data directory",
                False,
                f"Cannot write to {target}: {exc}. Check permissions or set DATA_DIR.",
            )
    return record("Data directory", True, str(data_dir))


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def check_ports() -> bool:
    wanted = {
        "backend": int(os.environ.get("BACKEND_PORT", 8787)),
        "frontend": int(os.environ.get("FRONTEND_PORT", 3939)),
        "wiremock": int(os.environ.get("WIREMOCK_PORT", 8181)),
    }
    privileged = [f"{n}={p}" for n, p in wanted.items() if p <= 1024]
    if privileged:
        return record(
            "Ports",
            False,
            f"Privileged port(s) configured: {', '.join(privileged)}. "
            "All ports must be > 1024 (NFR-1.3).",
        )
    busy = [f"{n}={p}" for n, p in wanted.items() if not _port_free(p)]
    if busy:
        return record(
            "Ports",
            False,
            f"Already in use: {', '.join(busy)}. Stop the conflicting process or "
            "override via BACKEND_PORT / FRONTEND_PORT / WIREMOCK_PORT.",
        )
    return record("Ports", True, ", ".join(f"{n}={p}" for n, p in wanted.items()))


def _ssl_context() -> ssl.SSLContext | None:
    """CA-bundle-first TLS resolution (NFR-2.2, NFR-2.3).

    Returns a verifying context when possible. Returns an unverified context
    only when SSL_VERIFY is explicitly disabled.
    """
    bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if bundle and Path(bundle).exists():
        return ssl.create_default_context(cafile=bundle)

    verify = os.environ.get("SSL_VERIFY", "true").strip().lower()
    if verify in {"false", "0", "no"}:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    return ssl.create_default_context()


def _gateway_get(path: str, timeout: float = 10.0) -> tuple[int, bytes]:
    base = os.environ["LITELLM_GATEWAY_URL"].rstrip("/")
    request = urllib.request.Request(
        f"{base}{path}",
        headers={"Authorization": f"Bearer {os.environ.get('LITELLM_API_KEY', '')}"},
    )
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        return response.status, response.read()


def check_gateway() -> bool:
    if not os.environ.get("LITELLM_GATEWAY_URL"):
        return record("Gateway reachability", False, "LITELLM_GATEWAY_URL is not set.")
    try:
        status, _ = _gateway_get("/health")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return record(
                "Gateway reachability",
                False,
                f"Gateway reachable but rejected the key (HTTP {exc.code}). Check LITELLM_API_KEY.",
            )
        return record("Gateway reachability", True, f"Reachable (HTTP {exc.code} on /health)")
    except ssl.SSLError as exc:
        return record(
            "Gateway reachability",
            False,
            f"TLS failure: {exc}. Corporate interception detected. Set REQUESTS_CA_BUNDLE to the "
            "corporate CA bundle (preferred), or set SSL_VERIFY=false to bypass "
            "(removes MITM protection - see PRD NFR-2.5).",
        )
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return record(
            "Gateway reachability",
            False,
            f"Unreachable: {exc}. Verify LITELLM_GATEWAY_URL and network access.",
        )
    return record("Gateway reachability", True, f"HTTP {status}")


def check_model_tiers() -> bool:
    """Resolve each tier against the gateway's real model list (PRD §9)."""
    try:
        _, body = _gateway_get("/v1/models")
        served = {m.get("id") for m in json.loads(body).get("data", [])}
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return record(
            "Model tier resolution",
            False,
            f"Could not list gateway models: {exc}. Cannot confirm tier assignments.",
        )

    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for tier, candidates in MODEL_TIERS.items():
        match = next((c for c in candidates if c in served), None)
        if match:
            resolved[tier] = match
        else:
            unresolved.append(f"{tier} (tried: {', '.join(candidates)})")

    if unresolved:
        return record(
            "Model tier resolution",
            False,
            f"No served model for: {'; '.join(unresolved)}. "
            f"Gateway serves: {', '.join(sorted(served)) or '(none)'}.",
        )

    (REPO_ROOT / "data").mkdir(exist_ok=True)
    (REPO_ROOT / "data" / "resolved_models.json").write_text(
        json.dumps(resolved, indent=2), encoding="utf-8"
    )
    return record(
        "Model tier resolution",
        True,
        ", ".join(f"{t}={m}" for t, m in resolved.items()),
    )


def check_embedding_model() -> bool:
    """Non-fatal: report whether the embedding model is already cached."""
    model = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    slug = "models--" + model.replace("/", "--")
    cached = (cache / "hub" / slug).exists() or (cache / slug).exists()
    if cached:
        return record("Embedding model", True, f"{model} (cached)")
    return record(
        "Embedding model",
        False,
        f"{model} not cached; first run will download ~90MB. If the network blocks this, "
        "pre-cache the model before the demo.",
        required=False,
    )


def check_tls_posture() -> bool:
    """Always-visible statement of the current TLS posture (NFR-2.4)."""
    bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if bundle and Path(bundle).exists():
        return record("TLS posture", True, f"Verifying via CA bundle: {bundle}")
    if os.environ.get("SSL_VERIFY", "true").strip().lower() in {"false", "0", "no"}:
        return record(
            "TLS posture",
            True,
            "WARNING: verification DISABLED. MITM protection is off for all gateway traffic. "
            "Acceptable for synthetic-data prototyping only.",
            required=False,
        )
    return record("TLS posture", True, "Verifying with system trust store")


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------

CHECKS = (
    check_python,
    check_venv,
    check_env_vars,
    check_data_dirs,
    check_ports,
    check_tls_posture,
    check_gateway,
    check_model_tiers,
    check_embedding_model,
)


def main(argv: list[str]) -> int:
    load_dotenv()

    checks = list(CHECKS)
    if "--no-ui" not in argv:
        checks.insert(2, check_node)
    if "--offline" in argv:
        checks = [c for c in checks if c not in (check_gateway, check_model_tiers)]

    print("\nOptiBot preflight\n" + "-" * 60)
    for check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a crashing check is a failed check
            record(check.__name__, False, f"Check crashed: {exc}")

    width = max(len(r.name) for r in results)
    for r in results:
        mark = "PASS" if r.ok else ("FAIL" if r.required else "WARN")
        print(f"  [{mark}] {r.name.ljust(width)}  {r.detail}")

    failures = [r for r in results if not r.ok and r.required]
    print("-" * 60)
    if failures:
        print(f"Preflight FAILED - {len(failures)} blocking issue(s). Resolve the above.\n")
        return 1
    print("Preflight passed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
