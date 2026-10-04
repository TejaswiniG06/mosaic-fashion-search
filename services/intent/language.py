"""Script + lexicon based language identification tuned for Indian code-mixed queries.

Off-the-shelf language ID (fastText/CLD3) labels Tanglish/Hinglish as English, which breaks
downstream handling. We instead use: Unicode script ratios (Tamil U+0B80–0BFF, Devanagari
U+0900–097F) + romanised marker-word evidence.
"""
from __future__ import annotations

import re

from mosaic_common.fashion_kb import HINGLISH_MARKERS, TANGLISH_MARKERS

TAMIL = re.compile(r"[஀-௿]")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")
WORD = re.compile(r"[A-Za-z]+")
# romanised Tamil morphology: dative "-ku/-kku", locative "-la", "-ah" question/emphasis
TANGLISH_SUFFIX = re.compile(r"\b\w+(kku|ukku|ku|kulla|kitta|ukkaga)\b", re.I)


def detect_language(text: str) -> tuple[str, float, dict]:
    ta = len(TAMIL.findall(text))
    hi = len(DEVANAGARI.findall(text))
    la = len(LATIN.findall(text))
    total = max(1, ta + hi + la)
    words = [w.lower() for w in WORD.findall(text)]
    tg = sum(1 for w in words if w in TANGLISH_MARKERS)
    hg = sum(1 for w in words if w in HINGLISH_MARKERS)
    # suffix evidence only counts on non-English-looking tokens
    tg += 0.5 * sum(1 for m in TANGLISH_SUFFIX.finditer(text) if not m.group(0).lower().endswith("haiku"))
    evidence = {"tamil_chars": ta, "devanagari_chars": hi, "latin_chars": la, "tanglish_markers": tg, "hinglish_markers": hg}

    if ta / total > 0.3:
        return ("ta" if la / total < 0.3 else "tanglish"), round(min(1.0, 0.6 + ta / total), 2), evidence
    if hi / total > 0.3:
        return ("hi" if la / total < 0.3 else "hinglish"), round(min(1.0, 0.6 + hi / total), 2), evidence
    if tg >= 1 and tg >= hg:
        return "tanglish", round(min(0.95, 0.55 + 0.1 * tg), 2), evidence
    if hg >= 2 or (hg >= 1 and any(w in {"chahiye", "chaiye", "liye", "kapde"} for w in words)):
        return "hinglish", round(min(0.95, 0.55 + 0.1 * hg), 2), evidence
    if la:
        return "en", 0.9 if tg == 0 and hg == 0 else 0.7, evidence
    return "unknown", 0.0, evidence
