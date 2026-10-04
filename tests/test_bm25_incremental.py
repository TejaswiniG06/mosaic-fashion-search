from services.retrieval.bm25 import BM25Index, query_tokens


def P(asin, title, **kw):
    return {"parent_asin": asin, "title": title, **kw}


def test_incremental_equals_rebuild():
    docs = [P("A1", "red cotton summer dress"), P("A2", "blue denim jeans"), P("A3", "cotton kurta for festive wear"),
            P("A4", "wool jacket for winter")]
    inc = BM25Index()
    for d in docs:
        inc.upsert(d["parent_asin"], d, 1)
    inc.upsert("A2", P("A2", "blue cotton shirt"), 2)      # update
    inc.delete("A4", 2)                                      # delete
    rebuilt = BM25Index()
    for d in [docs[0], P("A2", "blue cotton shirt"), docs[2]]:
        rebuilt.upsert(d["parent_asin"], d, 1)
    q = query_tokens("cotton shirt")
    a = inc.search(q, 10)
    b = rebuilt.search(q, 10)
    assert [x[0] for x in a] == [x[0] for x in b]
    assert all(abs(x[1] - y[1]) < 1e-9 for x, y in zip(a, b))
    assert len(inc) == 3 and "A4" not in inc.docs


def test_stale_events_ignored():
    idx = BM25Index()
    idx.upsert("A1", P("A1", "new title linen"), 5)
    assert idx.upsert("A1", P("A1", "old title wool"), 3) is False
    assert idx.search(query_tokens("linen"), 5)[0][0] == "A1"
    assert idx.search(query_tokens("wool"), 5) == []
    assert idx.delete("A1", 4) is False and len(idx) == 1


def test_accept_filter_applied_before_topk():
    idx = BM25Index()
    for i in range(20):
        idx.upsert(f"A{i}", P(f"A{i}", "cotton dress", price=100 * i), 1)
    hits = idx.search(query_tokens("cotton dress"), 5, accept=lambda p: p["price"] <= 300)
    assert len(hits) == 4 and all(idx.docs[a]["price"] <= 300 for a, _ in hits)
