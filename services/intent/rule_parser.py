"""Deterministic multilingual intent parser (English / Tamil / Tanglish / Hindi / Hinglish).

This is (a) the always-available fallback when the LLM is disabled/slow/failing, and (b) the
deterministic extractor for numeric slots (budget, size) which are merged into LLM output because
regexes are more reliable than LLMs for numbers.
"""
from __future__ import annotations

import re

from mosaic_common import fashion_kb as kb
from mosaic_common.schemas import Intent

from .language import detect_language

_CUR = r"(?:₹|rs\.?|inr|rupees?)?"
_NUM = r"(\d+(?:[.,]\d+)?)(?:\s*(k)\b)?"
_UNIT = r"\s*(?:rs\.?|rupees?|/-|inr|ரூபாய்|ரூ|रुपये|रुपए|रु|rupay|rubai|rooba|rupaye)?"
MAX_PRE = re.compile(r"(?:under|below|less than|within|upto|up to|max(?:imum)?|budget(?: of| is)?|not more than|cheaper than|<=?|atmost|at most|kam se kam)\s*" + _CUR + r"\s*" + _NUM, re.I)
MAX_POST = re.compile(_CUR + r"\s*" + _NUM + _UNIT + r"\s*(?:kulla|ku kulla|kku kulla|ulla|kkulla|க்குள்|குள்|க்கு\s*கீழ்|க்குக்\s*கீழ்|க்கு\s*குறைவ\w*|"
                      r"से\s*कम|के\s*अंदर|के\s*भीतर|तक|के\s*नीचे|se\s*kam|tak|ke\s*andar|ke\s*neeche|max|or\s*less|and\s*below|budget)", re.I)
MIN_PRE = re.compile(r"(?:above|over|more than|at least|minimum|starting(?: from)?|>=?)\s*" + _CUR + r"\s*" + _NUM, re.I)
MIN_POST = re.compile(_CUR + r"\s*" + _NUM + _UNIT + r"\s*(?:से\s*ज़?्यादा|से\s*अधिक|க்கு\s*மேல்|ku\s*mela|ku\s*mel|se\s*zyada|se\s*upar|and\s*above|\+|plus)", re.I)
RANGE = re.compile(r"(?:between|from)?\s*" + _CUR + r"\s*" + _NUM + _UNIT + r"\s*(?:-|to|and|से|முதல்)\s*" + _CUR + r"\s*" + _NUM + _UNIT, re.I)
CURRENCY_ONLY = re.compile(r"(?:₹|rs\.?\s*|inr\s*)(\d+(?:[.,]\d+)?)(?:\s*(k)\b)?|(\d+(?:[.,]\d+)?)(?:\s*(k)\b)?\s*(?:rs|rupees|ரூபாய்|रुपये|रुपए)", re.I)
SIZE_WORD = r"(?:size|சைஸ்|அளவு|साइज़|साइज|saiz)"
SIZE_RE = [
    re.compile(SIZE_WORD + r"\s*[:\-]?\s*(xxxl|xxl|xl|xs|s|m|l|\d{1,2})\b", re.I),
    re.compile(r"\b(xxxl|xxl|xl|xs|s|m|l|\d{1,2})\s*" + SIZE_WORD, re.I),
    re.compile(r"\b(?:uk|waist)\s*(\d{1,2})\b", re.I),
    re.compile(r"\b(\d{2})\s*waist\b", re.I),
    re.compile(r"(?<![\w])(xxxl|xxl|xl|xs)(?![\w])", re.I),
]
QUOTED = re.compile(r"[\"“']([^\"”']{2,40})[\"”']")
FOOTWEAR_WORDS = {"footwear", "காலணி", "காலணிகள்", "जूते-चप्पल", "फुटवियर"}
CLIMATE_WORDS = {"humid": "hot_humid", "humidity": "hot_humid", "sweaty": "hot_humid", "sticky": "hot_humid", "dry heat": "hot_dry",
                 "ஈரப்பதம்": "hot_humid", "புழுக்கம்": "hot_humid", "उमस": "hot_humid", "pulukkam": "hot_humid", "umas": "hot_humid"}


DEST_LEX = {**{d: d for d in kb.DESTINATIONS}, **kb.DESTINATION_ML}


def _num(v: str, k: str | None) -> float:
    x = float(v.replace(",", ""))
    return x * 1000 if k else x


def parse_budget(q: str) -> tuple[float | None, float | None]:
    lo = hi = None
    m = RANGE.search(q)
    if m:
        a, b = _num(m.group(1), m.group(2)), _num(m.group(3), m.group(4))
        if a >= 100 and b >= 100 and b > a:
            return a, b
    for rx in (MAX_PRE, MAX_POST):
        m = rx.search(q)
        if m:
            hi = _num(m.group(1), m.group(2))
            break
    for rx in (MIN_PRE, MIN_POST):
        m = rx.search(q)
        if m:
            lo = _num(m.group(1), m.group(2))
            break
    if hi is None and lo is None:
        m = CURRENCY_ONLY.search(q)
        if m:
            hi = _num(m.group(1) or m.group(3), m.group(2) or m.group(4))
    if hi is not None and hi < 50:  # "under 2" etc. — not a price
        hi = None
    return lo, hi


