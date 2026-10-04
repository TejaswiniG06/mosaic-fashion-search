import asyncio

import pytest

from services.catalogue.store import ProductExists, SqliteStore


def doc(asin, price=100.0, cat="dress"):
    return {"parent_asin": asin, "title": f"title {asin}", "price": price, "stock_qty": 1, "attributes": {"category": cat}}


def test_sqlite_store_crud_and_outbox(tmp_path):
    async def run():
        s = SqliteStore(tmp_path / "c.db")
        await s.init()
        assert await s.create(doc("A1")) == 1
        with pytest.raises(ProductExists):
            await s.create(doc("A1"))
        v, new = await s.patch("A1", lambda d: {**d, "price": 50.0})
        assert v == 2 and new["price"] == 50.0
        assert (await s.get("A1"))[0]["price"] == 50.0
        await s.upsert_many([doc("A2", cat="saree"), doc("A3")])
        assert [d["parent_asin"] for d in await s.list("", 10, "dress")] == ["A1", "A3"]
        assert await s.delete("A1") == 3 and await s.get("A1") is None and await s.delete("A1") is None
        published = []

        async def pub(evs):
            published.extend(evs)
        assert await s.relay(pub) == 5            # create, patch, 2 upserts, delete — all in commit order
        assert [e["type"] for e in published][-1] == "product.deleted"
        assert await s.relay(pub) == 0            # marked published, not re-sent
        st = await s.stats()
        assert st["products"] == 2 and st["outbox_pending"] == 0
        await s.close()
    asyncio.run(run())
