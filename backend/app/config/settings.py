"""Boot-time environment validation (FR-7.3).

A single Pydantic Settings object is the only sanctioned way to read
configuration. Nothing else in the codebase touches os.environ directly, so an
invalid environment fails at import time with a readable error rather than as a
KeyError three layers deep.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Validated application configuration."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM gateway (required) ------------------------------------------
    litellm_gateway_url: str = Field(..., min_length=1)
    litellm_api_key: str = Field(..., min_length=1)

    #: Provider prefix applied to every model id at call time. The gateway lists
    #: bare ids ("gemini-3.5-flash"), but LiteLLM would read that as a direct
    #: Vertex AI request and never reach the proxy. "litellm_proxy/" and
    #: "openai/" both work against a LiteLLM proxy; the former states intent.
    litellm_model_prefix: str = "litellm_proxy/"

    # --- Ports (NFR-1.3: all must exceed 1024) ---------------------------
    backend_port: int = 8787
    frontend_port: int = 3939
    wiremock_port: int = 8181

    # --- TLS (NFR-2.2, NFR-2.3) ------------------------------------------
    ssl_verify: bool = True
    requests_ca_bundle: str | None = None
    ssl_cert_file: str | None = None

    # --- Storage ----------------------------------------------------------
    data_dir: Path = REPO_ROOT / "data"

    # --- Embeddings -------------------------------------------------------
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # --- Observability ----------------------------------------------------
    telemetry_mirror_enabled: bool = False
    telemetry_mirror_provider: Literal["langfuse", "agentops"] = "langfuse"
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None

    # --- Resiliency (FR-7.4) ----------------------------------------------
    token_budget_cap: int | None = 2_000_000
    llm_max_retries: int = 4
    llm_backoff_base_seconds: float = 0.5

    # --- Mock enterprise APIs ---------------------------------------------
    wiremock_base_url: str = "http://127.0.0.1:8181"

    # --- Logging ----------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # ---------------------------------------------------------------------
    # Validation
    # ---------------------------------------------------------------------

    @field_validator("backend_port", "frontend_port", "wiremock_port")
    @classmethod
    def _unprivileged_port(cls, value: int, info) -> int:
        if value <= 1024:
            raise ValueError(
                f"{info.field_name}={value} is privileged. All ports must be > 1024 "
                "so the stack runs without admin rights (NFR-1.3)."
            )
        return value

    @field_validator("litellm_gateway_url")
    @classmethod
    def _normalise_gateway_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError(
                f"LITELLM_GATEWAY_URL must start with http:// or https:// (got {value!r})."
            )
        return value.rstrip("/")

    @field_validator("token_budget_cap", mode="before")
    @classmethod
    def _blank_cap_means_unlimited(cls, value):
        if value in ("", None):
            return None
        return value

    @model_validator(mode="after")
    def _resolve_ca_bundle(self) -> "Settings":
        """Discard a CA bundle path that does not exist on disk.

        A stale REQUESTS_CA_BUNDLE pointing at a missing file would otherwise
        silently fall through to a confusing TLS error at first call. Better to
        drop it here and let the documented resolution order (tls.py) apply.
        """
        for attr in ("requests_ca_bundle", "ssl_cert_file"):
            path = getattr(self, attr)
            if path and not Path(path).exists():
                object.__setattr__(self, attr, None)
        return self

    # ---------------------------------------------------------------------
    # Derived paths
    # ---------------------------------------------------------------------

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "optibot.db"

    @property
    def lancedb_path(self) -> Path:
        return self.data_dir / "lancedb"

    @property
    def resolved_models_path(self) -> Path:
        """Written by scripts/preflight.py; read by config/model_registry.py."""
        return self.data_dir / "resolved_models.json"

    @property
    def ca_bundle(self) -> str | None:
        return self.requests_ca_bundle or self.ssl_cert_file


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor. Import this, never instantiate Settings directly."""
    return Settings()  # type: ignore[call-arg]
