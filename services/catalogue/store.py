"""Catalogue storage backends with identical semantics:

* PgStore     — PostgreSQL (production): JSONB docs, transactional outbox, FOR UPDATE SKIP LOCKED relay
                (safe with N catalogue replicas).
* SqliteStore — SQLite (single-node / laptop "lite" mode, zero install): same tables and the same
                transactional-outbox guarantee (row + event in one transaction). Single catalogue replica only.

Selected with CATALOGUE_DB=postgres|sqlite.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from mosaic_common.schemas import CatalogueEvent


class ProductExists(Exception):
    pass


def _event(kind: str, asin: str, version: int, doc: dict | None) -> dict:
    return CatalogueEvent(event_id=uuid.uuid4().hex, type=kind, parent_asin=asin, version=version, ts=time.time(),
                          product=doc).model_dump(mode="json")


# =============================================================================== PostgreSQL
PG_DDL = """
CREATE TABLE IF NOT EXISTS products (
  parent_asin TEXT PRIMARY KEY, doc JSONB NOT NULL, title TEXT NOT NULL, price NUMERIC,
  stock_qty INT NOT NULL DEFAULT 0, category TEXT, version INT NOT NULL DEFAULT 1,
  deleted BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS products_category_idx ON products (category) WHERE NOT deleted;
CREATE INDEX IF NOT EXISTS products_updated_idx ON products (updated_at);
CREATE TABLE IF NOT EXISTS outbox (
  id BIGSERIAL PRIMARY KEY, event JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), published_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS outbox_unpublished_idx ON outbox (id) WHERE published_at IS NULL;
"""


class PgStore:
    name = "postgres"

    def __init__(self, dsn: str):
        from psycopg_pool import AsyncConnectionPool
        self.pool = AsyncConnectionPool(dsn, min_size=1, max_size=10, open=False)

    async def init(self) -> None:
        await self.pool.open(wait=True, timeout=30)
        async with self.pool.connection() as c:
            await c.execute(PG_DDL)

    async def close(self) -> None:
        await self.pool.close()

    async def ping(self) -> bool:
        async with self.pool.connection() as c:
            await c.execute("SELECT 1")
        return True

    async def _upsert(self, c, doc: dict) -> int:
        from psycopg.types.json import Jsonb
        row = await (await c.execute(
            """INSERT INTO products (parent_asin, doc, title, price, stock_qty, category) VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (parent_asin) DO UPDATE SET doc=EXCLUDED.doc, title=EXCLUDED.title, price=EXCLUDED.price,
                 stock_qty=EXCLUDED.stock_qty, category=EXCLUDED.category, deleted=FALSE,
                 version=products.version+1, updated_at=now() RETURNING version""",
            (doc["parent_asin"], Jsonb(doc), doc["title"], doc.get("price"), doc.get("stock_qty", 0), doc["attributes"].get("category")),
        )).fetchone()
        await c.execute("INSERT INTO outbox (event) VALUES (%s)", (Jsonb(_event("product.upserted", doc["parent_asin"], row[0], doc)),))
        return row[0]

    async def create(self, doc: dict) -> int:
        async with self.pool.connection() as c:
            async with c.transaction():
                ex = await (await c.execute("SELECT deleted FROM products WHERE parent_asin=%s", (doc["parent_asin"],))).fetchone()
                if ex and not ex[0]:
                    raise ProductExists(doc["parent_asin"])
                return await self._upsert(c, doc)

    async def upsert_many(self, docs: list[dict]) -> list[int]:
        async with self.pool.connection() as c:
            async with c.transaction():
                return [await self._upsert(c, d) for d in docs]

    async def patch(self, asin: str, fn: Callable[[dict], dict]) -> tuple[int, dict] | None:
        async with self.pool.connection() as c:
            async with c.transaction():
                row = await (await c.execute("SELECT doc FROM products WHERE parent_asin=%s AND NOT deleted FOR UPDATE", (asin,))).fetchone()
                if not row:
                    return None
                new = fn(row[0])
                return await self._upsert(c, new), new

    async def delete(self, asin: str) -> int | None:
        from psycopg.types.json import Jsonb
        async with self.pool.connection() as c:
            async with c.transaction():
                row = await (await c.execute(
                    "UPDATE products SET deleted=TRUE, version=version+1, updated_at=now() WHERE parent_asin=%s AND NOT deleted RETURNING version",
                    (asin,))).fetchone()
                if not row:
                    return None
                await c.execute("INSERT INTO outbox (event) VALUES (%s)", (Jsonb(_event("product.deleted", asin, row[0], None)),))
                return row[0]

    async def get(self, asin: str) -> tuple[dict, int] | None:
        async with self.pool.connection() as c:
            row = await (await c.execute("SELECT doc, version, deleted FROM products WHERE parent_asin=%s", (asin,))).fetchone()
        return None if not row or row[2] else (row[0], row[1])

    async def list(self, after: str, limit: int, category: str | None) -> list[dict]:
        sql, args = "SELECT doc, version FROM products WHERE NOT deleted AND parent_asin > %s", [after]
        if category:
            sql += " AND category = %s"
            args.append(category)
        sql += " ORDER BY parent_asin LIMIT %s"
        args.append(limit)
        async with self.pool.connection() as c:
            rows = await (await c.execute(sql, args)).fetchall()
        return [{**r[0], "_version": r[1]} for r in rows]

    async def stats(self) -> dict:
        async with self.pool.connection() as c:
            n = (await (await c.execute("SELECT count(*) FROM products WHERE NOT deleted")).fetchone())[0]
            pending = (await (await c.execute("SELECT count(*) FROM outbox WHERE published_at IS NULL")).fetchone())[0]
            cats = await (await c.execute("SELECT category, count(*) FROM products WHERE NOT deleted GROUP BY 1 ORDER BY 2 DESC")).fetchall()
        return {"products": n, "outbox_pending": pending, "by_category": {k or "unknown": v for k, v in cats}}

    async def relay(self, publish: Callable[[list[dict]], Any], batch: int = 500) -> int:
        async with self.pool.connection() as c:
            async with c.transaction():
                rows = await (await c.execute(
                    "SELECT id, event FROM outbox WHERE published_at IS NULL ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED", (batch,))).fetchall()
                if not rows:
                    return 0
                await publish([r[1] for r in rows])
                await c.execute("UPDATE outbox SET published_at = now() WHERE id = ANY(%s)", ([r[0] for r in rows],))
                return len(rows)


# =============================================================================== SQLite
SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS products (
  parent_asin TEXT PRIMARY KEY, doc TEXT NOT NULL, title TEXT NOT NULL, price REAL,
  stock_qty INTEGER NOT NULL DEFAULT 0, category TEXT, version INTEGER NOT NULL DEFAULT 1,
  deleted INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS products_category_idx ON products (category);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, created_at REAL NOT NULL, published_at REAL
);
CREATE INDEX IF NOT EXISTS outbox_unpublished_idx ON outbox (published_at, id);
"""


class SqliteStore:
    """All DB work runs on one worker thread via asyncio.to_thread under an asyncio lock (SQLite is single-writer)."""
    name = "sqlite"

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = asyncio.Lock()
        self.conn: sqlite3.Connection | None = None

    async def _run(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        async with self.lock:
            return await asyncio.to_thread(self._tx, fn)

    def _tx(self, fn):
        c = self.conn
        try:
            c.execute("BEGIN IMMEDIATE")
            out = fn(c)
            c.execute("COMMIT")
            return out
        except BaseException:
            c.execute("ROLLBACK")
            raise

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SQLITE_DDL)

    async def close(self) -> None:
        if self.conn:
            self.conn.close()

    async def ping(self) -> bool:
        return await self._run(lambda c: c.execute("SELECT 1").fetchone() is not None)

    @staticmethod
    def _upsert(c: sqlite3.Connection, doc: dict) -> int:
        now = time.time()
        row = c.execute("SELECT version FROM products WHERE parent_asin=?", (doc["parent_asin"],)).fetchone()
        version = (row[0] + 1) if row else 1
        c.execute(
            """INSERT INTO products (parent_asin, doc, title, price, stock_qty, category, version, deleted, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,0,?,?)
               ON CONFLICT(parent_asin) DO UPDATE SET doc=excluded.doc, title=excluded.title, price=excluded.price,
                 stock_qty=excluded.stock_qty, category=excluded.category, version=excluded.version, deleted=0, updated_at=excluded.updated_at""",
            (doc["parent_asin"], json.dumps(doc, ensure_ascii=False), doc["title"], doc.get("price"), doc.get("stock_qty", 0),
             doc["attributes"].get("category"), version, now, now))
        c.execute("INSERT INTO outbox (event, created_at) VALUES (?, ?)",
                  (json.dumps(_event("product.upserted", doc["parent_asin"], version, doc), ensure_ascii=False), now))
        return version

    async def create(self, doc: dict) -> int:
        def fn(c):
            ex = c.execute("SELECT deleted FROM products WHERE parent_asin=?", (doc["parent_asin"],)).fetchone()
            if ex and not ex[0]:
                raise ProductExists(doc["parent_asin"])
            return self._upsert(c, doc)
        return await self._run(fn)

    async def upsert_many(self, docs: list[dict]) -> list[int]:
        return await self._run(lambda c: [self._upsert(c, d) for d in docs])

    async def patch(self, asin: str, fn: Callable[[dict], dict]) -> tuple[int, dict] | None:
        def tx(c):
            row = c.execute("SELECT doc FROM products WHERE parent_asin=? AND deleted=0", (asin,)).fetchone()
            if not row:
                return None
            new = fn(json.loads(row[0]))
            return self._upsert(c, new), new
        return await self._run(tx)

    async def delete(self, asin: str) -> int | None:
        def fn(c):
            row = c.execute("SELECT version FROM products WHERE parent_asin=? AND deleted=0", (asin,)).fetchone()
            if not row:
                return None
            v = row[0] + 1
            c.execute("UPDATE products SET deleted=1, version=?, updated_at=? WHERE parent_asin=?", (v, time.time(), asin))
            c.execute("INSERT INTO outbox (event, created_at) VALUES (?, ?)", (json.dumps(_event("product.deleted", asin, v, None)), time.time()))
            return v
        return await self._run(fn)

    async def get(self, asin: str) -> tuple[dict, int] | None:
        row = await self._run(lambda c: c.execute("SELECT doc, version, deleted FROM products WHERE parent_asin=?", (asin,)).fetchone())
        return None if not row or row[2] else (json.loads(row[0]), row[1])

    async def list(self, after: str, limit: int, category: str | None) -> list[dict]:
        sql, args = "SELECT doc, version FROM products WHERE deleted=0 AND parent_asin > ?", [after]
        if category:
            sql += " AND category = ?"
            args.append(category)
        sql += " ORDER BY parent_asin LIMIT ?"
        args.append(limit)
        rows = await self._run(lambda c: c.execute(sql, args).fetchall())
        return [{**json.loads(d), "_version": v} for d, v in rows]

    async def stats(self) -> dict:
        def fn(c):
            n = c.execute("SELECT count(*) FROM products WHERE deleted=0").fetchone()[0]
            p = c.execute("SELECT count(*) FROM outbox WHERE published_at IS NULL").fetchone()[0]
            cats = c.execute("SELECT category, count(*) FROM products WHERE deleted=0 GROUP BY 1 ORDER BY 2 DESC").fetchall()
            return {"products": n, "outbox_pending": p, "by_category": {k or "unknown": v for k, v in cats}}
        return await self._run(fn)

    async def relay(self, publish: Callable[[list[dict]], Any], batch: int = 500) -> int:
        rows = await self._run(lambda c: c.execute(
            "SELECT id, event FROM outbox WHERE published_at IS NULL ORDER BY id LIMIT ?", (batch,)).fetchall())
        if not rows:
            return 0
        await publish([json.loads(e) for _, e in rows])   # at-least-once: mark only after publish succeeded
        ids = [r[0] for r in rows]
        await self._run(lambda c: c.execute(f"UPDATE outbox SET published_at=? WHERE id IN ({','.join('?' * len(ids))})", [time.time(), *ids]))
        return len(rows)
