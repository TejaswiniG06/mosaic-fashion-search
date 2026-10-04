"""Incrementally-updatable BM25 (Okapi) inverted index.

`rank_bm25` and most libraries require a full rebuild on every change. For an evolving catalogue
we keep postings + document lengths so add/update/delete are O(|doc terms|) and IDF/avgdl are
computed from live counters at query time. Title tokens are counted twice (field boost).
"""
from __future__ import annotations

import heapq
import math
from collections import Counter
from typing import Any, Callable

from mosaic_common.fashion_kb import STOPWORDS_EN, product_text, tokenize


def doc_tokens(p: dict[str, Any]) -> list[str]:
    title = tokenize(p.get("title") or "")
    body = tokenize(product_text(p))
    attrs = p.get("attributes") or {}
    extra = []
    if attrs.get("category"):
        extra += tokenize(attrs["category"].replace("-", " "))
    return [t for t in title + body + extra if t not in STOPWORDS_EN]


def query_tokens(q: str) -> list[str]:
    return [t for t in tokenize(q) if t not in STOPWORDS_EN]


class BM25Index:
    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.postings: dict[str, dict[str, int]] = {}
        self.doc_len: dict[str, int] = {}
        self.docs: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, int] = {}
        self.total_len = 0

    def __len__(self) -> int:
        return len(self.doc_len)

    def upsert(self, asin: str, product: dict[str, Any], version: int = 0) -> bool:
        if version and self.versions.get(asin, -1) > version:
            return False  # stale event (idempotent, out-of-order safe)
        self.delete(asin, version=None)
        toks = Counter(doc_tokens(product))
        for t, tf in toks.items():
            self.postings.setdefault(t, {})[asin] = tf
        n = sum(toks.values())
        self.doc_len[asin] = n
        self.total_len += n
        self.docs[asin] = product
        self.versions[asin] = version
        return True

    def delete(self, asin: str, version: int | None = 0) -> bool:
        if version and self.versions.get(asin, -1) > version:
            return False
        if asin not in self.doc_len:
            if version is not None:
                self.versions[asin] = version or 0
            return False
        toks = Counter(doc_tokens(self.docs[asin]))
        for t in toks:
            plist = self.postings.get(t)
            if plist is not None:
                plist.pop(asin, None)
                if not plist:
                    del self.postings[t]
        self.total_len -= self.doc_len.pop(asin)
        self.docs.pop(asin, None)
        if version is not None:
            self.versions[asin] = version or 0
        return True

    def _idf(self, df: int) -> float:
        n = len(self.doc_len)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score_doc(self, q_tokens: list[str], asin: str) -> float:
        if asin not in self.doc_len:
            return 0.0
        avgdl = self.total_len / max(1, len(self.doc_len))
        dl = self.doc_len[asin]
        s = 0.0
        for t in set(q_tokens):
            plist = self.postings.get(t)
            if not plist or asin not in plist:
                continue
            tf = plist[asin]
            s += self._idf(len(plist)) * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * dl / avgdl))
        return s

    def search(self, q_tokens: list[str], k: int, accept: Callable[[dict[str, Any]], bool] | None = None) -> list[tuple[str, float]]:
        if not self.doc_len or not q_tokens:
            return []
        avgdl = self.total_len / len(self.doc_len)
        scores: dict[str, float] = {}
        for t in set(q_tokens):
            plist = self.postings.get(t)
            if not plist:
                continue
            idf = self._idf(len(plist))
            k1, b = self.k1, self.b
            for asin, tf in plist.items():
                dl = self.doc_len[asin]
                scores[asin] = scores.get(asin, 0.0) + idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))
        if accept is None:
            return heapq.nlargest(k, scores.items(), key=lambda kv: kv[1])
        out: list[tuple[str, float]] = []
        for asin, s in sorted(scores.items(), key=lambda kv: -kv[1]):
            if accept(self.docs[asin]):
                out.append((asin, s))
                if len(out) >= k:
                    break
        return out
