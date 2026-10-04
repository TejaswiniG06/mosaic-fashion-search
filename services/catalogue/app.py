"""Catalogue service: system of record for products.

Evolving catalogue: every ADD / UPDATE / DELETE writes the row AND an outbox event in ONE
transaction (transactional outbox pattern => no lost or phantom events). A relay task publishes
outbox rows to the Redis Stream `catalogue.events`. Downstream consumers update the vector index and
BM25 incrementally; nothing is rebuilt.

Storage: PostgreSQL (default, production) or SQLite (CATALOGUE_DB=sqlite, zero-install laptop mode).
"""
from __future__ import annotations

import asyncio
import json
import time

import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException, Query

from mosaic_common.config import get_settings
from mosaic_common.events import catalogue_version
from mosaic_common.fashion_kb import enrich_product
from mosaic_common.schemas import Product, ProductPatch
from mosaic_common.service import create_service
from services.catalogue.store import PgStore, ProductExists, SqliteStore

settings = get_settings()
STATE: dict = {}


async def _ready():
    checks = {settings.catalogue_db: False, "redis": False}
    try:
        checks[settings.catalogue_db] = await STATE["store"].ping()
    except Exception:
        pass
    try:
        checks["redis"] = bool(await STATE["redis"].ping())
    except Exception:
        pass
    return checks


app = create_service("catalogue", ready_check=_ready)
log = app.state.logger


def require_admin(x_api_key: str | None = Header(default=None)):
    if x_api_key != settings.admin_api_key.get_secret_value():
        raise HTTPException(401, "invalid or missing X-API-Key")


@app.on_event("startup")
async def _startup():
    STATE["store"] = SqliteStore(settings.sqlite_path) if settings.catalogue_db == "sqlite" \
        else PgStore(settings.postgres_dsn.get_secret_value())
    await STATE["store"].init()
    STATE["redis"] = aioredis.from_url(settings.redis_url, protocol=2)
    STATE["relay"] = asyncio.create_task(_relay_loop())
    log.info("catalogue store ready", extra={"extra_fields": {"backend": STATE["store"].name}})


@app.on_event("shutdown")
async def _shutdown():
    STATE["relay"].cancel()
    await STATE["store"].close()


async def _publish(events: list[dict]) -> None:
    pipe = STATE["redis"].pipeline()
    for ev in events:
        pipe.xadd(settings.event_stream, {"data": json.dumps(ev, ensure_ascii=False)}, maxlen=1_000_000, approximate=True)
    pipe.incrby("mosaic:catalogue_version", len(events))
    await pipe.execute()


async def _relay_loop():
    """Outbox relay: publish committed events to the stream, then mark them published."""
    while True:
        try:
            n = await STATE["store"].relay(_publish)
            await asyncio.sleep(0.02 if n else 0.1)
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("outbox relay error")
            await asyncio.sleep(1.0)


def _prepare(p: Product) -> dict:
    doc = p.model_dump(mode="json")
    doc["attributes"] = enrich_product(doc)
    return doc


@app.post("/products", status_code=201, dependencies=[Depends(require_admin)])
async def create_product(p: Product):
    doc = _prepare(p)
    try:
        version = await STATE["store"].create(doc)
    except ProductExists:
        raise HTTPException(409, f"product {p.parent_asin} already exists; use PUT to update")
    return {"parent_asin": p.parent_asin, "version": version, "created_at": time.time(), "attributes": doc["attributes"]}


@app.put("/products/{asin}", dependencies=[Depends(require_admin)])
async def replace_product(asin: str, p: Product):
    if p.parent_asin != asin:
        raise HTTPException(400, "parent_asin in body must match path")
    doc = _prepare(p)
    version = (await STATE["store"].upsert_many([doc]))[0]
    return {"parent_asin": asin, "version": version, "attributes": doc["attributes"]}


@app.patch("/products/{asin}", dependencies=[Depends(require_admin)])
async def patch_product(asin: str, patch: ProductPatch):
    changes = patch.model_dump(mode="json", exclude_unset=True)

    def apply(doc: dict) -> dict:
        doc.update(changes)
        return _prepare(Product(**doc))

    res = await STATE["store"].patch(asin, apply)
    if res is None:
        raise HTTPException(404, "product not found")
    version, new_doc = res
    return {"parent_asin": asin, "version": version, "attributes": new_doc["attributes"]}


@app.delete("/products/{asin}", dependencies=[Depends(require_admin)])
async def delete_product(asin: str):
    version = await STATE["store"].delete(asin)
    if version is None:
        raise HTTPException(404, "product not found")
    return {"parent_asin": asin, "deleted": True, "version": version}


@app.post("/products/bulk", dependencies=[Depends(require_admin)])
async def bulk_upsert(products: list[Product]):
    if len(products) > 2000:
        raise HTTPException(413, "max 2000 products per bulk call")
    await STATE["store"].upsert_many([_prepare(p) for p in products])
    return {"upserted": len(products)}


@app.get("/products/{asin}")
async def get_product(asin: str):
    row = await STATE["store"].get(asin)
    if not row:
        raise HTTPException(404, "product not found")
    return {**row[0], "_version": row[1]}


@app.get("/products")
async def list_products(after: str = "", limit: int = Query(default=500, ge=1, le=5000), category: str | None = None):
    """Keyset-paginated export (used by retrieval replicas to warm their BM25 index)."""
    items = await STATE["store"].list(after, limit, category)
    return {"items": items, "next_after": items[-1]["parent_asin"] if len(items) == limit else None}


@app.get("/stats")
async def stats():
    s = await STATE["store"].stats()
    return {**s, "backend": STATE["store"].name, "catalogue_version": await catalogue_version(STATE["redis"])}
