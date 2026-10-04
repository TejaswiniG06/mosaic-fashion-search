"""Bulk-load a catalogue JSONL (Amazon-2023 schema) through the catalogue service API, then wait
until the indexer has drained the event stream. Loading goes through the same ADD path as live
catalogue updates (outbox -> stream -> incremental index), so there is no separate offline build.

    python -m ingestion.load_catalogue --file data/catalogue.jsonl [--limit 5000] [--batch 500]
"""
from __future__ import annotations

import argparse
import json
import time

import httpx

from mosaic_common.config import get_settings


def main() -> None:
    s = get_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/catalogue.jsonl")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--no-wait", action="store_true")
    a = ap.parse_args()
    headers = {"x-api-key": s.admin_api_key.get_secret_value()}
    items = []
    with open(a.file) as f:
        for line in f:
            if line.strip():
                items.append(json.loads(line))
            if a.limit and len(items) >= a.limit:
                break
    t0 = time.time()
    with httpx.Client(base_url=s.catalogue_url, timeout=300, headers=headers) as c:
        for i in range(0, len(items), a.batch):
            r = c.post("/products/bulk", json=items[i:i + a.batch])
            r.raise_for_status()
            print(f"  upserted {min(i + a.batch, len(items))}/{len(items)}", flush=True)
    print(f"catalogue write done in {time.time() - t0:.1f}s")
    if a.no_wait:
        return
    with httpx.Client(timeout=10) as c:
        last = None
        while True:
            st = c.get(f"{s.indexer_url}/stats").json()
            lag = (st.get("stream") or {})
            pending, behind = lag.get("pending") or 0, lag.get("lag") or 0
            if (pending, behind) != last:
                print(f"  indexer: processed={st.get('processed')} pending={pending} lag={behind}", flush=True)
                last = (pending, behind)
            if pending == 0 and behind == 0:
                break
            time.sleep(2)
    print(f"indexed & searchable in {time.time() - t0:.1f}s total")


if __name__ == "__main__":
    main()
