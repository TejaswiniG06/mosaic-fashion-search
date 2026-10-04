"""Query API gateway: the only public entry point. Orchestrates

  query → intent → embeddings (e5 + CLIP) → retrieval (BM25 / dense / hybrid) → context-adaptive
  rerank + hard constraints → grounded explanations

with per-hop timeouts, circuit breakers and degraded-mode fallbacks, a Redis response cache that is
invalidated by catalogue version, request-id tracing and per-component timings in every response.
Also proxies catalogue CRUD (admin key) and measures time-to-searchable.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid

import redis.asyncio as aioredis
from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, Field

from mosaic_common.config import get_settings
from mosaic_common.events import catalogue_version
from mosaic_common.http import ServiceClient
from mosaic_common.logging import request_id_var
from mosaic_common.schemas import (Candidate, Feedback, HardFilters, Intent, Product, ProductPatch, RankOptions, ScoredProduct,
                                   SearchRequest, SearchResponse, Suggestion)
from mosaic_common.service import FALLBACKS, Timer, create_service
from services.intent.language import detect_language
from mosaic_common.prompts import clip_prompt_for

settings = get_settings()
C: dict[str, ServiceClient] = {}
STATE: dict = {}


async def _ready():
    names = ["intent", "embedding", "retrieval", "ranking", "catalogue"]
    res = await asyncio.gather(*(C[n].ready() for n in names))
    checks = dict(zip(names, res))
    try:
        checks["redis"] = bool(await STATE["redis"].ping())
    except Exception:
        checks["redis"] = False
    # gateway can serve degraded without intent/embedding/ranking, but not without retrieval
    return checks


app = create_service("gateway", ready_check=_ready)
log = app.state.logger


@app.on_event("startup")
async def _startup():
    C["intent"] = ServiceClient("intent", settings.intent_url, timeout_s=settings.llm_timeout_s + 2)
    C["embedding"] = ServiceClient("embedding", settings.embedding_url, timeout_s=10)
    C["retrieval"] = ServiceClient("retrieval", settings.retrieval_url, timeout_s=8)
    C["ranking"] = ServiceClient("ranking", settings.ranking_url, timeout_s=settings.llm_timeout_s + 4)
    C["catalogue"] = ServiceClient("catalogue", settings.catalogue_url, timeout_s=30, retries=0)
    STATE["redis"] = aioredis.from_url(settings.redis_url, protocol=2)
    STATE["buckets"] = {}


# ------------------------------------------------------------------ helpers
def _rate_limit(request: Request) -> None:
    refill_per_s, capacity = settings.rate_limit_rps, settings.rate_limit_burst
    if refill_per_s <= 0:
        return
    ip = request.client.host if request.client else "?"
    now = time.monotonic()
    tokens, last = STATE["buckets"].get(ip, (capacity, now))
    tokens = min(capacity, tokens + (now - last) * refill_per_s)
    if tokens < 1:
        raise HTTPException(429, "rate limit exceeded")
    STATE["buckets"][ip] = (tokens - 1, now)


def passthrough_intent(q: str, has_image: bool) -> Intent:
    lang, conf, _ = detect_language(q) if q else ("unknown", 0.0, {})
    return Intent(original_query=q, language=lang, language_confidence=conf, normalized_query_en=q, parser="passthrough",
                  has_query_image=has_image, visual_intent=has_image, confidence=0.0)


def filters_from_intent(intent: Intent | None, structured: bool, relax: list[str] | None = None,
                        budget_max_override: float | None = None) -> HardFilters:
    if not (intent and structured):
        return HardFilters(in_stock_only=True)
    relax = relax or []
    f = HardFilters(price_min=intent.budget_min, price_max=intent.budget_max, in_stock_only=True, size=intent.size,
                    categories=intent.category if intent.category_explicit else [], gender=intent.gender if intent.gender in ("men", "women") else None)
    if budget_max_override is not None:
        f.price_max = budget_max_override
    if "price" in relax:
        f.price_min = f.price_max = None
    if "size" in relax:
        f.size = None
    if "category" in relax:
        f.categories = []
    if "gender" in relax:
        f.gender = None
    return f


async def relaxation_suggestions(filters: HardFilters, retrieve_body: dict) -> list[Suggestion]:
    """'No results' helper: try dropping one constraint at a time and report which would return products."""
    trials = []
    if filters.price_max is not None or filters.price_min is not None:
        trials.append(("price", filters.model_copy(update={"price_max": None, "price_min": None})))
    if filters.size:
        trials.append(("size", filters.model_copy(update={"size": None})))
    if filters.categories:
        trials.append(("category", filters.model_copy(update={"categories": []})))
    if filters.gender:
        trials.append(("gender", filters.model_copy(update={"gender": None})))

    async def one(kind: str, f: HardFilters):
        try:
            rr = await C["retrieval"].post("/retrieve", {**retrieve_body, "filters": f.model_dump(), "pool": 50, "complete_signals": False})
        except Exception:
            return None
        cands = rr.get("candidates", [])
        if not cands:
            return None
        if kind == "price":
            prices = sorted(c["product"].get("price") for c in cands if c["product"].get("price") is not None)
            if not prices:
                return None
            k = prices[min(4, len(prices) - 1)]           # enough budget for ~5 options
            new_budget = float(int((k + 499) // 500 * 500))
            within = sum(1 for x in prices if x <= new_budget)
            return Suggestion(relax="price", label=f"Raise budget to ₹{new_budget:,.0f}", matches=within, budget_max_override=new_budget)
        labels = {"size": f"Show all sizes (not just {filters.size})", "category": "Include similar categories",
                  "gender": "Include all genders"}
        return Suggestion(relax=kind, label=labels[kind], matches=len(cands))

    res = await asyncio.gather(*(one(k, f) for k, f in trials))
    return [r for r in res if r]


async def _cache_get(key: str):
    try:
        v = await STATE["redis"].get(key)
        return json.loads(v) if v else None
    except Exception:
        return None


async def _cache_set(key: str, value: dict):
    try:
        await STATE["redis"].set(key, json.dumps(value, ensure_ascii=False), ex=settings.search_cache_ttl_s)
    except Exception:
        pass


# ------------------------------------------------------------------ search
async def run_search(req: SearchRequest) -> SearchResponse:
    t: dict[str, float] = {}
    t0 = time.perf_counter()
    degraded: list[str] = []
    q = req.query.strip()[: settings.max_query_chars]
    if not q and not req.image_b64:
        raise HTTPException(422, "provide a text query and/or an image")
    has_image = bool(req.image_b64)
    structured = req.mode == "mosaic" and req.ablation.use_intent
    try:
        cver = await catalogue_version(STATE["redis"])
    except Exception:
        cver = -1

    cache_key = None
    if req.use_cache and not has_image:
        cache_key = "search:" + hashlib.sha1(f"{cver}|{req.model_dump_json(exclude={'use_cache'})}".encode()).hexdigest()
        hit = await _cache_get(cache_key)
        if hit:
            hit["cached"] = True
            hit["request_id"] = request_id_var.get()
            return SearchResponse(**hit)

    # 1) intent
    intent: Intent
    if structured and q:
        try:
            with Timer(t, "intent", "gateway"):
                intent = Intent(**await C["intent"].post("/parse", {"query": q, "has_query_image": has_image, "use_llm": req.use_llm}))
        except Exception as e:
            FALLBACKS.labels("gateway", "intent_unavailable").inc()
            degraded.append(f"intent_unavailable:{type(e).__name__}")
            intent = passthrough_intent(q, has_image)
    else:
        intent = passthrough_intent(q, has_image)
    filters = filters_from_intent(intent, structured, req.relax, req.budget_max_override)

    # 2) embeddings (parallel; each optional)
    want_dense = req.mode in ("dense", "hybrid", "mosaic")
    want_visual = req.mode == "mosaic" and req.ablation.use_visual
    dense_text = (f"{q} | {intent.normalized_query_en}" if structured and intent.normalized_query_en and intent.normalized_query_en != q else q)
    clip_text = (clip_prompt_for(intent) or intent.normalized_query_en) if structured else q
    text_vec = clip_vec = img_vec = None

    async def emb_text():
        return (await C["embedding"].post("/embed/text", {"texts": [dense_text], "kind": "query"}))["vectors"][0]

    async def emb_clip():
        return (await C["embedding"].post("/embed/clip-text", {"texts": [f"a photo of {clip_text}"]}))["vectors"][0]

    async def emb_img():
        return (await C["embedding"].post("/embed/image", {"b64": [req.image_b64]}))["vectors"][0]

    jobs = {}
    if want_dense and q:
        jobs["text"] = emb_text()
    if want_visual and q and clip_text:
        jobs["clip"] = emb_clip()
    if has_image and req.mode in ("mosaic", "dense", "hybrid"):
        jobs["image"] = emb_img()
    if jobs:
        with Timer(t, "embedding", "gateway"):
            res = await asyncio.gather(*jobs.values(), return_exceptions=True)
        for name, r in zip(jobs, res):
            if isinstance(r, Exception):
                degraded.append(f"embedding_{name}_unavailable:{type(r).__name__}")
                FALLBACKS.labels("gateway", f"embedding_{name}_failed").inc()
            elif name == "text":
                text_vec = r
            elif name == "clip":
                clip_vec = r
            else:
                img_vec = r
                if r is None:
                    degraded.append("query_image_unreadable")

    # 3) retrieval
    rmode = {"bm25": "bm25", "dense": "dense", "hybrid": "hybrid", "mosaic": req.ablation.retrieval}[req.mode]
    bm25_text = f"{intent.normalized_query_en} {q}" if structured else q
    try:
        with Timer(t, "retrieval", "gateway"):
            rr = await C["retrieval"].post("/retrieve", {
                "query_text": bm25_text, "text_vector": text_vec, "clip_text_vector": clip_vec, "image_query_vector": img_vec,
                "filters": filters.model_dump(), "mode": rmode, "pool": settings.candidate_pool,
                "complete_signals": req.mode == "mosaic"})
    except Exception as e:
        FALLBACKS.labels("gateway", "retrieval_unavailable").inc()
        raise HTTPException(503, f"retrieval unavailable: {type(e).__name__}") from e
    degraded += rr.get("degraded", [])
    cands = [Candidate(**c) for c in rr["candidates"]]
    for k, v in (rr.get("timings_ms") or {}).items():
        t[f"retrieval.{k}"] = v

    # 4) ranking (+ explanations)
    opts = RankOptions(adaptive=req.ablation.adaptive, use_visual=want_visual, use_context=structured and req.ablation.use_context,
                       explain=req.explain, top_k=req.top_k, base_mode=req.mode)
    weights, rationale = {}, []
    try:
        with Timer(t, "ranking", "gateway"):
            rk = await C["ranking"].post("/rank", {"intent": intent.model_dump(), "candidates": [c.model_dump() for c in cands],
                                                   "filters": filters.model_dump(), "options": opts.model_dump()})
        results = [ScoredProduct(**r) for r in rk["results"]]
        weights, rationale = rk["weights"], rk["weight_rationale"]
        for k, v in (rk.get("timings_ms") or {}).items():
            t[f"ranking.{k}"] = v
    except Exception as e:
        FALLBACKS.labels("gateway", "ranking_unavailable").inc()
        degraded.append(f"ranking_unavailable:{type(e).__name__}:retrieval_order")
        results = [ScoredProduct(rank=i, parent_asin=c.parent_asin, title=c.product.get("title", ""), score=round(c.rrf, 4),
                                 components={"rrf": c.rrf}, contributions={}, price=c.product.get("price"), store=c.product.get("store"),
                                 attributes=c.product.get("attributes") or {}, sizes=c.product.get("sizes") or [],
                                 explanation="Ranking service unavailable: shown in retrieval order.")
                   for i, c in enumerate(cands[: req.top_k], 1)]
    suggestions: list[Suggestion] = []
    if not results and structured:
        with Timer(t, "suggestions", "gateway"):
            suggestions = await relaxation_suggestions(filters, {
                "query_text": bm25_text, "text_vector": text_vec, "clip_text_vector": None, "image_query_vector": img_vec,
                "mode": rmode})
    t["total"] = round((time.perf_counter() - t0) * 1000, 2)

    resp = SearchResponse(suggestions=suggestions, 
        request_id=request_id_var.get(), query=q, mode=req.mode, intent=intent, filters=filters, constraints_applied=filters.describe(),
        retrieval_mode=rr.get("mode_used", rmode) + ("+image" if img_vec else "") + ("+clip_rerank" if clip_vec else ""),
        weights=weights, weight_rationale=rationale, results=results, degraded=degraded, timings_ms=t,
        filtered_out=rr.get("filtered_out", {}), index_size=rr.get("index_size", 0), catalogue_version=cver)
    if cache_key and not degraded:
        await _cache_set(cache_key, resp.model_dump(mode="json"))
    return resp


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, request: Request) -> SearchResponse:
    _rate_limit(request)
    return await run_search(req)


FEEDBACK_KEY = "mosaic:feedback"


@app.post("/feedback")
async def feedback(fb: Feedback):
    """Thumbs up/down per result, logged with its score breakdown (monitoring + future learning-to-rank data)."""
    rec = {**fb.model_dump(), "ts": time.time()}
    pipe = STATE["redis"].pipeline()
    pipe.lpush(FEEDBACK_KEY, json.dumps(rec, ensure_ascii=False))
    pipe.ltrim(FEEDBACK_KEY, 0, 99_999)
    pipe.hincrby("mosaic:feedback_counts", fb.vote, 1)
    await pipe.execute()
    log.info("feedback", extra={"extra_fields": {"vote": fb.vote, "asin": fb.parent_asin, "rank": fb.rank}})
    return {"ok": True}


@app.get("/feedback/stats")
async def feedback_stats(limit: int = 20):
    r = STATE["redis"]
    counts = {k.decode() if isinstance(k, bytes) else k: int(v) for k, v in (await r.hgetall("mosaic:feedback_counts")).items()}
    recent = [json.loads(x) for x in await r.lrange(FEEDBACK_KEY, 0, max(0, limit - 1))]
    up, down = counts.get("up", 0), counts.get("down", 0)
    return {"up": up, "down": down, "satisfaction": round(up / (up + down), 3) if up + down else None, "recent": recent}


class CompareRequest(BaseModel):
    query: str = Field(default="", max_length=500)
    image_b64: str | None = None
    top_k: int = Field(default=10, ge=1, le=50)


@app.post("/compare")
async def compare(req: CompareRequest, request: Request):
    _rate_limit(request)
    modes = ["bm25", "dense", "hybrid", "mosaic"]
    res = await asyncio.gather(*(run_search(SearchRequest(query=req.query, image_b64=req.image_b64, mode=m, top_k=req.top_k,
                                                          explain=(m == "mosaic"))) for m in modes), return_exceptions=True)
    out = {}
    for m, r in zip(modes, res):
        out[m] = r.model_dump(mode="json") if not isinstance(r, Exception) else {"error": str(r)}
    return out


# ------------------------------------------------------------------ catalogue (admin)
def _admin(key: str | None) -> dict:
    if key != settings.admin_api_key.get_secret_value():
        raise HTTPException(401, "invalid or missing X-API-Key")
    return {"x-api-key": key}


async def _proxy(method: str, path: str, key: str | None, body=None):
    import httpx
    h = _admin(key)
    try:
        return await C["catalogue"].request(method, path, json=body, headers=h)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.json().get("detail", "catalogue error")) from e


@app.post("/catalogue/products", status_code=201)
async def add_product(p: Product, x_api_key: str | None = Header(default=None)):
    return await _proxy("POST", "/products", x_api_key, p.model_dump(mode="json"))


@app.put("/catalogue/products/{asin}")
async def update_product(asin: str, p: Product, x_api_key: str | None = Header(default=None)):
    return await _proxy("PUT", f"/products/{asin}", x_api_key, p.model_dump(mode="json"))


@app.patch("/catalogue/products/{asin}")
async def patch_product(asin: str, p: ProductPatch, x_api_key: str | None = Header(default=None)):
    return await _proxy("PATCH", f"/products/{asin}", x_api_key, p.model_dump(mode="json", exclude_unset=True))


@app.delete("/catalogue/products/{asin}")
async def delete_product(asin: str, x_api_key: str | None = Header(default=None)):
    return await _proxy("DELETE", f"/products/{asin}", x_api_key)


@app.get("/catalogue/products/{asin}")
async def get_product(asin: str):
    import httpx
    try:
        return await C["catalogue"].get(f"/products/{asin}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, "not found") from e


async def _visible(asin: str, query: str, mode: str) -> bool:
    r = await run_search(SearchRequest(query=query, mode=mode, top_k=50, explain=False, use_cache=False))
    return any(x.parent_asin == asin for x in r.results)


class TTSRequest(BaseModel):
    product: Product | None = None
    probe_query: str | None = None
    timeout_s: float = 30.0
    cleanup: bool = True


@app.post("/catalogue/time-to-searchable")
async def time_to_searchable(req: TTSRequest, x_api_key: str | None = Header(default=None)):
    """Adds a product and measures how long until it is returned by search (lexical and dense paths)."""
    p = req.product or Product(
        parent_asin=f"TTS{uuid.uuid4().hex[:10].upper()}", title="Zyphora Women's Seafoam Linen Kaftan Dress for Beach Holidays",
        store="Zyphora", price=1499, stock_qty=25, sizes=["S", "M", "L"], features=["Fabric: Linen – breathable and soft", "Ideal for beach holidays"],
        details={"Material": "Linen", "Color": "Teal", "Department": "Womens"}, images=[])
    probe = req.probe_query or p.title
    t0 = time.perf_counter()
    await _proxy("POST", "/products", x_api_key, p.model_dump(mode="json"))
    t_write = time.perf_counter() - t0
    seen: dict[str, float | None] = {"bm25": None, "dense": None}
    while time.perf_counter() - t0 < req.timeout_s and None in seen.values():
        for mode in [m for m, v in seen.items() if v is None]:
            try:
                if await _visible(p.parent_asin, probe, mode):
                    seen[mode] = round((time.perf_counter() - t0) * 1000, 1)
            except Exception:
                pass
        await asyncio.sleep(0.05)
    indexed = await STATE["redis"].hget("mosaic:indexed_at", p.parent_asin)
    if req.cleanup:
        await _proxy("DELETE", f"/products/{p.parent_asin}", x_api_key)
    return {"parent_asin": p.parent_asin, "write_ack_ms": round(t_write * 1000, 1), "searchable_lexical_ms": seen["bm25"],
            "searchable_dense_ms": seen["dense"], "indexer_record": indexed.decode() if indexed else None, "cleaned_up": req.cleanup}


@app.get("/system/status")
async def system_status():
    names = ["intent", "embedding", "retrieval", "ranking", "catalogue"]
    ready = dict(zip(names, await asyncio.gather(*(C[n].ready() for n in names))))
    out = {"ready": ready, "breakers": {n: C[n].breaker.state for n in names}}
    for name, path in (("catalogue", "/stats"), ("retrieval", "/stats"), ("intent", "/info"), ("embedding", "/info")):
        try:
            out[f"{name}_stats"] = await C[name].get(path)
        except Exception as e:
            out[f"{name}_stats"] = {"error": type(e).__name__}
    return out