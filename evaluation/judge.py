"""Relevance judge over the hidden ground truth (never visible to any service).

grade(product, need):
  0  a required constraint fails (category / gender / price / size / stock)
  1  requirements met, <50% of preferences met
  2  requirements met, >=50% of preferences met
  3  requirements met, all preferences met (or the need has no preferences)
Binary relevance (P@k, R@k, MRR, MAP, HitRate) uses grade >= 2; NDCG uses graded gain 2^g - 1.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

COLOUR_FAMILY = {"blue": {"blue", "navy"}, "red": {"red", "maroon"}, "green": {"green", "olive"}, "white": {"white", "cream"},
                 "black": {"black"}, "yellow": {"yellow", "gold"}}


def load_truth(path: str | Path) -> dict[str, dict[str, Any]]:
    with open(path) as f:
        return {t["parent_asin"]: t for t in (json.loads(l) for l in f if l.strip())}


def requirements_ok(t: dict[str, Any], req: dict[str, Any]) -> bool:
    if not t.get("in_stock"):
        return False
    if req.get("category") and t["category"] not in req["category"]:
        return False
    if req.get("gender") and t["gender"] not in (req["gender"], "unisex"):
        return False
    if req.get("max_price") is not None and t["price"] > req["max_price"]:
        return False
    if req.get("size"):
        sizes = [s.upper() for s in t["sizes"]]
        if req["size"].upper() not in sizes and "FREE SIZE" not in sizes:
            return False
    return True


def pref_hits(t: dict[str, Any], pref: dict[str, Any]) -> tuple[int, int]:
    hit = n = 0
    for k, v in pref.items():
        n += 1
        if k == "material":
            hit += t["material"] in v
        elif k == "occasion":
            hit += bool(set(t["occasions"]) & set(v))
        elif k == "climate":
            hit += v in t["climates"]
        elif k == "colour":
            hit += any(t["colour"] in COLOUR_FAMILY.get(c, {c}) for c in v)
        elif k == "pattern":
            hit += t["pattern"] in v
        elif k == "comfort":
            hit += bool(t["comfort"]) == bool(v)
        elif k == "sustainable":
            hit += bool(t["sustainable"]) == bool(v)
    return hit, n


def grade(t: dict[str, Any] | None, need: dict[str, Any]) -> int:
    if t is None or not requirements_ok(t, need["req"]):
        return 0
    hit, n = pref_hits(t, need["pref"])
    if n == 0 or hit == n:
        return 3
    return 2 if hit / n >= 0.5 else 1


def all_grades(truth: dict[str, dict[str, Any]], need: dict[str, Any]) -> dict[str, int]:
    return {a: g for a, t in truth.items() if (g := grade(t, need)) > 0}
