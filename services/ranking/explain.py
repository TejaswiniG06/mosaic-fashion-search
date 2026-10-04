"""Grounded explanation generation.

Template explanations are assembled ONLY from (a) the parsed user intent and (b) real product
metadata / computed signals — every clause is traceable to a field. Optional LLM polishing receives
the same facts and its output is rejected (template kept) if it introduces any number or vocabulary
term (material, colour, occasion, category) that is not present in the facts.
"""
from __future__ import annotations

import re
from typing import Any

from mosaic_common import fashion_kb as kb
from mosaic_common.schemas import Intent
from services.retrieval.bm25 import doc_tokens, query_tokens

from .signals import HOT

VOCAB = set(kb.MATERIALS) | set(kb.COLOURS) | set(kb.OCCASIONS) | set(kb.CATEGORIES)


def _fmt_price(x: float | None) -> str:
    return f"₹{x:,.0f}" if x is not None else "n/a"


def constraint_facts(p: dict[str, Any], intent: Intent, filters) -> list[str]:
    out = []
    if filters.price_max is not None and p.get("price") is not None:
        out.append(f"{_fmt_price(p['price'])} within your {_fmt_price(filters.price_max)} budget")
    elif filters.price_min is not None and p.get("price") is not None:
        out.append(f"{_fmt_price(p['price'])} (≥ {_fmt_price(filters.price_min)})")
    if filters.size:
        out.append(f"size {filters.size} available" if filters.size.upper() in [s.upper() for s in p.get("sizes") or []] else "free size")
    if filters.in_stock_only:
        out.append(f"in stock ({p.get('stock_qty', 0)} units)")
    if filters.categories:
        out.append(f"category {(p.get('attributes') or {}).get('category')}")
    if filters.gender:
        out.append(f"for {(p.get('attributes') or {}).get('gender')}")
    return out


def reason_for(signal: str, value: float, intent: Intent, p: dict[str, Any], clip_prompt: str | None) -> str | None:
    a = p.get("attributes") or {}
    mats = a.get("materials") or []
    if signal == "occasion":
        hit = [o for o in intent.occasion if o in (a.get("occasions") or [])]
        if hit:
            return f"listed for {', '.join(hit)}"
        if a.get("occasions"):
            return f"suits related occasions ({', '.join(a['occasions'][:2])})"
        return None
    if signal == "climate" and intent.climate:
        where = f" in {intent.destination.title()}" if intent.destination else ""
        if intent.climate in HOT:
            m = f"{mats[0]} " if mats else ""
            return f"{m}fabric is breathable (breathability {a.get('breathability', 0):.2f}) for {kb.CLIMATE_DESC[intent.climate]}{where}"
        if intent.climate == "cold":
            return f"warm option (warmth {a.get('warmth', 0):.2f}) for cold weather{where}"
        if intent.climate == "rainy":
            return "rain-friendly material" + where if a.get("rain_ok") else None
        return f"comfortable for {kb.CLIMATE_DESC.get(intent.climate, intent.climate)}{where}"
    if signal == "material":
        if intent.material and any(m in intent.material for m in mats):
            return f"made of {', '.join(m for m in mats if m in intent.material)} as requested"
        if intent.sustainability and a.get("sustainable"):
            return "eco-friendly (organic/recycled/handcrafted materials)"
        if mats and value >= 0.6:
            return f"{mats[0]} suits the conditions"
        return None
    if signal == "comfort":
        tags = a.get("comfort_tags") or []
        return f"comfort features: {', '.join(tags[:3])}" if tags else (f"comfortable {mats[0]}" if mats else None)
    if signal == "visual":
        bits = []
        from services.ranking.signals import colour_sim
        cols = [c for c in (a.get("colours") or []) if any(colour_sim(q, c) >= 0.6 for q in intent.colour)]
        if cols:
            bits.append(f"colour {cols[0]}" + ("" if cols[0] in intent.colour else f" (close to {intent.colour[0]})"))
        pats = [x for x in (a.get("patterns") or []) if x in intent.pattern]
        if pats:
            bits.append(f"{pats[0]} pattern")
        if p.get("images") and clip_prompt and value >= 0.7:
            bits.append(f"photo visually matches “{clip_prompt}”")
        elif p.get("images") and intent.has_query_image:
            bits.append("photo resembles your uploaded image")
        return ", ".join(bits) if bits else None
    if signal == "lexical":
        q = set(query_tokens(intent.normalized_query_en or intent.original_query))
        overlap = [t for t in dict.fromkeys(doc_tokens({"title": p.get("title", "")})) if t in q][:3]
        return f"title mentions {', '.join(overlap)}" if overlap else None
    if signal == "semantic":
        return "closely matches the meaning of your request"
    return None


def template_explanation(intent: Intent, p: dict[str, Any], comps: dict[str, float], contrib: dict[str, float], filters,
                         clip_prompt: str | None) -> tuple[str, list[str]]:
    reasons = []
    generic = {"semantic", "lexical"}  # specific, attribute-grounded reasons first
    for sig, _c in sorted(contrib.items(), key=lambda kv: (kv[0] in generic, -kv[1])):
        if comps.get(sig) is None or comps[sig] < 0.45:
            continue
        r = reason_for(sig, comps[sig], intent, p, clip_prompt)
        if r and r not in reasons:
            reasons.append(r)
        if len(reasons) == 3:
            break
    cons = constraint_facts(p, intent, filters)
    text = (("Why: " + "; ".join(reasons) + ".") if reasons else "Why: best overall match among filtered products.")
    if cons:
        text += " Constraints met: " + ", ".join(cons) + "."
    return text, cons


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def grounded(llm_text: str, facts: str) -> bool:
    if not llm_text or len(llm_text.split()) > 60:
        return False
    fact_nums = {n.replace(",", "") for n in _NUM.findall(facts)}
    if any(n.replace(",", "") not in fact_nums for n in _NUM.findall(llm_text)):
        return False
    low_facts, low = facts.lower(), llm_text.lower()
    return not any(re.search(rf"\b{re.escape(v)}\b", low) and v not in low_facts for v in VOCAB)
