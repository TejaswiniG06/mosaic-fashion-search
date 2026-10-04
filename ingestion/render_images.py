"""Procedural product-image renderer for the synthetic catalogue.

Renders a flat-lay style product image per (category, colour, pattern): garment silhouette filled
with the colour and a pattern texture (stripes / checks / dots / florals / embroidery / block
print). These are *not* photos, but CLIP can read colour, pattern and coarse garment shape from
them, which is enough to exercise and evaluate the image-text reranking path end-to-end.
With real Amazon data, ingestion/amazon_adapter.py downloads the real product photos instead.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

RGB = {
    "red": (200, 30, 40), "blue": (40, 90, 200), "navy": (25, 35, 90), "black": (25, 25, 25), "white": (245, 245, 245),
    "green": (40, 150, 70), "yellow": (240, 200, 40), "pink": (240, 130, 170), "orange": (240, 130, 30), "purple": (120, 50, 160),
    "grey": (130, 130, 135), "beige": (215, 195, 160), "brown": (120, 75, 40), "maroon": (115, 20, 40), "gold": (212, 175, 55),
    "olive": (110, 120, 45), "teal": (20, 130, 130), "cream": (240, 230, 205),
}
S = 224


def _contrast(c):
    lum = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    return (255, 255, 255) if lum < 140 else (30, 30, 30)


def _shape(cat: str, d: ImageDraw.ImageDraw) -> None:
    """Draw a white silhouette mask for the category."""
    W = 255
    if cat in ("t-shirt", "shirt", "top", "sweater", "hoodie", "jacket", "blazer", "coat", "kurta", "kurti", "sherwani", "nightwear"):
        length = {"coat": 205, "kurta": 200, "kurti": 195, "sherwani": 205, "top": 150, "t-shirt": 165}.get(cat, 175)
        sleeve_long = cat in ("shirt", "sweater", "hoodie", "jacket", "blazer", "coat", "sherwani", "kurta")
        body = [(70, 45), (154, 45), (160, 70), (160, length), (64, length), (64, 70)]
        d.polygon(body, fill=W)
        if sleeve_long:
            d.polygon([(70, 45), (30, 70), (18, 170), (40, 172), (64, 95)], fill=W)
            d.polygon([(154, 45), (194, 70), (206, 170), (184, 172), (160, 95)], fill=W)
        else:
            d.polygon([(70, 45), (35, 70), (48, 100), (64, 88)], fill=W)
            d.polygon([(154, 45), (189, 70), (176, 100), (160, 88)], fill=W)
        if cat == "hoodie":
            d.ellipse((82, 18, 142, 62), fill=W)
        if cat in ("shirt", "blazer", "coat", "sherwani", "kurta"):
            d.polygon([(95, 45), (112, 70), (129, 45)], fill=0)  # collar / placket notch
    elif cat in ("dress", "lehenga", "skirt", "salwar-suit"):
        top = 40 if cat != "skirt" else 70
        if cat != "skirt":
            d.polygon([(88, top), (136, top), (142, 95), (82, 95)], fill=W)
            d.polygon([(88, top), (75, top + 8), (80, top + 30), (88, top + 20)], fill=W)
            d.polygon([(136, top), (149, top + 8), (144, top + 30), (136, top + 20)], fill=W)
        flare = 40 if cat in ("lehenga",) else 25
        d.polygon([(82, 95 if cat != "skirt" else top), (142, 95 if cat != "skirt" else top), (142 + flare + 20, 205), (82 - flare - 20, 205)], fill=W)
    elif cat == "saree":
        d.polygon([(60, 30), (165, 30), (175, 205), (50, 205)], fill=W)
        d.polygon([(130, 30), (200, 60), (190, 205), (160, 205)], fill=W)
    elif cat in ("jeans", "trousers", "palazzo", "activewear", "veshti"):
        wide = 18 if cat in ("palazzo", "veshti") else 0
        d.polygon([(70, 30), (154, 30), (160, 205), (118 + wide // 2, 205), (112, 90), (106 - wide // 2, 205), (64, 205)], fill=W)
        if cat == "veshti":
            d.rectangle((60, 30, 164, 205), fill=W)
    elif cat in ("shorts", "swimwear"):
        d.polygon([(65, 60), (159, 60), (168, 150), (118, 150), (112, 110), (106, 150), (56, 150)], fill=W)
        if cat == "swimwear":
            d.ellipse((80, 20, 108, 52), fill=W)
            d.ellipse((116, 20, 144, 52), fill=W)
    elif cat in ("sneakers", "formal-shoes", "boots", "juttis"):
        if cat == "boots":
            d.polygon([(70, 40), (120, 40), (125, 140), (195, 160), (195, 190), (60, 190)], fill=W)
        else:
            d.polygon([(30, 150), (60, 110), (110, 105), (140, 125), (195, 140), (200, 175), (30, 178)], fill=W)
        d.rectangle((28, 175, 202, 188), fill=W)
    elif cat == "heels":
        d.polygon([(40, 110), (90, 100), (180, 150), (185, 165), (60, 140)], fill=W)
        d.rectangle((50, 140, 62, 195), fill=W)
    elif cat == "sandals":
        d.rounded_rectangle((55, 40, 115, 195), radius=28, fill=W)
        d.rounded_rectangle((120, 40, 180, 195), radius=28, fill=W)
    elif cat == "scarf":
        d.polygon([(60, 25), (165, 25), (150, 205), (120, 205), (112, 80), (104, 205), (74, 205)], fill=W)
    elif cat == "hat":
        d.ellipse((25, 120, 199, 175), fill=W)
        d.chord((62, 50, 162, 170), 180, 360, fill=W)
    else:
        d.rectangle((50, 40, 174, 190), fill=W)


def _texture(base, pattern: str, rng: random.Random) -> Image.Image:
    tex = Image.new("RGB", (S, S), base)
    d = ImageDraw.Draw(tex)
    acc = _contrast(base)
    if pattern == "striped":
        for x in range(-S, S * 2, 18):
            d.line([(x, 0), (x + 60, S)], fill=acc, width=6)
    elif pattern == "checked":
        for x in range(0, S, 22):
            d.line([(x, 0), (x, S)], fill=acc, width=4)
            d.line([(0, x), (S, x)], fill=acc, width=4)
    elif pattern == "polka dot":
        for y in range(6, S, 22):
            for x in range(6 + (y // 22 % 2) * 11, S, 22):
                d.ellipse((x, y, x + 8, y + 8), fill=acc)
    elif pattern == "floral":
        for _ in range(28):
            cx, cy, r = rng.randint(0, S), rng.randint(0, S), rng.randint(5, 10)
            petal = rng.choice([(250, 250, 250), (250, 200, 60), (230, 60, 120), (60, 160, 90)])
            for k in range(5):
                a = 2 * math.pi * k / 5
                px, py = cx + r * math.cos(a), cy + r * math.sin(a)
                d.ellipse((px - r * 0.6, py - r * 0.6, px + r * 0.6, py + r * 0.6), fill=petal)
            d.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=(250, 220, 50))
    elif pattern == "printed":
        for _ in range(14):
            x, y = rng.randint(0, S), rng.randint(0, S)
            d.regular_polygon((x, y, rng.randint(6, 14)), rng.choice([3, 4, 6]), fill=acc)
    elif pattern == "embroidered":
        gold = (212, 175, 55) if base != RGB["gold"] else (150, 20, 30)
        for y in range(150, S, 10):
            for x in range(0, S, 10):
                d.ellipse((x, y, x + 5, y + 5), fill=gold)
        for _ in range(20):
            x, y = rng.randint(0, S), rng.randint(0, 150)
            d.ellipse((x, y, x + 6, y + 6), outline=gold, width=2)
    elif pattern == "block print":
        for y in range(4, S, 26):
            for x in range(4, S, 26):
                d.rectangle((x, y, x + 12, y + 12), outline=acc, width=2)
                d.ellipse((x + 4, y + 4, x + 8, y + 8), fill=acc)
    return tex


def render(cat: str, colour: str, pattern: str, seed: int = 0) -> Image.Image:
    rng = random.Random(f"{cat}{colour}{pattern}{seed}")
    bg = Image.new("RGB", (S, S), (246, 246, 244))
    mask = Image.new("L", (S, S), 0)
    _shape(cat, ImageDraw.Draw(mask))
    mask = mask.filter(ImageFilter.GaussianBlur(0.8))
    tex = _texture(RGB.get(colour, (128, 128, 128)), pattern, rng)
    shadow = Image.new("RGB", (S, S), (210, 210, 208))
    bg.paste(shadow, (4, 5), mask)
    bg.paste(tex, (0, 0), mask)
    edge = mask.point(lambda v: 255 if v > 128 else 0).filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(3))
    bg.paste(Image.new("RGB", (S, S), (90, 90, 90)), (0, 0), edge)
    return bg


def render_all(keys: list[str], out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for key in keys:
        path = out_dir / f"{key}.png"
        if path.exists():
            continue
        cat, colour, pattern = key.split("__")
        render(cat, colour, pattern.replace("-", " ")).save(path, optimize=True)
        n += 1
    print(f"rendered {n} new images into {out_dir} ({len(keys)} unique keys)")
    return n
