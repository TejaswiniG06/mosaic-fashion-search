"""Embedding service: multilingual text vectors (e5) + CLIP text/image vectors.

Production notes
  * models load once at startup; /ready is 503 until loaded
  * query vectors cached in Redis (sha1(model_version|kind|text)); image vectors cached by image
    content hash (identical images => identical vector; also makes re-indexing cheap)
  * image loading supports local paths (`local://`), http(s) URLs (with timeout) and base64; any
    failure returns `null` for that item (image fallback) instead of failing the batch
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import numpy as np
import redis.asyncio as aioredis
from fastapi import HTTPException
from pydantic import BaseModel, Field

from mosaic_common.config import get_settings
from mosaic_common.service import FALLBACKS, Timer, create_service
from services.embedding.encoders import ClipEncoder, TextEncoder, decode_image, image_digest

settings = get_settings()
STATE: dict = {}


class TextReq(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=256)
    kind: str = Field(default="query", pattern="^(query|passage)$")


class ClipTextReq(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=256)


class ImageReq(BaseModel):
    refs: list[str | None] = Field(default_factory=list, max_length=128)   # local://..., http(s)://..., or file path
    b64: list[str] = Field(default_factory=list, max_length=8)


async def _ready():
    return {"text_model": "text" in STATE, "clip_model": "clip" in STATE}


app = create_service("embedding", ready_check=_ready)
log = app.state.logger


@app.on_event("startup")
async def _startup():
    loop = asyncio.get_running_loop()
    STATE["redis"] = aioredis.from_url(settings.redis_url, protocol=2)
    STATE["http"] = httpx.AsyncClient(timeout=settings.image_fetch_timeout_s, follow_redirects=True)
    STATE["text"] = await loop.run_in_executor(None, lambda: TextEncoder(settings.text_model_dir, settings.text_model_file, settings.onnx_threads))
    STATE["clip"] = await loop.run_in_executor(None, lambda: ClipEncoder(settings.clip_model_dir, settings.onnx_threads))
    STATE["lock"] = asyncio.Semaphore(2)
    log.info("models loaded", extra={"extra_fields": {"text": STATE["text"].version, "clip": STATE["clip"].version}})


def _key(*parts: str) -> str:
    return "emb:" + hashlib.sha1("|".join(parts).encode()).hexdigest()


async def _cached_encode(texts: list[str], namespace: str, fn) -> list[list[float]]:
    r: aioredis.Redis = STATE["redis"]
    keys = [_key(namespace, t) for t in texts]
    try:
        cached = await r.mget(keys)
    except Exception:
        cached = [None] * len(keys)
        FALLBACKS.labels("embedding", "redis_cache_unavailable").inc()
    miss = [i for i, c in enumerate(cached) if c is None]
    out: list = [np.frombuffer(c, dtype=np.float32).tolist() if c is not None else None for c in cached]
    if miss:
        async with STATE["lock"]:
            vecs = await asyncio.get_running_loop().run_in_executor(None, fn, [texts[i] for i in miss])
        try:
            pipe = r.pipeline()
            for i, v in zip(miss, vecs):
                out[i] = v.tolist()
                pipe.set(keys[i], v.astype(np.float32).tobytes(), ex=86400)
            await pipe.execute()
        except Exception:
            for i, v in zip(miss, vecs):
                out[i] = v.tolist()
    return out


@app.post("/embed/text")
async def embed_text(req: TextReq):
    enc: TextEncoder = STATE["text"]
    timings: dict[str, float] = {}
    with Timer(timings, "e5_encode", "embedding"):
        if req.kind == "query":
            vecs = await _cached_encode(req.texts, f"{enc.version}|q", lambda t: enc.encode(t, "query"))
        else:
            async with STATE["lock"]:
                vecs = (await asyncio.get_running_loop().run_in_executor(None, lambda: enc.encode(req.texts, "passage"))).tolist()
    return {"vectors": vecs, "model": enc.version, "dim": enc.dim, "timings_ms": timings}


@app.post("/embed/clip-text")
async def embed_clip_text(req: ClipTextReq):
    clip: ClipEncoder = STATE["clip"]
    timings: dict[str, float] = {}
    with Timer(timings, "clip_text_encode", "embedding"):
        vecs = await _cached_encode(req.texts, f"{clip.version}|t", clip.encode_text)
    return {"vectors": vecs, "model": clip.version, "dim": clip.dim, "timings_ms": timings}


async def _load_bytes(ref: str) -> bytes | None:
    try:
        if ref.startswith("local://"):
            p = (settings.image_root / ref[len("local://"):]).resolve()
            if settings.image_root.resolve() not in p.parents:
                return None  # path traversal guard
            return await asyncio.to_thread(p.read_bytes)
        if ref.startswith(("http://", "https://")):
            r = await STATE["http"].get(ref)
            if r.status_code == 200 and len(r.content) <= settings.max_image_bytes:
                return r.content
            return None
        p = Path(ref)
        if p.is_file():
            return await asyncio.to_thread(p.read_bytes)
    except Exception:
        return None
    return None


async def _image_vectors(blobs: list[bytes | None]) -> tuple[list[list[float] | None], int]:
    clip: ClipEncoder = STATE["clip"]
    r: aioredis.Redis = STATE["redis"]
    out: list[list[float] | None] = [None] * len(blobs)
    digests = [image_digest(b) if b else None for b in blobs]
    keys = [_key(clip.version, "img", d) if d else None for d in digests]
    try:
        cached = await r.mget([k for k in keys if k]) if any(keys) else []
    except Exception:
        cached = [None] * sum(1 for k in keys if k)
    it = iter(cached)
    todo: dict[str, list[int]] = {}
    for i, k in enumerate(keys):
        if not k:
            continue
        c = next(it)
        if c is not None:
            out[i] = np.frombuffer(c, dtype=np.float32).tolist()
        else:
            todo.setdefault(digests[i], []).append(i)
    failed = 0
    if todo:
        imgs, idx_groups = [], []
        for d, idxs in todo.items():
            try:
                imgs.append(decode_image(blobs[idxs[0]]))
                idx_groups.append((d, idxs))
            except Exception:
                failed += len(idxs)
        if imgs:
            async with STATE["lock"]:
                vecs = await asyncio.get_running_loop().run_in_executor(None, clip.encode_images, imgs)
            pipe = r.pipeline()
            for (d, idxs), v in zip(idx_groups, vecs):
                for i in idxs:
                    out[i] = v.tolist()
                pipe.set(_key(clip.version, "img", d), v.tobytes(), ex=7 * 86400)
            try:
                await pipe.execute()
            except Exception:
                pass
    return out, failed


@app.post("/embed/image")
async def embed_image(req: ImageReq):
    timings: dict[str, float] = {}
    with Timer(timings, "image_load", "embedding"):
        blobs: list[bytes | None] = list(await asyncio.gather(*[_load_bytes(r) if r else asyncio.sleep(0, None) for r in req.refs]))
        for b in req.b64:
            try:
                raw = base64.b64decode(b.split(",")[-1], validate=False)
                if len(raw) > settings.max_image_bytes:
                    raise HTTPException(413, "image too large")
                blobs.append(raw)
            except HTTPException:
                raise
            except Exception:
                blobs.append(None)
    with Timer(timings, "clip_image_encode", "embedding"):
        vecs, failed = await _image_vectors(blobs)
    missing = sum(1 for v in vecs if v is None)
    if missing:
        FALLBACKS.labels("embedding", "image_unavailable").inc(missing)
    return {"vectors": vecs, "missing": missing, "model": STATE["clip"].version, "dim": 512, "timings_ms": timings}


@app.get("/info")
async def info():
    return {"text_model": STATE["text"].version, "text_dim": 384, "clip_model": STATE["clip"].version, "clip_dim": 512,
            "runtime": "onnxruntime-cpu"}
