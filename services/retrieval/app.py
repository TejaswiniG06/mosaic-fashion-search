"""Retrieval service: BM25 (sparse) + Qdrant ANN (dense text / image) + Reciprocal Rank Fusion.

* Hard constraints are pushed down into both channels (Qdrant payload filter, BM25 accept-fn),
  so constrained-out products never consume candidate slots.
* Every candidate gets *all* raw signals (BM25 score computed for dense-only hits, cosine computed
  from stored vectors for BM25-only hits, CLIP visual similarity from stored image vectors) so the
  ranker can fuse them without bias toward the channel that found the item.
* Degraded modes: Qdrant/embedding unavailable => BM25-only (flagged in `degraded`).
* The in-memory BM25 index is warmed from the catalogue service and kept fresh by consuming the
  catalogue event stream (per-replica consumer group).
"""
from __future__ import annotations

import asyncio
import os
import socket
import time

import httpx
import numpy as np
import redis.asyncio as aioredis

from mosaic_common.config import get_settings
from mosaic_common.events import EventBus
from mosaic_common.filters import accepts
from mosaic_common.schemas import Candidate, HardFilters, RetrieveRequest, RetrieveResponse
from mosaic_common.service import FALLBACKS, Timer, create_service
from mosaic_common.vector_store import VectorStore
from services.retrieval.bm25 import BM25Index, query_tokens

settings = get_settings()
STATE: dict = {"bm25": BM25Index(), "warm": False}
GROUP = f"retrieval-bm25-{socket.gethostname()}-{os.getpid()}"


async def _ready():
    q_ok = False
    try:
        await STATE["vs"].count()
        q_ok = True
    except Exception:
        pass
    # BM25 warm is required; Qdrant is not (we can serve degraded), but report it
    return {"bm25_warm": STATE["warm"], "qdrant": q_ok}


app = create_service("retrieval", ready_check=_ready)
log = app.state.logger


@app.on_event("startup")
async def _startup():
    STATE["vs"] = VectorStore(settings.qdrant_url, settings.qdrant_collection,
                              settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None)
    try:
        await STATE["vs"].ensure_collection()
    except Exception:
        log.warning("qdrant unavailable at startup; serving BM25-only until it recovers")
    STATE["redis"] = aioredis.from_url(settings.redis_url, protocol=2)
    STATE["bus"] = EventBus(STATE["redis"], settings.event_stream)
    # create the consumer group at the stream tip BEFORE warming => no gap between snapshot & stream
    await STATE["bus"].ensure_group(GROUP, start="$")
    STATE["warm_task"] = asyncio.create_task(_warm_then_consume())


@app.on_event("shutdown")
async def _shutdown():
    STATE["warm_task"].cancel()
    try:
        await STATE["redis"].xgroup_destroy(settings.event_stream, GROUP)
    except Exception:
        pass


async def _warm_then_consume():
    bm: BM25Index = STATE["bm25"]
    t0 = time.perf_counter()
    async with httpx.AsyncClient(base_url=settings.catalogue_url, timeout=30) as c:
        after = ""
        while True:
            for attempt in range(30):
                try:
                    r = await c.get("/products", params={"after": after, "limit": 2000})
                    r.raise_for_status()
                    break
                except Exception:
                    await asyncio.sleep(1.0)
            else:
                log.error("catalogue unreachable; BM25 warm incomplete")
                break
            data = r.json()
            for p in data["items"]:
                bm.upsert(p["parent_asin"], p, int(p.pop("_version", 0)))
            if not data["next_after"]:
                break
            after = data["next_after"]
    STATE["warm"] = True
    log.info("bm25 warmed", extra={"extra_fields": {"docs": len(bm), "seconds": round(time.perf_counter() - t0, 2)}})
    bus: EventBus = STATE["bus"]
    while True:
        try:
            events = await bus.read(GROUP, "c1", count=256, block_ms=1000)
            for _id, ev in events:
                if ev.type == "product.upserted" and ev.product:
                    bm.upsert(ev.parent_asin, ev.product, ev.version)
                elif ev.type == "product.deleted":
                    bm.delete(ev.parent_asin, ev.version)
            await bus.ack(GROUP, [i for i, _ in events])
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("bm25 event consumer error")
            await asyncio.sleep(1.0)


def _rrf(ranks: list[int | None], k: int) -> float:
    return sum(1.0 / (k + r) for r in ranks if r is not None)


