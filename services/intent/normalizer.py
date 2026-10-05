"""Attribute normalisation: maps free-form LLM slot values onto the canonical vocabulary and merges
LLM output with deterministic parsing (rules own hard constraints; LLM fills semantic gaps)."""
from __future__ import annotations

from typing import Any

from mosaic_common import fashion_kb as kb
from mosaic_common.schemas import Intent


def _map_list(values: Any, lexicon: dict[str, str], allowed: set[str] | None = None) -> tuple[list[str], list[str]]:
    if values is None:
        return [], []
    if isinstance(values, str):
        values = [values]
    out, dropped = [], []
    for v in values:
        if not isinstance(v, str) or not v.strip():
            continue
        s = v.strip().lower()
        canon = lexicon.get(s)
        if canon is None:
            hits = kb.find_terms(s, lexicon)
            canon = hits[0][1] if hits else None
        if canon is None and allowed and s in allowed:
            canon = s
        if canon:
            out.append(canon)
        else:
            dropped.append(v)
    return list(dict.fromkeys(out)), dropped


def _num(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def normalise_llm(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    warn: list[str] = []
    cats, d1 = _map_list(raw.get("category"), kb.CATEGORY_LEX, set(kb.CATEGORIES))
    occ, d2 = _map_list(raw.get("occasion"), kb.OCCASION_SYN, set(kb.OCCASIONS))
    mats, d3 = _map_list(raw.get("material"), kb.MATERIAL_SYN, set(kb.MATERIALS))
    cols, d4 = _map_list(raw.get("colour") or raw.get("color"), kb.COLOUR_SYN, set(kb.COLOURS))
    pats, d5 = _map_list(raw.get("pattern"), kb.PATTERN_SYN, set(kb.PATTERNS))
    styles, _ = _map_list(raw.get("style"), kb.STYLE_SYN)
    season = None
    if isinstance(raw.get("season"), str):
        season = kb.SEASON_SYN.get(raw["season"].lower()) or (raw["season"].lower() if raw["season"].lower() in ("summer", "winter", "monsoon") else None)
    dest = raw.get("destination")
    dest = dest.strip().lower() if isinstance(dest, str) and dest.strip() else None
    if dest and dest not in kb.DESTINATIONS:
        dest = kb.DESTINATION_ML.get(dest, dest)
    gender = raw.get("gender")
    gender = kb.GENDER_SYN.get(gender.lower()) if isinstance(gender, str) else None
    for name, dropped in (("category", d1), ("occasion", d2), ("material", d3), ("colour", d4), ("pattern", d5)):
        if dropped:
            warn.append(f"llm {name} values not in vocabulary dropped: {dropped[:3]}")
    out = {
        "normalized_query_en": raw.get("normalized_query_en") if isinstance(raw.get("normalized_query_en"), str) else "",
        "category": cats, "category_explicit": bool(raw.get("category_explicit")) and bool(cats), "occasion": occ, "season": season,
        "destination": dest, "comfort": bool(raw.get("comfort")), "style": styles, "material": mats, "colour": cols, "pattern": pats,
        "budget_min": _num(raw.get("budget_min")), "budget_max": _num(raw.get("budget_max")),
        "size": str(raw["size"]).upper() if raw.get("size") else None, "gender": gender if gender != "unisex" else None,
        "sustainability": bool(raw.get("sustainability")),
        "brand": [b for b in (raw.get("brand") or []) if isinstance(b, str)][:3],
    }
    return out, warn


def merge(rules: Intent, llm: dict[str, Any], warn: list[str]) -> Intent:
    d = rules.model_dump()
    for k in ("category", "occasion", "material", "colour", "pattern", "style", "brand"):
        merged = list(dict.fromkeys((llm.get(k) or []) + d[k]))
        d[k] = merged
    for k in ("season", "destination", "gender"):
        d[k] = d[k] or llm.get(k)
    for k in ("comfort", "sustainability"):
        d[k] = d[k] or llm.get(k, False)
    # Hard numeric/size constraints must have deterministic evidence in the query.
    for k in ("budget_min", "budget_max", "size"):
        d[k] = getattr(rules, k)
    # An LLM cannot expand explicit hard categories or invent new hard constraints.
    if rules.category_explicit:
        d["category"] = rules.category
    d["category_explicit"] = rules.category_explicit
    d["gender"] = rules.gender
    if llm.get("normalized_query_en"):
        d["normalized_query_en"] = llm["normalized_query_en"] + " | " + rules.normalized_query_en
    d["climate"] = kb.resolve_climate(d["destination"], d["season"]) or rules.climate
    if not d["climate"] and "beach" in d["occasion"]:
        d["climate"] = "hot_humid"
    d["visual_intent"] = bool(d["colour"] or d["pattern"] or rules.visual_intent)
    d["parser"] = "llm+rules"
    d["confidence"] = min(1.0, rules.confidence + 0.2)
    d["warnings"] = rules.warnings + warn
    return Intent(**d)
