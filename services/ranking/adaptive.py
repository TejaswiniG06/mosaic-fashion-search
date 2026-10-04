"""Context-adaptive weighting (the MOSAIC contribution).

Instead of one fixed linear fusion for every query, the weight vector is a function of the
decomposed intent:  w(intent) = normalise( BASE ⊙ active(intent) ⊙ Π boosts(intent) ).

  * signals the query gives no evidence for are switched off (no occasion asked => occasion weight 0)
  * evidence-specific boosts: image query / colour-pattern words => visual ↑; destination+season
    (e.g. Chennai summer) => climate ↑ and implied-fabric ↑; explicit fabric => material ↑; comfort
    words => comfort ↑; brand / quoted terms => lexical ↑; code-mixed / native-script query =>
    lexical ↓ semantic ↑ (exact term overlap is unreliable across scripts); vague query => semantic ↑
  * per-candidate image fallback: if a product has no image, its visual weight is redistributed

Every boost is recorded as a human-readable rationale string returned to the UI/API.
"""
from __future__ import annotations

from mosaic_common.schemas import SIGNALS, Intent

from .signals import HOT, comfort_active, material_active

BASE = {"semantic": 0.30, "lexical": 0.15, "visual": 0.10, "occasion": 0.12, "climate": 0.11, "material": 0.11, "comfort": 0.11}


def _norm(w: dict[str, float]) -> dict[str, float]:
    s = sum(w.values())
    return {k: (v / s if s > 0 else 0.0) for k, v in w.items()}


def fixed_weights() -> tuple[dict[str, float], list[str]]:
    return _norm(dict(BASE)), ["fixed weights (ablation): identical for every query"]


def adaptive_weights(intent: Intent, visual_available: bool, use_visual: bool = True, use_context: bool = True) -> tuple[dict[str, float], list[str]]:
    w = dict(BASE)
    why: list[str] = []
    active = {
        "semantic": True,
        "lexical": True,
        "visual": use_visual and visual_available,
        "occasion": use_context and bool(intent.occasion),
        "climate": use_context and bool(intent.climate),
        "material": use_context and material_active(intent),
        "comfort": use_context and comfort_active(intent),
    }
    off = [k for k, on in active.items() if not on]
    for k in off:
        w[k] = 0.0
    if off:
        why.append("no query evidence for " + ", ".join(off) + " → weight 0")

    if active["visual"]:
        if intent.has_query_image:
            w["visual"] *= 3.5
            w["semantic"] *= 0.7
            why.append("query image supplied → visual ×3.5, semantic ×0.7")
        elif intent.colour or intent.pattern:
            w["visual"] *= 3.0
            why.append(f"colour/pattern requested ({', '.join(intent.colour + intent.pattern)}) → visual ×3")
        elif intent.visual_intent:
            w["visual"] *= 2.0
            why.append("look/style requested → visual ×2")
    if active["climate"]:
        f = 1.8 * (1.15 if intent.destination else 1.0)
        w["climate"] *= f
        why.append(f"climate '{intent.climate}'" + (f" from destination {intent.destination}" if intent.destination else "") + f" → climate ×{f:.2f}")
    if active["material"]:
        if intent.material:
            w["material"] *= 1.8
            why.append(f"explicit fabric {intent.material} → material ×1.8")
        if intent.sustainability:
            w["material"] *= 1.5
            why.append("sustainability preference → material ×1.5")
        if not intent.material and not intent.sustainability and intent.climate in HOT:
            why.append("hot climate implies breathable fabrics → material signal active")
    if active["comfort"] and intent.comfort:
        w["comfort"] *= 1.7
        why.append("comfort requested → comfort ×1.7")
    if active["occasion"]:
        w["occasion"] *= 1.5
        why.append(f"occasion {intent.occasion} → occasion ×1.5")
    if intent.brand:
        w["lexical"] *= 2.0
        why.append(f"exact terms/brand {intent.brand} → lexical ×2")
    if intent.language in ("ta", "hi", "tanglish", "hinglish"):
        w["lexical"] *= 0.6
        w["semantic"] *= 1.15
        why.append(f"{intent.language} query → lexical ×0.6, semantic ×1.15 (cross-script term overlap unreliable)")
    if intent.confidence < 0.4:
        w["semantic"] *= 1.4
        why.append(f"low intent confidence ({intent.confidence}) → semantic ×1.4")
    return _norm(w), why


def score(signals: dict[str, float | None], weights: dict[str, float]) -> tuple[float, dict[str, float], dict[str, float]]:
    """Weighted fusion with per-candidate renormalisation for missing signals (e.g. no image)."""
    present = {k: weights[k] for k in SIGNALS if weights.get(k, 0) > 0 and signals.get(k) is not None}
    total = sum(present.values())
    eff = {k: v / total for k, v in present.items()} if total > 0 else {}
    contrib = {k: round(eff[k] * float(signals[k]), 4) for k in eff}
    return round(sum(contrib.values()), 4), contrib, eff
