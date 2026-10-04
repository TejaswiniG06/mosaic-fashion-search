"""Catalogue event bus on Redis Streams (consumer groups => at-least-once, replayable, ordered
per stream). Producers: catalogue service outbox relay. Consumers: indexer worker (Qdrant) and
every retrieval replica (its own group, for in-memory BM25 deltas)."""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from .schemas import CatalogueEvent

CATALOGUE_VERSION_KEY = "mosaic:catalogue_version"


class EventBus:
    def __init__(self, redis: aioredis.Redis, stream: str):
        self.r = redis
        self.stream = stream

    async def publish(self, event: CatalogueEvent) -> str:
        msg_id = await self.r.xadd(self.stream, {"data": event.model_dump_json()}, maxlen=1_000_000, approximate=True)
        await self.r.incr(CATALOGUE_VERSION_KEY)
        return msg_id

    async def ensure_group(self, group: str, start: str = "0") -> None:
        try:
            await self.r.xgroup_create(self.stream, group, id=start, mkstream=True)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def read(self, group: str, consumer: str, count: int = 64, block_ms: int = 1000) -> list[tuple[str, CatalogueEvent]]:
        # first re-deliver anything pending for this consumer (crash recovery), then new messages
        out: list[tuple[str, CatalogueEvent]] = []
        for start in ("0", ">"):
            resp = await self.r.xreadgroup(group, consumer, {self.stream: start}, count=count,
                                           block=None if start == "0" else block_ms)
            for _stream, messages in resp or []:
                for msg_id, fields in messages:
                    if not fields:
                        continue
                    raw = fields.get(b"data") or fields.get("data")
                    out.append((msg_id if isinstance(msg_id, str) else msg_id.decode(), CatalogueEvent(**json.loads(raw))))
            if out:
                break
        return out

    async def ack(self, group: str, ids: list[str]) -> None:
        if ids:
            await self.r.xack(self.stream, group, *ids)

    async def lag(self, group: str) -> dict[str, Any]:
        try:
            groups = await self.r.xinfo_groups(self.stream)
        except aioredis.ResponseError:
            return {"pending": 0, "lag": 0}
        for g in groups:
            gname = g.get("name") or g.get(b"name")
            gname = gname.decode() if isinstance(gname, bytes) else gname
            if gname == group:
                lag = g.get("lag")
                if lag is None:  # Redis < 7 (e.g. Redis 5 for Windows) has no 'lag' field: count undelivered entries
                    last = g.get("last-delivered-id") or g.get(b"last-delivered-id") or "0-0"
                    last = last.decode() if isinstance(last, bytes) else last
                    ms, seq = last.split("-")  # exclusive "(" ranges need Redis 6.2, so start at last-id + 1
                    lag = len(await self.r.xrange(self.stream, min=f"{ms}-{int(seq) + 1}", max="+", count=5000))
                return {"pending": g.get("pending", 0), "lag": lag}
        return {"pending": 0, "lag": None}


async def catalogue_version(r: aioredis.Redis) -> int:
    v = await r.get(CATALOGUE_VERSION_KEY)
    return int(v) if v else 0
