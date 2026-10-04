"""Standard IR metrics (binary relevance = grade >= 2, graded gain for NDCG)."""
from __future__ import annotations

import math
import random


def precision_at(ranked: list[str], rel: set[str], k: int) -> float:
    return sum(1 for a in ranked[:k] if a in rel) / k


def recall_at(ranked: list[str], rel: set[str], k: int) -> float | None:
    return None if not rel else sum(1 for a in ranked[:k] if a in rel) / len(rel)


def mrr(ranked: list[str], rel: set[str], k: int = 10) -> float:
    for i, a in enumerate(ranked[:k], 1):
        if a in rel:
            return 1.0 / i
    return 0.0


def average_precision(ranked: list[str], rel: set[str], k: int = 10) -> float:
    if not rel:
        return 0.0
    hits, s = 0, 0.0
    for i, a in enumerate(ranked[:k], 1):
        if a in rel:
            hits += 1
            s += hits / i
    return s / min(len(rel), k)


def ndcg_at(ranked: list[str], grades: dict[str, int], k: int = 10) -> float:
    dcg = sum((2 ** grades.get(a, 0) - 1) / math.log2(i + 1) for i, a in enumerate(ranked[:k], 1))
    ideal = sorted(grades.values(), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 1) for i, g in enumerate(ideal, 1))
    return dcg / idcg if idcg > 0 else 0.0


def hit_rate(ranked: list[str], rel: set[str], k: int = 10) -> float:
    return 1.0 if any(a in rel for a in ranked[:k]) else 0.0


def all_metrics(ranked: list[str], grades: dict[str, int], constraint_ok: list[bool]) -> dict[str, float | None]:
    rel = {a for a, g in grades.items() if g >= 2}
    return {
        "P@5": precision_at(ranked, rel, 5), "P@10": precision_at(ranked, rel, 10), "R@10": recall_at(ranked, rel, 10),
        "NDCG@10": ndcg_at(ranked, grades, 10), "MRR": mrr(ranked, rel, 10), "MAP@10": average_precision(ranked, rel, 10),
        "HitRate@10": hit_rate(ranked, rel, 10),
        "ConstraintSat@10": (sum(constraint_ok[:10]) / len(constraint_ok[:10])) if constraint_ok else 0.0,
    }


def paired_permutation_test(a: list[float], b: list[float], iters: int = 10000, seed: int = 7) -> float:
    """Two-sided paired randomisation test on the mean difference; returns p-value."""
    rng = random.Random(seed)
    diffs = [x - y for x, y in zip(a, b)]
    obs = abs(sum(diffs) / len(diffs))
    count = 0
    for _ in range(iters):
        s = sum(d if rng.random() < 0.5 else -d for d in diffs) / len(diffs)
        if abs(s) >= obs - 1e-12:
            count += 1
    return (count + 1) / (iters + 1)
