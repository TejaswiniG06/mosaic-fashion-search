"""Indexer worker: consumes catalogue events and incrementally maintains the Qdrant index.

For each batch (<=64 events): collapse to the latest event per product, embed product text with e5
("passage:"), embed product images with CLIP (missing/unreachable image => text-only point, flagged
`has_image=false`), upsert/delete points, record `indexed_at` per product (time-to-searchable), ack.
Exposes a tiny HTTP server for /health, /ready and /metrics. Horizontally scalable: run N workers
in the same consumer group.
"""
from __future__ import annotations

import asyncio
import socket
import time

import redis.asyncio as aioredis
import uvicorn
from prometheus_client import Counter, Gauge, Histogram

from mosaic_common.config import get_settings
from mosaic_common.events import EventBus
from mosaic_common.fashion_kb import product_text
from mosaic_common.http import ServiceClient
from mosaic_common.service import create_service
from mosaic_common.vector_store import VectorStore

settings = get_settings()
GROUP = "indexer"
CONSUMER = f"indexer-{socket.gethostname()}"
INDEXED = Counter("mosaic_indexer_events_total", "Indexed catalogue events", ["type"])
BATCH_SEC = Histogram("mosaic_indexer_batch_seconds", "Indexer batch latency", buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30))
LAG = Gauge("mosaic_indexer_stream_lag", "Events not yet delivered to the indexer group")
STATE: dict = {"processed": 0, "last_batch_s": None, "running": False}


async def _ready():
    return {"loop_running": STATE["running"]}


app = create_service("indexer", ready_check=_ready)
log = app.state.logger


def _payload(p: dict) -> dict:
    keep = ("parent_asin", "title", "store", "price", "currency", "stock_qty", "sizes", "images", "features", "description",
            "details", "categories", "average_rating", "rating_number", "attributes", "main_category", "url")
    return {k: p.get(k) for k in keep}


async def process_batch(events, vs: VectorStore, emb: ServiceClient, r: aioredis.Redis) -> dict:
    latest = {}
    for _id, ev in events:
        cur = latest.get(ev.parent_asin)
        if cur is None or ev.version >= cur.version:
            latest[ev.parent_asin] = ev
    ups = [e for e in latest.values() if e.type == "product.upserted" and e.product]
    dels = [e.parent_asin for e in latest.values() if e.type == "product.deleted"]
    stats = {"upserts": len(ups), "deletes": len(dels), "images_missing": 0}
    if ups:
        texts = [product_text(e.product) for e in ups]
        tv = (await emb.post("/embed/text", {"texts": texts, "kind": "passage"}))["vectors"]
        refs = [((e.product.get("images") or [{}])[0] or {}).get("large") for e in ups]
        try:
            ir = await emb.post("/embed/image", {"refs": refs})
            iv = ir["vectors"]
        except Exception:
            log.warning("image embedding failed for batch; indexing text-only (image fallback)")
            iv = [None] * len(ups)
        stats["images_missing"] = sum(1 for v in iv if v is None)
        await vs.upsert([(e.parent_asin, _payload(e.product), t, i) for e, t, i in zip(ups, tv, iv)])
        INDEXED.labels("upsert").inc(len(ups))
    if dels:
        await vs.delete(dels)
        INDEXED.labels("delete").inc(len(dels))
    now = time.time()
    pipe = r.pipeline()
    for e in latest.values():
        pipe.hset("mosaic:indexed_at", e.parent_asin, f"{now}|{e.version}|{e.ts}")
    await pipe.execute()
    return stats


async def run_loop():
    vs = VectorStore(settings.qdrant_url, settings.qdrant_collection,
                     settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None)
    r = aioredis.from_url(settings.redis_url, protocol=2)
    bus = EventBus(r, settings.event_stream)
    emb = ServiceClient("embedding", settings.embedding_url, timeout_s=120, retries=3)
    for _ in range(60):
        try:
            await vs.ensure_collection()
            break
        except Exception:
            await asyncio.sleep(1)
    await bus.ensure_group(GROUP, start="0")
    STATE["running"] = True
    log.info("indexer started", extra={"extra_fields": {"group": GROUP, "consumer": CONSUMER}})
    while True:
        try:
            events = await bus.read(GROUP, CONSUMER, count=64, block_ms=1000)
            if not events:
                LAG.set((await bus.lag(GROUP)).get("lag") or 0)
                continue
            t0 = time.perf_counter()
            stats = await process_batch(events, vs, emb, r)
            await bus.ack(GROUP, [i for i, _ in events])
            dt = time.perf_counter() - t0
            BATCH_SEC.observe(dt)
            STATE["processed"] += len(events)
            STATE["last_batch_s"] = round(dt, 3)
            log.info("batch indexed", extra={"extra_fields": {**stats, "events": len(events), "seconds": round(dt, 3)}})
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("indexer batch failed; will retry (events stay pending)")
            await asyncio.sleep(2.0)


@app.on_event("startup")
async def _startup():
    STATE["task"] = asyncio.create_task(run_loop())


@app.get("/stats")
async def stats():
    r = aioredis.from_url(settings.redis_url, protocol=2)
    lag = await EventBus(r, settings.event_stream).lag(GROUP)
    return {**{k: v for k, v in STATE.items() if k != "task"}, "stream": lag}


if __name__ == "__main__":
    uvicorn.run("services.indexer.worker:app", host="0.0.0.0", port=8006, log_level="warning")
