"""Per-candidate ranking signals, each in [0, 1] (None = not applicable for this query).

semantic : e5 cosine (min-max over the candidate set)
lexical  : BM25 score (min-max over the candidate set)
visual   : appearance agreement. CLIP image–text (or image–image) cosine, min-max over candidates with an
           image; when the user names colours/patterns it is fused 60/40 with catalogue colour/pattern
           attributes (colour-family aware, navy≈blue). Image missing => attribute agreement only
           (image fallback); no image and no colour/pattern asked => not applicable
occasion : compatibility of product occasions with requested occasions (with soft cross-occasion credit)
climate  : physical suitability for the resolved climate, from material breathability/warmth,
           garment type and season cues  (e.g. Chennai + summer => hot_humid)
material : explicit material match / sustainability / climate-implied fabric preference
comfort  : material comfort + comfort features (relaxed fit, stretch, cushioned, breathable ...)
"""
from __future__ import annotations

from typing import Any

from mosaic_common import fashion_kb as kb
from mosaic_common.schemas import Candidate, Intent

HOT = {"hot", "hot_humid", "hot_dry"}
COMFORT_OCCASIONS = {"lounge", "travel", "sports"}


def minmax(values: list[float | None]) -> list[float | None]:
    xs = [v for v in values if v is not None]
    if not xs:
        return [None] * len(values)
    lo, hi = min(xs), max(xs)
    if hi - lo < 1e-9:
        return [0.5 if v is not None else None for v in values]
    return [None if v is None else (v - lo) / (hi - lo) for v in values]


def occasion_signal(intent: Intent, a: dict[str, Any]) -> float | None:
    if not intent.occasion:
        return None
    po = a.get("occasions") or []
    if not po:
        return 0.25
    return sum(max(kb.occasion_compat(o, p) for p in po) for o in intent.occasion) / len(intent.occasion)


def climate_signal(intent: Intent, a: dict[str, Any]) -> float | None:
    c = intent.climate
    if not c:
        return None
    b, w = float(a.get("breathability", 0.5)), float(a.get("warmth", 0.5))
    seasons = a.get("seasons") or []
    cat = a.get("category")
    mats = a.get("materials") or []
    if c in HOT:
        s = 0.55 * b + 0.25 * (1 - w) + 0.2 * (1.0 if "summer" in seasons else 0.5 if ("all-season" in seasons or not seasons) else 0.0)
        if cat in kb.HEAVY_CATEGORIES:
            s *= 0.4
        if "winter" in seasons:
            s *= 0.6
        if cat in kb.OPEN_CATEGORIES:
            s = min(1.0, s + 0.1)
        if c == "hot_humid" and any(m in ("polyester", "nylon", "recycled polyester") for m in mats) and cat != "swimwear":
            s *= 0.85
        return max(0.0, min(1.0, s))
    if c == "cold":
        s = 0.55 * w + 0.25 * (1.0 if cat in kb.WARM_CATEGORIES else 0.0) + 0.2 * (1.0 if "winter" in seasons else 0.3 if "all-season" in seasons else 0.0)
        if cat in kb.OPEN_CATEGORIES:
            s *= 0.4
        return max(0.0, min(1.0, s))
    if c == "rainy":
        s = 0.5 * (1.0 if a.get("rain_ok") else 0.0) + 0.3 * (1.0 if "monsoon" in seasons else 0.0) + 0.2 * (1 - 0.5 * w)
        if any(m in ("silk", "suede", "velvet") for m in mats):
            s *= 0.5
        return max(0.0, min(1.0, s))
    # mild
    s = 0.6 + 0.2 * (1.0 if "all-season" in seasons else 0.0) - (0.4 if cat == "coat" else 0.0)
    return max(0.0, min(1.0, s))


def material_active(intent: Intent) -> bool:
    return bool(intent.material) or intent.sustainability or (intent.climate in HOT | {"cold"})


def material_signal(intent: Intent, a: dict[str, Any]) -> float | None:
    if not material_active(intent):
        return None
    mats = a.get("materials") or []
    parts = []
    if intent.material:
        if not mats:
            parts.append(0.2)
        elif any(m in intent.material for m in mats):
            parts.append(1.0)
        else:
            fams = {kb.MATERIAL_FAMILY.get(m) for m in intent.material}
            parts.append(0.5 if any(kb.MATERIAL_FAMILY.get(m) in fams for m in mats) else 0.0)
    if intent.sustainability:
        parts.append(1.0 if a.get("sustainable") else 0.0)
    if not parts:  # climate-implied fabric preference
        if intent.climate in HOT:
            parts.append(float(a.get("breathability", 0.5)))
        elif intent.climate == "cold":
            parts.append(float(a.get("warmth", 0.5)))
    return sum(parts) / len(parts)


def comfort_active(intent: Intent) -> bool:
    return intent.comfort or bool(set(intent.occasion) & COMFORT_OCCASIONS)


def comfort_signal(intent: Intent, a: dict[str, Any]) -> float | None:
    if not comfort_active(intent):
        return None
    tags = a.get("comfort_tags") or []
    return 0.5 * float(a.get("material_comfort", 0.5)) + 0.5 * min(1.0, len(tags) / 2)


COLOUR_FAMILY = {
    ("navy", "blue"): 0.8, ("teal", "blue"): 0.5, ("teal", "green"): 0.5, ("olive", "green"): 0.7, ("maroon", "red"): 0.7,
    ("pink", "red"): 0.3, ("cream", "white"): 0.7, ("cream", "beige"): 0.6, ("beige", "brown"): 0.4, ("gold", "yellow"): 0.6,
    ("orange", "yellow"): 0.3, ("purple", "pink"): 0.3, ("grey", "black"): 0.3,
}


def colour_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return COLOUR_FAMILY.get((a, b)) or COLOUR_FAMILY.get((b, a)) or 0.0


def appearance_attr(intent: Intent, a: dict[str, Any]) -> float | None:
    parts = []
    if intent.colour:
        pc = a.get("colours") or []
        parts.append(max((colour_sim(q, c) for q in intent.colour for c in pc), default=0.15 if not pc else 0.0))
    if intent.pattern:
        pp = a.get("patterns") or []
        parts.append(1.0 if any(p in intent.pattern for p in pp) else (0.15 if not pp else 0.0))
    return sum(parts) / len(parts) if parts else None


def compute_all(intent: Intent, cands: list[Candidate], use_visual: bool, use_context: bool) -> list[dict[str, float | None]]:
    sem = minmax([c.dense if (c.dense or c.dense_rank) else None for c in cands])
    lex = minmax([c.bm25 for c in cands])
    vis = minmax([c.visual for c in cands]) if use_visual else [None] * len(cands)
    out = []
    for i, c in enumerate(cands):
        a = (c.product or {}).get("attributes") or {}
        v = vis[i]
        if use_visual and use_context:
            attr = appearance_attr(intent, a)
            if attr is not None:
                v = attr if v is None else 0.6 * v + 0.4 * attr
        row: dict[str, float | None] = {"semantic": sem[i] if sem[i] is not None else 0.0, "lexical": lex[i] if lex[i] is not None else 0.0,
                                        "visual": v}
        if use_context:
            row.update(occasion=occasion_signal(intent, a), climate=climate_signal(intent, a),
                       material=material_signal(intent, a), comfort=comfort_signal(intent, a))
        else:
            row.update(occasion=None, climate=None, material=None, comfort=None)
        out.append(row)
    return out
