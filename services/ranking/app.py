"""Ranking service: hard-constraint enforcement (defence in depth) -> context-adaptive multi-signal
fusion -> top-k -> grounded explanations. Also serves baseline orderings (bm25/dense/hybrid) with
the same output contract so the UI and evaluator compare like-for-like."""
from __future__ import annotations

import asyncio

from mosaic_common.config import get_settings
from mosaic_common.filters import violations
from mosaic_common.prompts import clip_prompt_for
from mosaic_common.schemas import RankRequest, RankResponse, ScoredProduct
from mosaic_common.service import FALLBACKS, Timer, create_service
from services.intent.llm import LLMClient
from services.ranking import adaptive, explain, signals

settings = get_settings()
STATE: dict = {}
app = create_service("ranking")
log = app.state.logger


@app.on_event("startup")
async def _startup():
    STATE["llm"] = LLMClient(settings)


def _image(p: dict) -> str | None:
    imgs = p.get("images") or []
    return (imgs[0] or {}).get("large") if imgs else None


@app.post("/rank", response_model=RankResponse)
async def rank(req: RankRequest) -> RankResponse:
    t: dict[str, float] = {}
    intent, opts, f = req.intent, req.options, req.filters
    with Timer(t, "constraints", "ranking"):
        kept = [c for c in req.candidates if not violations(c.product, f)]
        dropped = len(req.candidates) - len(kept)
        if dropped:
            log.warning("retrieval returned constraint violators; dropped", extra={"extra_fields": {"n": dropped}})

    with Timer(t, "signals", "ranking"):
        rows = signals.compute_all(intent, kept, use_visual=opts.use_visual, use_context=opts.use_context)
    visual_available = any(r["visual"] is not None for r in rows)

    if opts.base_mode != "mosaic":
        raw_key = {"bm25": lambda c: c.bm25, "dense": lambda c: max(c.dense, c.image_dense), "hybrid": lambda c: c.rrf}[opts.base_mode]
        sig_name = {"bm25": "lexical", "dense": "semantic", "hybrid": "rrf"}[opts.base_mode]
        raws = signals.minmax([raw_key(c) for c in kept])
        weights = {sig_name: 1.0}
        rationale = [f"baseline ordering by {opts.base_mode} score only"]
        scored = []
        for c, row, r in zip(kept, rows, raws):
            comps = {k: round(v, 4) for k, v in row.items() if v is not None}
            comps[sig_name] = round(r or 0.0, 4)
            scored.append((raw_key(c), r or 0.0, c, comps, {sig_name: round(r or 0.0, 4)}))
    else:
        weights, rationale = adaptive.adaptive_weights(intent, visual_available, opts.use_visual, opts.use_context) if opts.adaptive \
            else adaptive.fixed_weights()
        if opts.adaptive is False and not opts.use_visual:
            weights = adaptive._norm({k: (0.0 if k == "visual" else v) for k, v in weights.items()})
        scored = []
        with Timer(t, "fusion", "ranking"):
            for c, row in zip(kept, rows):
                s, contrib, _eff = adaptive.score(row, weights)
                comps = {k: round(v, 4) for k, v in row.items() if v is not None}
                scored.append((s, s, c, comps, contrib))
    scored.sort(key=lambda x: (x[0], x[2].rrf), reverse=True)
    top = scored[: opts.top_k]

    prompt = clip_prompt_for(intent)
    results: list[ScoredProduct] = []
    with Timer(t, "explain", "ranking"):
        for i, (_k, s, c, comps, contrib) in enumerate(top, 1):
            p = c.product
            text, cons = ("", explain.constraint_facts(p, intent, f))
            src = "none"
            if opts.explain:
                text, cons = explain.template_explanation(intent, p, comps, contrib, f, prompt)
                src = "template"
            results.append(ScoredProduct(
                rank=i, parent_asin=c.parent_asin, title=p.get("title", ""), score=round(float(s), 4), components=comps,
                contributions=contrib, price=p.get("price"), store=p.get("store"), image=_image(p), has_image=c.visual is not None,
                in_stock=int(p.get("stock_qty") or 0) > 0, sizes=p.get("sizes") or [], attributes=p.get("attributes") or {},
                constraints_satisfied=cons, explanation=text, explanation_source=src, url=p.get("url"),
                rating=p.get("average_rating")))
        llm: LLMClient = STATE["llm"]
        if opts.explain and settings.llm_explanations and llm.enabled and results:
            await _llm_polish(results[:5], intent, llm)
    return RankResponse(results=results, weights={k: round(v, 4) for k, v in weights.items()}, weight_rationale=rationale, timings_ms=t)


async def _llm_polish(results: list[ScoredProduct], intent, llm: LLMClient) -> None:
    needs = intent.normalized_query_en or intent.original_query

    async def one(r: ScoredProduct):
        a = r.attributes
        facts = (f"title={r.title}; price={r.price}; materials={a.get('materials')}; occasions={a.get('occasions')}; "
                 f"comfort={a.get('comfort_tags')}; category={a.get('category')}; template={r.explanation}")
        try:
            txt = await asyncio.wait_for(llm.explain(facts, needs), timeout=settings.llm_timeout_s)
            if explain.grounded(txt, facts + " " + needs):
                r.explanation, r.explanation_source = txt, "llm"
            else:
                FALLBACKS.labels("ranking", "llm_explanation_ungrounded").inc()
        except Exception:
            FALLBACKS.labels("ranking", "llm_explanation_failed").inc()

    await asyncio.gather(*(one(r) for r in results))