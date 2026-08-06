"""Token cost accounting (Deliverable 5 SS6).

Priority order:
  1. LiteLLM's model cost map, when the model is known
  2. Configured override rates
  3. Documented fallback rates, flagged as estimated (FR-5.1)

The estimated flag propagates to the header monitor and the comparison
dashboard. Cost credibility depends on being explicit about which numbers are
measured and which are inferred, so an inferred figure is never displayed as a
measured one.
"""

from __future__ import annotations

from dataclasses import dataclass

#: USD per 1M tokens. Applied when the model is absent from LiteLLM's cost map.
#: Chosen to sit in the middle of published flash-class pricing -- close enough
#: to be useful, and always flagged so it is never mistaken for measured.
FALLBACK_INPUT_PER_M = 0.30
FALLBACK_OUTPUT_PER_M = 1.20

#: Explicit overrides, keyed by model id. Populated when exact gateway rates
#: are known; takes precedence over the fallback but not over LiteLLM's map.
RATE_OVERRIDES: dict[str, tuple[float, float]] = {}


@dataclass(frozen=True)
class CostResult:
    cost_usd: float
    estimated: bool
    source: str


def _from_litellm(model: str, tokens_in: int, tokens_out: int) -> CostResult | None:
    try:
        import litellm

        cost = litellm.completion_cost(
            model=model,
            prompt_tokens=tokens_in,
            completion_tokens=tokens_out,
        )
    except Exception:
        # A missing model, an unparsable id, or a LiteLLM internal change all
        # land here. Falling through to an estimate is correct; raising would
        # fail a run over a pricing lookup.
        return None

    if cost is None or cost <= 0:
        return None
    return CostResult(round(float(cost), 8), estimated=False, source="litellm_cost_map")


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> CostResult:
    """Cost for one call, with provenance."""
    if tokens_in <= 0 and tokens_out <= 0:
        return CostResult(0.0, estimated=False, source="zero_tokens")

    exact = _from_litellm(model, tokens_in, tokens_out)
    if exact is not None:
        return exact

    rate_in, rate_out = RATE_OVERRIDES.get(
        model, (FALLBACK_INPUT_PER_M, FALLBACK_OUTPUT_PER_M)
    )
    source = "override" if model in RATE_OVERRIDES else "fallback_rates"
    cost = (tokens_in * rate_in + tokens_out * rate_out) / 1_000_000
    return CostResult(round(cost, 8), estimated=True, source=source)