@app.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(req: RetrieveRequest) -> RetrieveResponse:
    t: dict[str, float] = {}
    degraded: list[str] = []
    bm: BM25Index = STATE["bm25"]
    vs: VectorStore = STATE["vs"]
    f: HardFilters = req.filters
    pool = req.pool
    mode = req.mode
    if mode in ("dense", "hybrid") and req.text_vector is None and req.image_query_vector is None:
        degraded.append("no_query_vector:bm25_only")
        FALLBACKS.labels("retrieval", "no_query_vector").inc()
        mode = "bm25"

    qt = query_tokens(req.query_text)
    bm_hits: list[tuple[str, float]] = []
    dense_hits: list[tuple[str, float, dict]] = []
    img_hits: list[tuple[str, float, dict]] = []

    want_vecs: list[str] = []
    if req.complete_signals:
        if req.text_vector is not None:
            want_vecs.append("text")
        if req.clip_text_vector is not None or req.image_query_vector is not None:
            want_vecs.append("image")
    inline_vecs: dict[str, dict] = {}

    async def run_dense():
        nonlocal dense_hits, img_hits
        tasks = []
        if req.text_vector is not None:
            tasks.append(vs.search(req.text_vector, "text", f, pool, with_vectors=want_vecs or None))
        if req.image_query_vector is not None:
            tasks.append(vs.search(req.image_query_vector, "image", f, pool, with_vectors=want_vecs or None))
        res = await asyncio.gather(*tasks)
        i = 0
        if req.text_vector is not None:
            dense_hits = res[i]
            i += 1
        if req.image_query_vector is not None:
            img_hits = res[i]
        for hits in (dense_hits, img_hits):
            for asin, _s, _p, vec in hits:
                if vec:
                    inline_vecs[asin] = vec

    if mode in ("bm25", "hybrid"):
        with Timer(t, "bm25", "retrieval"):
            bm_hits = bm.search(qt, pool, accept=lambda p: accepts(p, f))
    if mode in ("dense", "hybrid"):
        try:
            with Timer(t, "dense_ann", "retrieval"):
                await asyncio.wait_for(run_dense(), timeout=3.0)
        except Exception as e:
            degraded.append(f"vector_search_unavailable:{type(e).__name__}")
            FALLBACKS.labels("retrieval", "vector_search_failed").inc()
            if mode == "dense" or not bm_hits:
                with Timer(t, "bm25", "retrieval"):
                    bm_hits = bm.search(qt, pool, accept=lambda p: accepts(p, f))
            mode = "bm25"

    # ---- fuse
    with Timer(t, "fusion", "retrieval"):
        cands: dict[str, Candidate] = {}
        for r, (asin, s) in enumerate(bm_hits, 1):
            cands[asin] = Candidate(parent_asin=asin, bm25=s, bm25_rank=r, product=bm.docs.get(asin, {}))
        for r, (asin, s, payload, _v) in enumerate(dense_hits, 1):
            c = cands.get(asin) or Candidate(parent_asin=asin, product=bm.docs.get(asin) or payload)
            c.dense, c.dense_rank = s, r
            cands[asin] = c
        img_rank: dict[str, int] = {}
        for r, (asin, s, payload, _v) in enumerate(img_hits, 1):
            c = cands.get(asin) or Candidate(parent_asin=asin, product=bm.docs.get(asin) or payload)
            c.image_dense = s
            img_rank[asin] = r
            cands[asin] = c
        for asin, c in cands.items():
            c.rrf = _rrf([c.bm25_rank, c.dense_rank, img_rank.get(asin)], settings.rrf_k)

    # ---- complete missing signals so every candidate carries the full feature vector
    if req.complete_signals:
        with Timer(t, "signal_completion", "retrieval"):
            for asin, c in cands.items():
                if c.bm25_rank is None and qt:
                    c.bm25 = bm.score_doc(qt, asin)
            vector_ok = not any(d.startswith("vector_search_unavailable") for d in degraded)
            missing = [a for a in cands if a not in inline_vecs]
            if want_vecs and vector_ok:
                try:
                    if missing:  # only BM25-only hits need a round trip; dense hits came with their vectors
                        inline_vecs.update(await asyncio.wait_for(vs.vectors(missing, want_vecs), timeout=2.0))
                    tv = np.asarray(req.text_vector, dtype=np.float32) if req.text_vector is not None else None
                    cv = np.asarray(req.clip_text_vector, dtype=np.float32) if req.clip_text_vector is not None else None
                    iv = np.asarray(req.image_query_vector, dtype=np.float32) if req.image_query_vector is not None else None
                    for asin, c in cands.items():
                        v = inline_vecs.get(asin, {})
                        if tv is not None and c.dense_rank is None and "text" in v:
                            c.dense = float(np.dot(tv, np.asarray(v["text"], dtype=np.float32)))
                        if "image" in v:
                            img = np.asarray(v["image"], dtype=np.float32)
                            text_sim = float(np.dot(cv, img)) if cv is not None else None
                            img_sim = float(np.dot(iv, img)) if iv is not None else None
                            if img_sim is not None:
                                c.image_dense = img_sim
                            sims = [x for x in (text_sim, img_sim) if x is not None]
                            c.visual = sum(sims) / len(sims) if sims else None
                except Exception as e:
                    degraded.append(f"vector_fetch_failed:{type(e).__name__}")

    key = {"bm25": lambda c: c.bm25, "dense": lambda c: max(c.dense, c.image_dense), "hybrid": lambda c: c.rrf}[mode]
    ordered = sorted(cands.values(), key=key, reverse=True)
    return RetrieveResponse(candidates=ordered, mode_used=mode, degraded=degraded, timings_ms=t, index_size=len(bm))


@app.get("/stats")
async def stats():
    bm: BM25Index = STATE["bm25"]
    try:
        q = await STATE["vs"].count()
    except Exception:
        q = None
    lag = await STATE["bus"].lag(GROUP)
    return {"bm25_docs": len(bm), "bm25_terms": len(bm.postings), "qdrant_points": q, "warm": STATE["warm"], "stream_lag": lag}
