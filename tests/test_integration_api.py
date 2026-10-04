"""Integration tests against the running stack (make up / scripts/run_local.sh). Skipped if gateway is down."""
import time
import uuid

import httpx
import pytest

API = "http://localhost:8000"
KEY = {"x-api-key": "change-me-admin-key"}


def _up():
    try:
        return httpx.get(f"{API}/ready", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="stack not running")]


def search(q, **kw):
    r = httpx.post(f"{API}/search", json={"query": q, "use_cache": False, **kw}, timeout=30)
    r.raise_for_status()
    return r.json()


def test_health_endpoints():
    for port in (8000, 8001, 8002, 8003, 8004, 8005, 8006):
        assert httpx.get(f"http://localhost:{port}/health", timeout=3).json()["status"] == "ok"
        assert httpx.get(f"http://localhost:{port}/ready", timeout=5).status_code == 200
    assert "mosaic_http_requests_total" in httpx.get(f"{API}/metrics").text


def test_mosaic_pipeline_and_hard_constraints():
    r = search("Chennai summer ku comfortable cotton dress venum under 2000", top_k=10)
    assert r["intent"]["language"] == "tanglish"
    assert r["results"], "expected results"
    for x in r["results"]:
        assert x["price"] <= 2000 and x["in_stock"] and x["attributes"]["category"] == "dress"
        assert x["explanation"] and x["contributions"]
    assert r["weights"]["climate"] > 0 and r["weight_rationale"]


def test_results_only_from_catalogue():
    r = search("red silk saree for wedding", top_k=5)
    for x in r["results"]:
        assert httpx.get(f"{API}/catalogue/products/{x['parent_asin']}").status_code == 200


def test_compare_modes():
    r = httpx.post(f"{API}/compare", json={"query": "linen shirt for goa", "top_k": 3}, timeout=60).json()
    assert set(r) == {"bm25", "dense", "hybrid", "mosaic"}


def test_crud_and_time_to_searchable():
    asin = "IT" + uuid.uuid4().hex[:8].upper()
    p = {"parent_asin": asin, "title": "Quokkaline Men's Saffron Khadi Kurta for Pongal", "price": 1299, "stock_qty": 4, "sizes": ["M", "L"],
         "details": {"Material": "Khadi", "Department": "Mens"}}
    assert httpx.post(f"{API}/catalogue/products", json=p, headers=KEY).status_code == 201
    t0 = time.time()
    found = False
    while time.time() - t0 < 15 and not found:
        found = any(x["parent_asin"] == asin for x in search("Quokkaline khadi kurta", mode="hybrid", top_k=20)["results"])
        time.sleep(0.1)
    assert found, "new product not searchable within 15s"
    # UPDATE: out of stock => must disappear from results (hard constraint)
    assert httpx.patch(f"{API}/catalogue/products/{asin}", json={"stock_qty": 0}, headers=KEY).status_code == 200
    time.sleep(1.0)
    assert not any(x["parent_asin"] == asin for x in search("Quokkaline khadi kurta", mode="hybrid", top_k=20)["results"])
    assert httpx.delete(f"{API}/catalogue/products/{asin}", headers=KEY).status_code == 200
    assert httpx.get(f"{API}/catalogue/products/{asin}").status_code == 404


def test_admin_auth_required():
    assert httpx.post(f"{API}/catalogue/products", json={"parent_asin": "NOAUTH1", "title": "valid title"}).status_code == 401


def test_validation_errors():
    assert httpx.post(f"{API}/search", json={"query": "x" * 600}).status_code == 422
    assert httpx.post(f"{API}/search", json={"query": ""}).status_code == 422
