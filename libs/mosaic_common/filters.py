"""Hard-constraint evaluation shared by retrieval (BM25 path), ranking (defence in depth) and the
Qdrant filter builder, so the same semantics apply on every path."""
from __future__ import annotations

from typing import Any

from .schemas import HardFilters

FREE_SIZE = "Free Size"


def product_category(p: dict[str, Any]) -> str | None:
    return (p.get("attributes") or {}).get("category")


def product_gender(p: dict[str, Any]) -> str:
    return (p.get("attributes") or {}).get("gender") or "unisex"


def violations(p: dict[str, Any], f: HardFilters) -> list[str]:
    v = []
    price = p.get("price")
    if f.price_max is not None and (price is None or price > f.price_max):
        v.append("price")
    if f.price_min is not None and (price is None or price < f.price_min):
        v.append("price")
    if f.in_stock_only and int(p.get("stock_qty") or 0) <= 0:
        v.append("stock")
    if f.size:
        sizes = [str(s).upper() for s in (p.get("sizes") or [])]
        if f.size.upper() not in sizes and FREE_SIZE.upper() not in sizes:
            v.append("size")
    if f.categories and product_category(p) not in f.categories:
        v.append("category")
    if f.gender and product_gender(p) not in (f.gender, "unisex"):
        v.append("gender")
    return v


def accepts(p: dict[str, Any], f: HardFilters) -> bool:
    return not violations(p, f)
