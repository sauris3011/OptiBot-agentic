"""Model tier indirection (Deliverable 5 §2).

No module in this codebase references a concrete model id. Nodes request a
*tier*; this registry resolves it against what the gateway actually serves.

Resolution order for each tier is declared in TIER_CANDIDATES. scripts/preflight.py
probes the gateway and writes the winner to data/resolved_models.json. This module
reads that file, and falls back to probing itself if the file is absent.

The indirection is what makes the PRD SS9 risk survivable: if the 3.x models are
not served, tiers collapse onto the confirmed 2.5 pair automatically, and the
shape of the optimization (spend where quality matters) is preserved.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache

import httpx

from app.config.settings import get_settings


class ModelTier(StrEnum):
    """Capability tiers. Nodes reference these, never model ids."""

    TIER1 = "tier1"  # most capable  - ground_check, and every baseline node
    TIER2 = "tier2"  # mid           - draft (optimized)
    TIER3 = "tier3"  # lite          - classify, guardrails (optimized)


#: Candidates per tier, most preferred first. The first one the gateway actually
#: serves wins. Keep in sync with scripts/preflight.py.
#:
#: Ids are BARE, exactly as the gateway lists them in /v1/models. The provider
#: prefix (settings.litellm_model_prefix) is applied at call time by
#: llm/client.py -- an unprefixed name makes LiteLLM route to Vertex AI directly
#: instead of to the local proxy.
#:
#: gemini-2.5-pro is retained only as a portability fallback -- THIS gateway does
#: not serve it, so it never wins. The three flash-class models form a clean
#: capability ladder on their own, and the measured reasoning-token spread
#: between them (575-717 / 323 / 0 on an identical classification) is what the
#: optimization story rests on.
TIER_CANDIDATES: dict[ModelTier, tuple[str, ...]] = {
    ModelTier.TIER1: ("gemini-3.5-flash", "gemini-2.5-pro"),
    ModelTier.TIER2: ("gemini-2.5-flash", "gemini-3.5-flash"),
    ModelTier.TIER3: ("gemini-3.1-flash-lite", "gemini-2.5-flash"),
}


class ModelTierUnresolved(RuntimeError):
    """No candidate for a tier is served by the gateway."""


class ModelRegistry:
    """Resolved tier -> model id mapping for the process lifetime."""

    def __init__(self, resolved: dict[str, str], source: str) -> None:
        self._resolved = resolved
        self.source = source

    def model_for(self, tier: ModelTier) -> str:
        """Bare model id, as the gateway lists it. Use for logging and spans."""
        try:
            return self._resolved[str(tier)]
        except KeyError as exc:
            raise ModelTierUnresolved(
                f"Tier {tier} was not resolved at startup. Run "
                "`startup.sh --preflight` to probe the gateway and refresh "
                "data/resolved_models.json."
            ) from exc

    def qualified_model_for(self, tier: ModelTier) -> str:
        """Prefixed model id for the LiteLLM call itself.

        Without the prefix LiteLLM inspects the bare name, recognises it as a
        Gemini model, and routes straight to Vertex AI -- failing with a Google
        Cloud SDK import error rather than reaching the local proxy.
        """
        from app.config.settings import get_settings

        return f"{get_settings().litellm_model_prefix}{self.model_for(tier)}"

    def as_dict(self) -> dict[str, str]:
        return dict(self._resolved)

    def is_degraded(self) -> bool:
        """True when any tier fell back off its first-choice candidate.

        Surfaced through /api/health so a fallback is visible rather than silent.
        """
        return any(
            self._resolved.get(str(tier)) != candidates[0]
            for tier, candidates in TIER_CANDIDATES.items()
        )


def _served_models(timeout: float = 15.0) -> set[str]:
    """Ask the gateway which models it actually serves.

    Every failure mode is normalised to ModelTierUnresolved so callers have one
    exception to handle. A transport error escaping as httpx.ConnectError would
    crash startup, when the correct behaviour is to stay up and let /api/health
    explain what went wrong.
    """
    settings = get_settings()
    verify: bool | str = settings.ca_bundle or settings.ssl_verify
    try:
        with httpx.Client(timeout=timeout, verify=verify) as client:
            response = client.get(
                f"{settings.litellm_gateway_url}/v1/models",
                headers={"Authorization": f"Bearer {settings.litellm_api_key}"},
            )
            response.raise_for_status()
            return {entry.get("id") for entry in response.json().get("data", [])}
    except httpx.HTTPStatusError as exc:
        raise ModelTierUnresolved(
            f"Gateway rejected the model list request (HTTP {exc.response.status_code}). "
            "Check LITELLM_API_KEY."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - normalised for callers
        raise ModelTierUnresolved(
            f"Could not reach the gateway to list models: {exc}. "
            "Verify LITELLM_GATEWAY_URL, then run `startup.sh --preflight`."
        ) from exc


def _resolve_against(served: set[str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for tier, candidates in TIER_CANDIDATES.items():
        match = next((c for c in candidates if c in served), None)
        if match:
            resolved[str(tier)] = match
        else:
            unresolved.append(f"{tier} (tried: {', '.join(candidates)})")
    if unresolved:
        raise ModelTierUnresolved(
            f"Gateway serves no model for: {'; '.join(unresolved)}. "
            f"Available: {', '.join(sorted(served)) or '(none)'}."
        )
    return resolved


@lru_cache(maxsize=1)
def get_registry() -> ModelRegistry:
    """Load the tier mapping, preferring the preflight-written file."""
    settings = get_settings()
    path = settings.resolved_models_path

    if path.exists():
        try:
            resolved = json.loads(path.read_text(encoding="utf-8"))
            if all(str(t) in resolved for t in ModelTier):
                return ModelRegistry(resolved, source=str(path))
        except (json.JSONDecodeError, OSError):
            pass  # fall through to a live probe

    resolved = _resolve_against(_served_models())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(resolved, indent=2), encoding="utf-8")
    return ModelRegistry(resolved, source="live gateway probe")
