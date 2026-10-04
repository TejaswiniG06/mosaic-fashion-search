"""Download product images referenced by an (Amazon) catalogue JSONL into IMAGE_ROOT and rewrite the
references to `local://` paths. Failures are tolerated: the product keeps its remote URL (the embedding
service retries it at index time) or ends up text-only (image fallback).

    python -m ingestion.download_images --file data/amazon_catalogue.jsonl --out data/amazon_catalogue.local.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import httpx

from mosaic_common.config import get_settings


async def fetch(c: httpx.AsyncClient, url: str, dest: Path, sem: asyncio.Semaphore) -> bool:
    if dest.exists():
        return True
    async with sem:
        try:
            r = await c.get(url)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                dest.write_bytes(r.content)
                return True
        except Exception:
            pass
    return False


async def main_async(a):
    s = get_settings()
    root = s.image_root / "amazon"
    root.mkdir(parents=True, exist_ok=True)
    items = [json.loads(l) for l in open(a.file) if l.strip()]
    sem = asyncio.Semaphore(a.concurrency)
    ok = 0
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        tasks = []
        for p in items:
            imgs = p.get("images") or []
            url = imgs[0].get("large") if imgs else None
            if url and url.startswith("http"):
                name = hashlib.sha1(url.encode()).hexdigest()[:20] + ".jpg"
                tasks.append((p, name, fetch(c, url, root / name, sem)))
        results = await asyncio.gather(*(t[2] for t in tasks))
        for (p, name, _), good in zip(tasks, results):
            if good:
                p["images"][0]["large"] = f"local://amazon/{name}"
                ok += 1
    with open(a.out, "w") as f:
        for p in items:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"downloaded {ok}/{len(tasks)} images; wrote {a.out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--concurrency", type=int, default=16)
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
