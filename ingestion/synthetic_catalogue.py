"""Synthetic fashion catalogue in the exact Amazon Reviews 2023 item-metadata schema.

Why synthetic in this repo's default run: the build sandbox cannot reach HuggingFace or the Amazon
image CDN. The generator mirrors real-world catalogue properties that matter for search:
  * Amazon-style noisy titles, bullet features, details dicts, ratings, prices (INR)
  * attributes are mentioned *incompletely* in text (e.g. occasion stated in ~70% of products,
    season in ~55%), so retrieval must infer, not string-match
  * Indian + western assortment (saree, veshti, kurta, lehenga ... jeans, blazers, sneakers)
  * out-of-stock items, size runs, missing images (~7%) and missing material fields

Hidden ground truth (data/ground_truth.jsonl) is written separately and is used ONLY by the
evaluation judge, never by any service.

Usage:  python -m ingestion.synthetic_catalogue --n 5000 --out data --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from mosaic_common.fashion_kb import MATERIALS, WARM_CATEGORIES

ALPHA = ["XS", "S", "M", "L", "XL", "XXL"]
WAIST = ["28", "30", "32", "34", "36", "38", "40"]
SHOE = ["5", "6", "7", "8", "9", "10", "11"]

# category: genders, materials, price range, occasions, seasons, patterns, size system, display names
SPEC: dict[str, dict] = {
    "t-shirt": dict(g=["men", "women", "unisex"], m=["cotton", "organic cotton", "polyester", "bamboo", "lycra blend", "modal"], p=(299, 1499), occ=["casual", "sports", "travel", "lounge"], sea=["summer", "all-season"], pat=["solid", "printed", "striped"], sz="alpha", names=["T-Shirt", "Tee", "Crew Neck T-Shirt", "Polo T-Shirt"]),
    "shirt": dict(g=["men", "women"], m=["cotton", "linen", "denim", "rayon", "polyester", "khadi"], p=(499, 2999), occ=["office", "casual", "party", "travel"], sea=["summer", "all-season"], pat=["solid", "checked", "striped", "printed"], sz="alpha", names=["Shirt", "Casual Shirt", "Formal Shirt", "Button-Down Shirt"]),
    "top": dict(g=["women"], m=["rayon", "cotton", "georgette", "chiffon", "polyester"], p=(349, 1799), occ=["casual", "party", "office", "beach"], sea=["summer", "all-season"], pat=["solid", "floral", "printed", "striped", "polka dot"], sz="alpha", names=["Top", "Blouse", "Crop Top", "Peplum Top"]),
    "kurta": dict(g=["men", "women"], m=["cotton", "linen", "silk", "khadi", "rayon"], p=(599, 3999), occ=["festive", "traditional", "casual", "office", "wedding"], sea=["all-season", "summer"], pat=["solid", "embroidered", "block print", "printed"], sz="alpha", names=["Kurta", "Straight Kurta", "Pathani Kurta", "Long Kurta"]),
    "kurti": dict(g=["women"], m=["cotton", "rayon", "georgette"], p=(399, 1999), occ=["casual", "office", "festive", "traditional"], sea=["summer", "all-season"], pat=["block print", "floral", "printed", "embroidered", "solid"], sz="alpha", names=["Kurti", "A-Line Kurti", "Flared Kurti", "Tunic Kurti"]),
    "saree": dict(g=["women"], m=["silk", "cotton", "georgette", "chiffon", "linen"], p=(799, 14999), occ=["wedding", "festive", "traditional", "office", "party"], sea=["all-season", "summer"], pat=["embroidered", "solid", "printed", "floral", "block print"], sz="free", names=["Saree", "Saree with Blouse Piece", "Handloom Saree", "Designer Saree"]),
    "lehenga": dict(g=["women"], m=["silk", "velvet", "georgette"], p=(2499, 24999), occ=["wedding", "festive", "party"], sea=["all-season", "winter"], pat=["embroidered", "solid"], sz="alpha", names=["Lehenga Choli", "Bridal Lehenga", "Semi-Stitched Lehenga"]),
    "salwar-suit": dict(g=["women"], m=["cotton", "rayon", "georgette", "silk"], p=(799, 5999), occ=["festive", "office", "casual", "traditional", "wedding"], sea=["all-season", "summer"], pat=["embroidered", "printed", "block print", "solid"], sz="alpha", names=["Salwar Suit Set", "Churidar Suit", "Anarkali Suit", "Salwar Kameez Set"]),
    "dress": dict(g=["women"], m=["cotton", "rayon", "linen", "chiffon", "polyester", "georgette", "organic cotton"], p=(599, 4999), occ=["casual", "party", "beach", "office", "travel"], sea=["summer", "all-season"], pat=["floral", "solid", "printed", "polka dot", "striped"], sz="alpha", names=["Maxi Dress", "Midi Dress", "A-Line Dress", "Sundress", "Shift Dress", "Wrap Dress"]),
    "jeans": dict(g=["men", "women"], m=["denim", "lycra blend"], p=(799, 3499), occ=["casual", "travel", "party"], sea=["all-season", "winter"], pat=["solid"], sz="waist", names=["Jeans", "Slim Fit Jeans", "Straight Jeans", "Bootcut Jeans"]),
    "trousers": dict(g=["men", "women"], m=["cotton", "linen", "polyester", "wool"], p=(699, 3499), occ=["office", "casual", "travel"], sea=["all-season", "summer", "winter"], pat=["solid", "checked"], sz="waist", names=["Trousers", "Chinos", "Formal Trousers", "Pleated Pants"]),
    "shorts": dict(g=["men", "women", "unisex"], m=["cotton", "linen", "polyester", "denim"], p=(299, 1499), occ=["beach", "casual", "sports", "lounge", "travel"], sea=["summer"], pat=["solid", "printed", "striped", "floral"], sz="alpha", names=["Shorts", "Bermuda Shorts", "Cargo Shorts", "Board Shorts"]),
    "skirt": dict(g=["women"], m=["cotton", "denim", "rayon", "georgette"], p=(499, 2499), occ=["casual", "party", "office", "beach"], sea=["summer", "all-season"], pat=["solid", "floral", "printed", "checked"], sz="alpha", names=["Skirt", "Midi Skirt", "Pleated Skirt", "Wrap Skirt"]),
    "palazzo": dict(g=["women"], m=["rayon", "cotton", "georgette"], p=(399, 1499), occ=["casual", "festive", "office", "lounge"], sea=["summer", "all-season"], pat=["solid", "printed", "block print"], sz="alpha", names=["Palazzo Pants", "Flared Palazzo"]),
    "jacket": dict(g=["men", "women", "unisex"], m=["polyester", "nylon", "denim", "leather", "fleece"], p=(999, 6999), occ=["casual", "travel", "party"], sea=["winter", "monsoon"], pat=["solid"], sz="alpha", names=["Jacket", "Bomber Jacket", "Puffer Jacket", "Windcheater", "Biker Jacket"]),
    "blazer": dict(g=["men", "women"], m=["wool", "polyester", "linen", "velvet"], p=(1999, 8999), occ=["office", "party", "wedding"], sea=["all-season", "winter"], pat=["solid", "checked"], sz="alpha", names=["Blazer", "Single-Breasted Blazer", "Slim Fit Blazer"]),
    "sweater": dict(g=["men", "women", "unisex"], m=["wool", "fleece", "cotton"], p=(799, 3999), occ=["casual", "travel", "office"], sea=["winter"], pat=["solid", "striped", "checked"], sz="alpha", names=["Sweater", "Pullover", "Cardigan", "Sweatshirt"]),
    "hoodie": dict(g=["unisex", "men", "women"], m=["fleece", "cotton", "polyester"], p=(699, 2999), occ=["casual", "sports", "travel", "lounge"], sea=["winter"], pat=["solid", "printed"], sz="alpha", names=["Hoodie", "Zip Hoodie", "Pullover Hoodie"]),
    "coat": dict(g=["men", "women"], m=["wool", "polyester"], p=(2499, 11999), occ=["office", "travel", "party"], sea=["winter"], pat=["solid", "checked"], sz="alpha", names=["Overcoat", "Trench Coat", "Long Coat"]),
    "sherwani": dict(g=["men"], m=["silk", "velvet"], p=(4999, 29999), occ=["wedding", "festive"], sea=["all-season", "winter"], pat=["embroidered", "solid"], sz="alpha", names=["Sherwani", "Sherwani Set", "Indo-Western Sherwani"]),
    "veshti": dict(g=["men"], m=["cotton", "silk"], p=(299, 2999), occ=["traditional", "festive", "wedding"], sea=["summer", "all-season"], pat=["solid", "embroidered"], sz="free", names=["Veshti", "Dhoti", "Veshti with Zari Border", "Pattu Veshti"]),
    "swimwear": dict(g=["men", "women"], m=["nylon", "lycra blend", "polyester"], p=(499, 2499), occ=["beach", "sports"], sea=["summer"], pat=["solid", "printed", "floral", "striped"], sz="alpha", names=["Swimsuit", "Swim Trunks", "One-Piece Swimsuit", "Swim Shorts"]),
    "activewear": dict(g=["men", "women", "unisex"], m=["lycra blend", "polyester", "cotton"], p=(399, 1999), occ=["sports", "lounge", "travel"], sea=["all-season"], pat=["solid", "printed", "striped"], sz="alpha", names=["Track Pants", "Joggers", "Leggings", "Training Tights"]),
    "sneakers": dict(g=["men", "women", "unisex"], m=["mesh", "canvas", "leather", "suede"], p=(999, 6999), occ=["casual", "sports", "travel"], sea=["all-season"], pat=["solid"], sz="shoe", names=["Sneakers", "Running Shoes", "Canvas Sneakers", "Walking Shoes"]),
    "sandals": dict(g=["men", "women", "unisex"], m=["eva rubber", "leather", "canvas"], p=(199, 1999), occ=["beach", "casual", "travel"], sea=["summer", "monsoon"], pat=["solid"], sz="shoe", names=["Sandals", "Flip Flops", "Slides", "Strappy Sandals"]),
    "heels": dict(g=["women"], m=["leather", "suede", "velvet"], p=(799, 3999), occ=["party", "wedding", "office"], sea=["all-season"], pat=["solid"], sz="shoe", names=["Block Heels", "Stilettos", "Wedges", "Pumps"]),
    "formal-shoes": dict(g=["men", "women"], m=["leather", "suede"], p=(1299, 5999), occ=["office", "wedding", "party"], sea=["all-season"], pat=["solid"], sz="shoe", names=["Formal Shoes", "Oxfords", "Loafers", "Derby Shoes"]),
    "boots": dict(g=["men", "women", "unisex"], m=["leather", "suede"], p=(1999, 7999), occ=["travel", "casual", "party"], sea=["winter", "monsoon"], pat=["solid"], sz="shoe", names=["Boots", "Chelsea Boots", "Ankle Boots", "Trekking Boots"]),
    "juttis": dict(g=["women", "men"], m=["leather", "velvet"], p=(399, 2499), occ=["wedding", "festive", "traditional"], sea=["all-season"], pat=["embroidered", "solid"], sz="shoe", names=["Juttis", "Mojaris", "Embroidered Juttis"]),
    "scarf": dict(g=["women", "unisex"], m=["wool", "silk", "cotton", "chiffon"], p=(199, 1999), occ=["casual", "travel", "festive", "wedding"], sea=["winter", "all-season"], pat=["solid", "printed", "checked", "floral"], sz="free", names=["Scarf", "Stole", "Shawl", "Dupatta"]),
    "hat": dict(g=["unisex"], m=["cotton", "canvas", "wool"], p=(199, 1499), occ=["beach", "travel", "casual", "sports"], sea=["summer", "winter"], pat=["solid", "printed"], sz="free", names=["Sun Hat", "Baseball Cap", "Bucket Hat", "Beanie"]),
    "nightwear": dict(g=["men", "women"], m=["cotton", "modal", "rayon", "fleece"], p=(399, 1999), occ=["lounge"], sea=["all-season", "summer", "winter"], pat=["solid", "printed", "checked", "floral"], sz="alpha", names=["Pyjama Set", "Night Suit", "Lounge Set", "Nightdress"]),
}
CATEGORY_WEIGHT = {"saree": 2.0, "kurta": 2.0, "kurti": 1.8, "dress": 2.2, "t-shirt": 2.2, "shirt": 2.0, "jeans": 1.5, "top": 1.6, "salwar-suit": 1.4}
ETHNIC_COLOURS = ["red", "maroon", "gold", "green", "pink", "yellow", "blue", "orange", "purple", "cream", "teal"]
ALL_COLOURS = ["red", "blue", "navy", "black", "white", "green", "yellow", "pink", "orange", "purple", "grey", "beige", "brown", "maroon", "olive", "teal", "cream"]
ETHNIC = {"kurta", "kurti", "saree", "lehenga", "salwar-suit", "sherwani", "veshti", "juttis"}
BRANDS = ["Urban Loom", "Kaveri Weaves", "Nila Threads", "Mitti & Co", "Coastline", "Northpeak", "Saanjh", "Thread Theory", "Vastra House",
          "Indigo Lane", "Breeze Wear", "Gully Street", "Aaranya", "Peak Trail", "Madras Mill", "Banyan Tree", "Silk Route", "EcoKnit",
          "Sole Story", "Stride Lab", "Marina Bay", "Kolam Craft", "Rangrez", "Zephyr", "Monsoon Muse"]
ECO_BRANDS = {"EcoKnit", "Mitti & Co", "Aaranya"}
MAT_TITLE = {"cotton": ["Cotton", "Pure Cotton", "100% Cotton"], "organic cotton": ["Organic Cotton"], "linen": ["Linen", "Pure Linen"],
             "khadi": ["Khadi"], "bamboo": ["Bamboo Fabric"], "rayon": ["Rayon", "Viscose Rayon"], "chiffon": ["Chiffon"], "georgette": ["Georgette"],
             "silk": ["Silk", "Art Silk", "Kanjivaram Silk", "Banarasi Silk"], "polyester": ["Polyester"], "recycled polyester": ["Recycled Polyester"],
             "nylon": ["Nylon"], "denim": ["Denim"], "wool": ["Wool", "Woollen", "Merino Wool"], "fleece": ["Fleece"], "leather": ["Leather", "Genuine Leather"],
             "velvet": ["Velvet"], "lycra blend": ["Stretch", "Lycra Blend"], "canvas": ["Canvas"], "mesh": ["Mesh"], "suede": ["Suede"],
             "eva rubber": ["EVA"], "modal": ["Modal"]}
PAT_TITLE = {"solid": ["Solid", "Plain", ""], "floral": ["Floral", "Floral Print"], "striped": ["Striped"], "checked": ["Checked", "Checkered"],
             "printed": ["Printed", "Graphic Print"], "embroidered": ["Embroidered", "Zari Embroidered"], "polka dot": ["Polka Dot"],
             "block print": ["Block Print", "Hand Block Printed"]}
OCC_PHRASE = {"casual": ["everyday casual wear", "casual outings and weekends"], "office": ["office and workwear", "formal meetings and office wear"],
              "party": ["parties and evening events", "party wear and night outs"], "wedding": ["weddings and receptions", "wedding functions"],
              "festive": ["festive occasions like Diwali and Pongal", "festivals and celebrations"], "beach": ["beach holidays and resort wear", "the beach and poolside"],
              "sports": ["gym, running and workouts", "sports and yoga"], "lounge": ["lounging at home and sleep", "relaxing at home"],
              "travel": ["travel and vacations", "trips and travel days"], "traditional": ["temple visits and pooja", "traditional ceremonies"]}
SEASON_PHRASE = {"summer": ["Lightweight weave keeps you cool in hot weather", "Perfect for summer days", "Beat the heat in breathable comfort"],
                 "winter": ["Keeps you warm on chilly days", "Insulated for cold weather", "Winter essential"],
                 "monsoon": ["Water-resistant finish for the monsoon", "Quick-dry fabric handles rain"],
                 "all-season": ["Versatile all-season wear", "Year-round staple"]}
FITS = {"alpha": ["Regular Fit", "Relaxed Fit", "Slim Fit", "Oversized"], "waist": ["Regular Fit", "Slim Fit", "Relaxed Fit"], "shoe": [""], "free": [""]}


def _sizes(system: str, rng: random.Random) -> list[str]:
    if system == "free":
        return ["Free Size"]
    pool = {"alpha": ALPHA, "waist": WAIST, "shoe": SHOE}[system]
    a = rng.randint(0, max(0, len(pool) - 3))
    b = rng.randint(a + 2, len(pool))
    sizes = pool[a:b]
    if rng.random() < 0.2 and len(sizes) > 2:  # a size sold out / missing in the run
        sizes.pop(rng.randrange(len(sizes)))
    return sizes


def _seasons(cat: str, material: str, base: str) -> list[str]:
    breath, warmth = MATERIALS[material][0], MATERIALS[material][1]
    s = {base} if base != "all-season" else {"all-season"}
    if warmth >= 0.8 or cat in WARM_CATEGORIES:
        s.discard("summer")
        s.add("winter")
    if breath >= 0.85 and cat not in WARM_CATEGORIES and warmth < 0.5:
        s.add("summer")
    if MATERIALS[material][3] and cat in ("jacket", "sandals", "boots", "swimwear"):
        s.add("monsoon")
    return sorted(s)


def _climates(cat: str, material: str, seasons: list[str]) -> list[str]:
    breath, warmth, _c, rain_ok, _s = MATERIALS[material]
    out = set()
    hot_ok = breath >= 0.65 and warmth < 0.5 and cat not in WARM_CATEGORIES and cat not in ("blazer", "sherwani", "lehenga", "jeans", "formal-shoes")
    if hot_ok and ("summer" in seasons or "all-season" in seasons):
        out.update({"hot_humid", "hot_dry", "hot"})
    if cat in ("sandals", "swimwear", "hat", "shorts") and "winter" not in seasons:
        out.update({"hot_humid", "hot_dry", "hot"})
    if warmth >= 0.7 or cat in WARM_CATEGORIES or "winter" in seasons:
        out.add("cold")
    if rain_ok or "monsoon" in seasons:
        out.add("rainy")
    if cat not in ("coat",) and warmth < 0.9:
        out.add("mild")
    return sorted(out)


def generate(n: int, seed: int = 42, start_index: int = 0) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    cats = list(SPEC)
    weights = [CATEGORY_WEIGHT.get(c, 1.0) for c in cats]
    products, truth = [], []
    for i in range(start_index, start_index + n):
        cat = rng.choices(cats, weights)[0]
        sp = SPEC[cat]
        gender = rng.choice(sp["g"])
        brand = rng.choice(BRANDS)
        material = rng.choice(sp["m"])
        if brand in ECO_BRANDS and material in ("cotton", "polyester") and rng.random() < 0.7:
            material = "organic cotton" if material == "cotton" else "recycled polyester"
        colour = rng.choice(ETHNIC_COLOURS if cat in ETHNIC else ALL_COLOURS)
        pattern = rng.choice(sp["pat"])
        k = rng.choice([1, 2, 2, 3])
        occasions = rng.sample(sp["occ"], min(k, len(sp["occ"])))
        seasons = _seasons(cat, material, rng.choice(sp["sea"]))
        fit = rng.choice(FITS[sp["sz"]])
        lo, hi = sp["p"]
        price = round(rng.uniform(lo, hi) / 10) * 10 - 1
        if material in ("silk", "velvet", "leather", "wool") and rng.random() < 0.6:
            price = min(hi, int(price * 1.4))
        sizes = _sizes(sp["sz"], rng)
        stock = 0 if rng.random() < 0.10 else rng.randint(1, 250)
        name = rng.choice(sp["names"])
        gtxt = {"men": "Men's", "women": "Women's", "unisex": "Unisex", "kids": "Kids'"}[gender]

        # ---- Amazon-like noisy title: some attributes omitted, order varies
        mat_t = rng.choice(MAT_TITLE[material]) if rng.random() < 0.7 else ""
        pat_t = rng.choice(PAT_TITLE[pattern]) if rng.random() < 0.8 else ""
        col_t = colour.title() if rng.random() < 0.6 else ""
        parts = [brand, gtxt, col_t, mat_t, pat_t, fit if rng.random() < 0.4 else "", name]
        title = " ".join(p for p in parts if p)
        if rng.random() < 0.35:
            tag = rng.choice(occasions)
            title += " - " + {"beach": "Beach Wear", "office": "Office Wear", "party": "Party Wear", "wedding": "Wedding Collection",
                              "festive": "Festive Collection", "sports": "Activewear", "lounge": "Loungewear", "travel": "Travel Essential",
                              "traditional": "Traditional Wear", "casual": "Casual Wear"}[tag]
        if rng.random() < 0.15 and seasons:
            title += " | " + {"summer": "Summer Special", "winter": "Winter Wear", "monsoon": "Monsoon Ready", "all-season": "All Season"}[seasons[0]]

        comfort = fit in ("Relaxed Fit", "Oversized") or MATERIALS[material][2] >= 0.85 or cat in ("nightwear", "activewear")
        features = []
        if rng.random() < 0.85:
            bt = {True: "breathable and soft", False: "durable finish"}[MATERIALS[material][0] >= 0.7]
            features.append(f"Fabric: {MAT_TITLE[material][0]} – {bt}")
        if fit:
            features.append(f"Fit: {fit}" + (" for all-day comfort" if fit in ("Relaxed Fit", "Oversized") else ""))
        if rng.random() < 0.7:
            features.append("Ideal for " + " and ".join(rng.choice(OCC_PHRASE[o]) for o in occasions))
        if rng.random() < 0.55:
            features.append(rng.choice(SEASON_PHRASE[seasons[0]]))
        if comfort and rng.random() < 0.5:
            features.append(rng.choice(["Soft hand-feel, comfortable to wear all day", "Lightweight and comfortable", "Cushioned comfort" if cat in ("sneakers", "sandals") else "Easy, comfortable fit"]))
        if material in ("organic cotton", "recycled polyester", "khadi", "bamboo") or brand in ECO_BRANDS:
            features.append(rng.choice(["Sustainably made with eco-friendly processes", "Made from organic / recycled fibres", "Ethically crafted by artisans"]))
        features.append(rng.choice(["Care: Machine wash cold", "Care: Hand wash recommended", "Care: Dry clean only" if material in ("silk", "velvet", "wool") else "Care: Gentle machine wash"]))
        rng.shuffle(features)

        desc = f"{name} from {brand}" + (f" in {colour}" if rng.random() < 0.5 else "") + "."
        if rng.random() < 0.4:
            desc += " " + rng.choice(["A wardrobe essential designed for Indian weather.", "Crafted with attention to detail.",
                                     "Pairs well with your favourite accessories.", "Designed for effortless styling."])
        details = {"Department": {"men": "Mens", "women": "Womens", "unisex": "Unisex"}[gender], "Fit Type": fit or None,
                   "Pattern": pattern.title(), "Color": colour.title(), "Item model number": f"MF{i:06d}",
                   "Date First Available": f"{rng.choice(['January', 'March', 'June', 'September', 'November'])} {rng.randint(1, 28)}, {rng.choice([2023, 2024, 2025, 2026])}"}
        if rng.random() < 0.85:
            details["Material"] = MAT_TITLE[material][0]
        details = {k: v for k, v in details.items() if v}

        asin = f"MF{i:07d}"
        img_key = f"{cat}__{colour}__{pattern.replace(' ', '-')}"
        images = [] if rng.random() < 0.07 else [{"large": f"local://renders/{img_key}.png", "thumb": f"local://renders/{img_key}.png", "hi_res": None, "variant": "MAIN"}]
        products.append({
            "parent_asin": asin, "main_category": "AMAZON FASHION", "title": title, "store": brand,
            "average_rating": round(rng.uniform(3.0, 4.9), 1), "rating_number": rng.randint(3, 25000),
            "features": features, "description": [desc], "price": float(price), "currency": "INR", "images": images,
            "categories": ["Clothing, Shoes & Jewelry", {"men": "Men", "women": "Women", "unisex": "Unisex"}[gender], name],
            "details": details, "stock_qty": stock, "sizes": sizes,
        })
        truth.append({
            "parent_asin": asin, "category": cat, "gender": gender, "material": material, "colour": colour, "pattern": pattern,
            "occasions": occasions, "seasons": seasons, "climates": _climates(cat, material, seasons), "comfort": comfort,
            "sustainable": MATERIALS[material][4] or brand in ECO_BRANDS, "price": float(price), "sizes": sizes, "in_stock": stock > 0,
            "brand": brand, "image_key": img_key if images else None,
        })
    return products, truth


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data")
    ap.add_argument("--render", action="store_true", help="render product images (see ingestion/render_images.py)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    products, truth = generate(a.n, a.seed)
    with open(out / "catalogue.jsonl", "w") as f:
        for p in products:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with open(out / "ground_truth.jsonl", "w") as f:
        for t in truth:
            f.write(json.dumps(t) + "\n")
    print(f"wrote {len(products)} products -> {out/'catalogue.jsonl'} (+ hidden ground_truth.jsonl)")
    if a.render:
        from ingestion.render_images import render_all
        keys = sorted({t["image_key"] for t in truth if t["image_key"]})
        render_all(keys, Path(a.out) / "images" / "renders")


if __name__ == "__main__":
    main()