def parse_size(q: str) -> str | None:
    if re.search(r"free\s*size|ப்ரீ\s*சைஸ்|फ्री\s*साइज", q, re.I):
        return "Free Size"
    for rx in SIZE_RE:
        m = rx.search(q)
        if m:
            return m.group(1).upper()
    return None


def _canon(found: list[tuple[str, str]]) -> list[str]:
    return list(dict.fromkeys(c for _, c in found))


def parse(query: str, has_query_image: bool = False) -> Intent:
    q = query.strip()
    lang, lconf, _ev = detect_language(q)
    low = q.lower()

    categories = _canon(kb.find_terms(q, kb.CATEGORY_LEX))
    if not categories and any(w in low for w in FOOTWEAR_WORDS):
        categories = [c for c, m in kb.CATEGORIES.items() if m["group"] == "footwear"]
    occasions = _canon(kb.find_terms(q, kb.OCCASION_SYN))
    seasons = _canon(kb.find_terms(q, kb.SEASON_SYN))
    dest_found = kb.find_terms(q, DEST_LEX)
    destination = dest_found[0][1] if dest_found else None
    materials = _canon(kb.find_terms(q, kb.MATERIAL_SYN))
    colours = _canon(kb.find_terms(q, kb.COLOUR_SYN))
    patterns = _canon(kb.find_terms(q, kb.PATTERN_SYN))
    styles = _canon(kb.find_terms(q, kb.STYLE_SYN))
    genders = _canon(kb.find_terms(q, kb.GENDER_SYN))
    comfort = bool(kb.find_terms(q, kb.COMFORT_WORDS))
    sustain = bool(kb.find_terms(q, kb.SUSTAIN_WORDS))
    lo, hi = parse_budget(q)
    size = parse_size(q)
    quoted = [m.group(1).strip() for m in QUOTED.finditer(q)]

    season = seasons[0] if seasons else None
    climate = kb.resolve_climate(destination, season)
    if not climate:
        cw = kb.find_terms(q, CLIMATE_WORDS)
        if cw:
            climate = cw[0][1]
    if not climate and "beach" in occasions:
        climate = "hot_humid"
    if "formal" in low and "office" not in occasions and not occasions:
        occasions = ["office"]
    gender = genders[0] if genders else None
    if gender == "unisex":
        gender = None

    visual = bool(colours or patterns or has_query_image or any(w in low for w in kb.VISUAL_WORDS))
    slots = sum(bool(x) for x in (categories, occasions, season or climate, materials, colours, patterns, styles, gender,
                                  comfort, sustain, hi or lo, size, destination))

    # English canonical rewrite (feeds BM25 + CLIP text tower; keeps original for dense e5)
    leftovers = [w for w in re.findall(r"[a-zA-Z][a-zA-Z\-']+", q)
                 if w.lower() not in kb.STOPWORDS_EN and w.lower() not in kb.TANGLISH_MARKERS and w.lower() not in kb.HINGLISH_MARKERS]
    pieces = []
    if gender:
        pieces.append({"men": "men's", "women": "women's", "kids": "kids"}.get(gender, gender))
    pieces += colours + patterns + materials + styles
    pieces += [c.replace("-", " ") for c in categories] or ["outfit"]
    if comfort:
        pieces.append("comfortable breathable")
    if occasions:
        pieces.append("for " + " ".join(occasions))
    if season:
        pieces.append(season)
    if climate:
        pieces.append(kb.CLIMATE_DESC.get(climate, climate))
    if destination:
        pieces.append(destination)
    if sustain:
        pieces.append("sustainable organic eco-friendly")
    norm = " ".join(pieces)
    extra = [w for w in leftovers if w.lower() not in norm.lower()]
    if lang == "en" and extra:
        norm = norm + " " + " ".join(extra[:8])

    warnings = []
    if hi is not None and lo is not None and lo > hi:
        warnings.append("budget_min > budget_max; ignoring min")
        lo = None
    if slots == 0:
        warnings.append("no structured attributes recognised; relying on dense semantics")

    return Intent(
        original_query=q, language=lang, language_confidence=lconf, normalized_query_en=norm.strip(),
        category=categories, category_explicit=bool(categories), occasion=occasions, season=season, climate=climate,
        destination=destination, comfort=comfort, style=styles, material=materials, colour=colours, pattern=patterns,
        budget_min=lo, budget_max=hi, size=size, gender=gender, sustainability=sustain, brand=quoted,
        visual_intent=visual, has_query_image=has_query_image, parser="rules",
        confidence=round(min(1.0, 0.25 + 0.12 * slots), 2) if slots else 0.15, warnings=warnings,
    )
