"""TLS posture resolution (NFR-2.2 - 2.5, Deliverable 5 SS3).

Mirrors scripts/preflight.py exactly, so what preflight validates is what
runtime uses.

Resolution order:
  1. Corporate CA bundle, if configured and present  -> verifying
  2. Explicit SSL_VERIFY=false                       -> bypass, loudly
  3. System trust store                              -> verifying (default)

The bundle is tried first deliberately. The master prompt offers the bypass
directly; taking it immediately would be the easy path and the wrong one. Most
corporate interception is solved correctly by trusting the corporate CA, which
keeps certificate verification intact.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from app.config.settings import get_settings

TlsMode = Literal["ca_bundle", "system", "bypass", "relaxed_ciphers"]

BYPASS_WARNING = (
    "TLS verification is DISABLED. The client cannot distinguish the sanctioned "
    "corporate proxy from any other interceptor; gateway credentials and prompt "
    "content are readable by anything on the network path. Acceptable for this "
    "synthetic-data prototype on loopback only -- never for real credentials or "
    "personal data."
)


@dataclass(frozen=True)
class TlsPosture:
    """The active posture, surfaced through /api/health and /api/settings.

    Returned rather than merely applied: a silent bypass is the actual danger,
    a visible one is a managed risk. This object drives the persistent UI
    warning banner (FR-5.8).
    """

    verifying: bool
    mode: TlsMode
    detail: str

    @property
    def warning(self) -> str | None:
        return None if self.verifying else BYPASS_WARNING

    def to_dict(self) -> dict:
        return {
            "verifying": self.verifying,
            "mode": self.mode,
            "detail": self.detail,
            "warning": self.warning,
        }


_posture: TlsPosture | None = None


def configure_tls() -> TlsPosture:
    """Apply and return the TLS posture. Called once from lifespan startup."""
    global _posture
    settings = get_settings()

    # 1. Corporate CA bundle -- the correct fix, tried first.
    bundle = settings.ca_bundle
    if bundle:
        os.environ["REQUESTS_CA_BUNDLE"] = bundle
        os.environ["SSL_CERT_FILE"] = bundle
        _posture = TlsPosture(True, "ca_bundle", f"verifying via CA bundle: {bundle}")
        return _posture

    # 2. Explicit opt-out.
    if not settings.ssl_verify:
        import litellm

        # Scoped to LiteLLM's client rather than a process-global flag, so the
        # optional telemetry mirror and WireMock calls keep their verification.
        # Narrower blast radius for the same demo outcome.
        litellm.ssl_verify = False
        _posture = TlsPosture(False, "bypass", "certificate verification disabled")
        return _posture

    # 3. Default.
    _posture = TlsPosture(True, "system", "verifying with system trust store")
    return _posture


def relax_cipher_level() -> TlsPosture:
    """Weaken cipher requirements without disabling identity verification.

    For proxies presenting legacy ciphers. Strictly preferable to a full bypass
    when it suffices, and should be tried before one.
    """
    global _posture
    import litellm

    litellm.ssl_security_level = "DEFAULT@SECLEVEL=1"
    _posture = TlsPosture(
        True, "relaxed_ciphers", "verifying with relaxed cipher level (SECLEVEL=1)"
    )
    return _posture


def get_posture() -> TlsPosture:
    return _posture if _posture is not None else configure_tls()


def httpx_verify():
    """`verify` argument for httpx clients, matching the active posture."""
    settings = get_settings()
    return settings.ca_bundle or settings.ssl_verify
