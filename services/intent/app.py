"""Intent service: language detection -> LLM decomposition (optional, free providers) -> attribute
normalisation -> merge with deterministic parse. Rules-only path on any LLM failure/timeout."""
from __future__ import annotations

import asyncio
import hashlib
import json

import redis.asyncio as aioredis

from mosaic_common.config import get_settings
from mosaic_common.schemas import Intent, IntentRequest
from mosaic_common.service import FALLBACKS, Timer, create_service
from services.intent import rule_parser
from services.intent.llm import LLMClient, LLMError
from services.intent.normalizer import merge, normalise_llm
from services.intent.output_security import validate_intent

settings = get_settings()
STATE: dict = {}


async def _ready():
    return {"rules": True, "llm_configured": True}  # LLM is optional by design: never blocks readiness


app = create_service("intent", ready_check=_ready)
log = app.state.logger


@app.on_event("startup")
async def _startup():
    STATE["llm"] = LLMClient(settings)
    STATE["redis"] = aioredis.from_url(settings.redis_url, protocol=2)


@app.post("/parse", response_model=Intent)
async def parse(req: IntentRequest) -> Intent:
    timings: dict[str, float] = {}
    with Timer(timings, "rules", "intent"):
        rules = rule_parser.parse(req.query, req.has_query_image)
    llm: LLMClient = STATE["llm"]
    if not (req.use_llm and llm.enabled):
        return rules
    key = "intent:" + hashlib.sha1(f"{settings.llm_model}|{req.query}".encode()).hexdigest()
    try:
        cached = await STATE["redis"].get(key)
        if cached:
            raw = json.loads(cached)
        else:
            with Timer(timings, "llm", "intent"):
                raw = await asyncio.wait_for(llm.decompose(req.query), timeout=settings.llm_timeout_s)
            await STATE["redis"].set(key, json.dumps(raw), ex=86400)
        norm, warn = normalise_llm(validate_intent(raw))
        out = merge(rules, norm, warn)
        out.has_query_image = req.has_query_image
        return out
    except (LLMError, asyncio.TimeoutError, Exception) as e:  # graceful fallback
        FALLBACKS.labels("intent", "llm_failed").inc()
        rules.warnings.append(f"llm unavailable ({type(e).__name__}); used deterministic parser")
        return rules


@app.get("/info")
async def info():
    return {"llm_provider": settings.llm_provider, "llm_model": settings.llm_model if settings.llm_provider != "none" else None,
            "languages": ["en", "ta", "tanglish", "hi", "hinglish"]}
