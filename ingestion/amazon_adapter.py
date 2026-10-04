"""Amazon Reviews 2023 (McAuley Lab) -> MOSAIC catalogue adapter.

Input : meta_Amazon_Fashion.jsonl(.gz)  (or meta_Clothing_Shoes_and_Jewelry.jsonl.gz) — item metadata with
        fields main_category, title, average_rating, rating_number, features, description, price, images,
        videos, store, categories, details, parent_asin, bought_together.
Output: catalogue JSONL in the MOSAIC Product schema (a superset of the Amazon schema), ready for
        `python -m ingestion.load_catalogue`.

Mapping decisions (documented, configurable):
  * price      : Amazon price is USD (often null). Converted to INR with --usd-inr (default 83.0) so INR
                 budgets in queries work; items with no price keep price=null and are excluded only by
                 explicit budget filters.
  * stock_qty  : not in the dataset. Default --default-stock (10) so items are searchable; a real
                 deployment would join the inventory service here.
  * sizes      : parsed from details["Size"] / title tokens when present, else ["Free Size"] for accessories
                 and [] otherwise (=> excluded only when the user asks for a size).
  * images     : first MAIN image `large` URL (or hi_res). Downloaded later by
                 ingestion/download_images.py; unreachable images fall back to text-only ranking.
  * Records without title or with non-fashion main_category can be dropped with --strict.

Download (on a machine with HuggingFace access):
  wget https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw/meta_categories/meta_Amazon_Fashion.jsonl
  python -m ingestion.amazon_adapter --input meta_Amazon_Fashion.jsonl --out data/amazon_catalogue.jsonl --limit 20000
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path
from typing import Any, Iterator

SIZE_TOKENS = re.compile(r"\b(XXS|XS|S|M|L|XL|XXL|XXXL|\d{1,2}W|\d{2})\b")
ASIN_OK = re.compile(r"^[A-Za-z0-9_\-]{3,40}$")


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def parse_price(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"\d+(?:\.\d+)?", str(v).replace(",", ""))
    return float(m.group(0)) if m else None


def convert(rec: dict[str, Any], usd_inr: float, default_stock: int) -> dict[str, Any] | None:
    asin = rec.get("parent_asin") or rec.get("asin")
    title = (rec.get("title") or "").strip()
    if not asin or not ASIN_OK.match(str(asin)) or len(title) < 3:
        return None
    price_usd = parse_price(rec.get("price"))
    details = rec.get("details") or {}
    if not isinstance(details, dict):
        details = {}
    size_src = str(details.get("Size", "")) + " " + str(details.get("Size Name", ""))
    sizes = list(dict.fromkeys(SIZE_TOKENS.findall(size_src.upper())))
    images = []
    for im in rec.get("images") or []:
        if isinstance(im, dict) and (im.get("large") or im.get("hi_res")):
            images.append({"large": im.get("large") or im.get("hi_res"), "thumb": im.get("thumb"), "hi_res": im.get("hi_res"),
                           "variant": im.get("variant") or "MAIN"})
    images.sort(key=lambda x: 0 if x["variant"] == "MAIN" else 1)
    return {
        "parent_asin": str(asin), "title": title[:500], "main_category": rec.get("main_category") or "AMAZON FASHION",
        "store": rec.get("store"), "average_rating": rec.get("average_rating"), "rating_number": rec.get("rating_number"),
        "features": [str(x) for x in (rec.get("features") or [])][:15], "description": [str(x) for x in (rec.get("description") or [])][:5],
        "price": round(price_usd * usd_inr, 2) if price_usd is not None else None, "currency": "INR",
        "images": images[:3], "categories": [str(c) for c in (rec.get("categories") or [])][:6],
        "details": {str(k): v for k, v in details.items() if isinstance(v, (str, int, float))},
        "stock_qty": default_stock, "sizes": sizes,
        "url": f"https://www.amazon.com/dp/{asin}",   # genuine product page for real Amazon items
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="data/amazon_catalogue.jsonl")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--usd-inr", type=float, default=83.0)
    ap.add_argument("--default-stock", type=int, default=10)
    ap.add_argument("--strict", action="store_true", help="drop items without price or image")
    a = ap.parse_args()
    n_in = n_out = 0
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for rec in read_jsonl(Path(a.input)):
            n_in += 1
            p = convert(rec, a.usd_inr, a.default_stock)
            if p is None or (a.strict and (p["price"] is None or not p["images"])):
                continue
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
            n_out += 1
            if a.limit and n_out >= a.limit:
                break
    print(f"read {n_in} records, wrote {n_out} products -> {a.out}")


if __name__ == "__main__":
    main()
