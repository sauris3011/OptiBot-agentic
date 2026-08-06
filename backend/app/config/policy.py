"""Policy objects driving the two measurement arms (Deliverable 6 SS6).

One graph serves both arms. Every behavioural difference between `baseline` and
`optimized` is a field on this frozen object -- never an `if arm == "baseline"`
branch inside a node.

Two reasons. It keeps nodes small (NFR-4.1). More importantly it keeps the
comparison defensible: with no arm-name branching there is no code path that
exists solely to make the baseline look bad, and a reviewer can verify that with
a single grep.

Adding an optimization lever means adding a field here, not forking a node.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.config.model_registry import ModelTier

PolicyName = Literal["baseline", "optimized"]

#: Node identifiers. Kept here so policy tables and the graph cannot drift apart.
NODE_CLASSIFY = "classify"
NODE_GUARDRAIL_PRE = "guardrail_pre"
NODE_DRAFT = "draft"
NODE_GROUND_CHECK = "ground_check"
NODE_GUARDRAIL_POST = "guardrail_post"

LLM_NODES = (
    NODE_CLASSIFY,
    NODE_GUARDRAIL_PRE,
    NODE_DRAFT,
    NODE_GROUND_CHECK,
    NODE_GUARDRAIL_POST,
)


class Policy(BaseModel):
    """Frozen behavioural contract for one measurement arm."""

    model_config = ConfigDict(frozen=True)

    name: PolicyName

    # --- Model routing ----------------------------------------------------
    model_tier_by_node: dict[str, ModelTier]

    # --- Prompting --------------------------------------------------------
    prompt_variant: Literal["baseline", "optimized"]

    # --- Retrieval --------------------------------------------------------
    chunking: Literal["fixed_512", "structure_aware"]
    retrieval_top_k: int
    metadata_filter_enabled: bool
    rerank_enabled: bool
    rerank_top_k: int | None = None

    # --- Cost controls ----------------------------------------------------
    cache_enabled: bool

    # --- Governance -------------------------------------------------------
    guardrails_enabled: bool
    escalation: Literal["always_human", "confidence_gated"]
    confidence_threshold: float = 0.75

    def tier_for(self, node: str) -> ModelTier:
        """Tier for a node. Unlisted nodes default to the most capable tier.

        Defaulting upward is deliberate: a node accidentally omitted from the
        table gets correct-but-expensive behaviour rather than silently cheap
        behaviour that would corrupt a quality metric.
        """
        return self.model_tier_by_node.get(node, ModelTier.TIER1)


# ---------------------------------------------------------------------------
# The two arms
# ---------------------------------------------------------------------------

BASELINE = Policy(
    name="baseline",
    # One big model for everything - the naive enterprise default.
    model_tier_by_node={node: ModelTier.TIER1 for node in LLM_NODES},
    prompt_variant="baseline",
    chunking="fixed_512",
    retrieval_top_k=10,
    metadata_filter_enabled=False,
    rerank_enabled=False,
    rerank_top_k=None,
    cache_enabled=False,
    guardrails_enabled=False,
    escalation="always_human",
)

OPTIMIZED = Policy(
    name="optimized",
    model_tier_by_node={
        NODE_CLASSIFY: ModelTier.TIER3,
        NODE_GUARDRAIL_PRE: ModelTier.TIER3,
        NODE_DRAFT: ModelTier.TIER2,
        # Deliberately retained on the most capable tier. Downgrading the node
        # that detects hallucinations to save tokens would optimize away the
        # thing being optimized for (Deliverable 6 SS4).
        NODE_GROUND_CHECK: ModelTier.TIER1,
        NODE_GUARDRAIL_POST: ModelTier.TIER3,
    },
    prompt_variant="optimized",
    chunking="structure_aware",
    retrieval_top_k=10,
    metadata_filter_enabled=True,
    rerank_enabled=True,
    rerank_top_k=3,
    cache_enabled=True,
    guardrails_enabled=True,
    escalation="confidence_gated",
)

_POLICIES: dict[str, Policy] = {BASELINE.name: BASELINE, OPTIMIZED.name: OPTIMIZED}


def get_policy(name: PolicyName, *, bypass_cache: bool = False) -> Policy:
    """Resolve a policy by name.

    `bypass_cache=True` is how the eval harness enforces FR-3.1/FR-3.2. A warmed
    cache would let the optimized arm replay the baseline's work and report a
    delta that is an artifact of run order rather than of optimization, so
    benchmark runs disable it on both arms.
    """
    policy = _POLICIES[name]
    if bypass_cache and policy.cache_enabled:
        return policy.model_copy(update={"cache_enabled": False})
    return policy
