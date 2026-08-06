"""Ingest the seed KB corpus and score retrieval against the gold set.

    python scripts/ingest_kb.py            ingest, then score both strategies
    python scripts/ingest_kb.py --score    score only, skip re-ingestion

Milestone 1 exit criterion: structure_aware must visibly beat fixed_512.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config.policy import get_policy  # noqa: E402
from app.eval import goldset  # noqa: E402
from app.observability.logging import configure_logging  # noqa: E402
from app.persistence.db import close_db, init_db  # noqa: E402
from app.rag import ingestion, rerank, store  # noqa: E402


def score_arm(name: str) -> tuple[dict, float]:
    """Score one arm's real retrieval configuration. Returns (metrics, avg context tokens)."""
    policy = get_policy(name)  # type: ignore[arg-type]
    judgements = goldset.load_judgements()
    scores, context_tokens = [], []

    for ticket in goldset.load_tickets():
        judgement = judgements.get(ticket["ticket_id"])
        if judgement is None:
            continue
        query = goldset.query_text(ticket)
        hits = store.search(query, strategy=policy.chunking, top_k=policy.retrieval_top_k)
        if policy.rerank_enabled and policy.rerank_top_k:
            hits = rerank.rerank(query, hits, top_k=policy.rerank_top_k)
        scores.append(goldset.score_retrieval(hits, judgement))
        context_tokens.append(sum(h.token_count for h in hits))

    avg_tokens = sum(context_tokens) / len(context_tokens) if context_tokens else 0.0
    return goldset.aggregate(scores), avg_tokens


def main(argv: list[str]) -> int:
    configure_logging()
    init_db()
    try:
        if "--score" not in argv:
            print("Ingesting seed corpus under both strategies...\n")
            report = ingestion.ingest_directory()
            print(f"  documents      : {report.documents}")
            print(f"  corpus_version : {report.corpus_version}")
            for strategy, count in sorted(report.chunks_by_strategy.items()):
                truncated = report.truncated_by_strategy.get(strategy, 0)
                pct = truncated / count * 100 if count else 0
                print(f"  {strategy:16} : {count:4} chunks, {truncated:3} truncated ({pct:.1f}%)")

        info = store.stats()
        print("\nCorpus statistics")
        print(f"  embedding model : {info['embedding_model']}")
        print(f"  dimension       : {info['dimension']}   max input tokens: {info['max_tokens']}")
        for strategy, s in sorted(info["by_strategy"].items()):
            print(
                f"  {strategy:16} : {s['chunks']:4} chunks  avg {s['avg_tokens']:6.1f} tok  "
                f"truncation {s['truncation_rate']*100:5.1f}%"
            )

        print("\nRetrieval quality vs. hand-labelled gold set")
        print(f"  {'metric':<20} {'baseline':>12} {'optimized':>12} {'delta':>12}")
        print("  " + "-" * 58)

        base, base_tokens = score_arm("baseline")
        opt, opt_tokens = score_arm("optimized")

        for key in ("precision_at_k", "recall_at_k", "primary_hit_rate", "section_hit_rate", "mrr"):
            b, o = base.get(key, 0.0), opt.get(key, 0.0)
            delta = (o - b) / b * 100 if b else float("inf")
            arrow = "+" if o > b else ("=" if o == b else "")
            print(f"  {key:<20} {b:>12.4f} {o:>12.4f} {arrow}{delta:>11.1f}%")

        tok_delta = (opt_tokens - base_tokens) / base_tokens * 100 if base_tokens else 0
        print(f"  {'context_tokens':<20} {base_tokens:>12.1f} {opt_tokens:>12.1f} {tok_delta:>12.1f}%")

        gate = opt.get("precision_at_k", 0) > base.get("precision_at_k", 0)
        print("\n" + ("PASS" if gate else "FAIL") + ": structure_aware "
              + ("beats" if gate else "does NOT beat") + " fixed_512 on precision@k")
        return 0 if gate else 1
    finally:
        store.close()
        close_db()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
