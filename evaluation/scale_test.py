"""Catalogue scale test: grow the LIVE catalogue step by step (e.g. 5K -> 20K -> 50K -> 100K) through the
normal ADD path and, at each size, measure what actually happens:

  * ingestion throughput (products/s until fully indexed) and time-to-searchable
  * query latency P50/P95/P99 (sequential and concurrent) for MOSAIC and Hybrid
  * relevance (NDCG@10, P@10, ConstraintSat@10) for BM25 / Dense / Hybrid / MOSAIC on the 120 queries
  * process memory (RSS) of retrieval, Qdrant, Postgres, Redis

Nothing is extrapolated: a size is only reported if it was actually loaded and measured.

    python -m evaluation.scale_test --sizes 20000,50000,100000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from pathlib import Path

import httpx

from evaluation.judge import load_truth
from evaluation.load_test import level
from evaluation.run_offline_eval import SYSTEMS, run, summarise
from ingestion.synthetic_catalogue import generate
from mosaic_common.config import get_settings

S = get_settings()
API = "http://localhost:8000"


def rss_mb(pattern: str) -> float | None:
    try:
        out = subprocess.run(["bash", "-c", f"ps -eo rss,args | grep -E '{pattern}' | grep -v grep | awk '{{s+=$1}} END {{print s}}'"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return round(int(out) / 1024, 1) if out else None
    except Exception:
        return None


def catalogue_count() -> int:
    return httpx.get(f"{S.catalogue_url}/stats", timeout=30).json()["products"]


def wait_indexed(t0: float) -> float:
    while True:
        st = httpx.get(f"{S.indexer_url}/stats", timeout=10).json()["stream"]
        if (st.get("pending") or 0) == 0 and (st.get("lag") or 0) == 0:
            return time.time() - t0
        time.sleep(2)


def grow_to(target: int, truth_path: Path, batch: int = 1000) -> dict:
    cur = catalogue_count()
    need = target - cur
    if need <= 0:
        return {"added": 0}
    products, truth = generate(need, seed=10_000 + target, start_index=1_000_000 + cur)
    with open(truth_path, "a") as f:
        for t in truth:
            f.write(json.dumps(t) + "\n")
    headers = {"x-api-key": S.admin_api_key.get_secret_value()}
    t0 = time.time()
    with httpx.Client(base_url=S.catalogue_url, timeout=600, headers=headers) as c:
        for i in range(0, len(products), batch):
            c.post("/products/bulk", json=products[i:i + batch]).raise_for_status()
    t_write = time.time() - t0
    t_index = wait_indexed(t0)
    return {"added": need, "write_s": round(t_write, 1), "fully_indexed_s": round(t_index, 1), "ingest_products_per_s": round(need / t_index, 1)}


def latency(mode: str, conc: int, duration: float, queries: list[str]) -> dict:
    r = asyncio.run(level(API, queries, conc, duration, mode, cache=False, seed=conc))
    return {"concurrency": conc, "throughput_rps": r["throughput_rps"], **r["latency_ms"], "error_rate": r["error_rate"],
            "retrieval_p50": r["components_ms"].get("retrieval", {}).get("p50"), "dense_ann_p50": r["components_ms"].get("retrieval.dense_ann", {}).get("p50"),
            "bm25_p50": r["components_ms"].get("retrieval.bm25", {}).get("p50")}


def to_md(steps: list[dict]) -> str:
    L = ["# Scale test report\n", "_Each row is a catalogue size that was actually loaded through the live ADD path and measured on this host "
         "(2 vCPU, 7 GB RAM; all services + Qdrant + Postgres + Redis co-located). No extrapolation._\n",
         "## Ingestion & freshness", "| catalogue size | products added | ingest rate (products/s, to fully indexed) | time-to-searchable lexical (ms) | dense (ms) |",
         "|---|---|---|---|---|"]
    for s in steps:
        g, tts = s["growth"], s.get("tts", {})
        L.append(f"| {s['size']} | {g.get('added', 0)} | {g.get('ingest_products_per_s', '-')} | {tts.get('searchable_lexical_ms')} | {tts.get('searchable_dense_ms')} |")
    L += ["\n## Query latency (ms, end-to-end through the gateway, cache off)",
          "| size | mode | concurrency | P50 | P95 | P99 | throughput (req/s) | retrieval P50 | ANN P50 | BM25 P50 | errors |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in steps:
        for l in s["latency"]:
            L.append(f"| {s['size']} | {l['mode']} | {l['concurrency']} | {l['p50']} | {l['p95']} | {l['p99']} | {l['throughput_rps']} | "
                     f"{l['retrieval_p50']} | {l['dense_ann_p50']} | {l['bm25_p50']} | {l['error_rate']} |")
    L += ["\n## Relevance at scale (120 multilingual queries)", "| size | system | NDCG@10 | P@10 | MRR | ConstraintSat@10 |", "|---|---|---|---|---|---|"]
    for s in steps:
        for name, m in s["quality"].items():
            L.append(f"| {s['size']} | {name} | {m['NDCG@10']:.3f} | {m['P@10']:.3f} | {m['MRR']:.3f} | {m['ConstraintSat@10']:.3f} |")
    L += ["\n## Memory (RSS, MB)", "| size | retrieval svc | qdrant | postgres | redis |", "|---|---|---|---|---|"]
    for s in steps:
        m = s["memory_mb"]
        L.append(f"| {s['size']} | {m['retrieval']} | {m['qdrant']} | {m['postgres']} | {m['redis']} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="20000,50000,100000")
    ap.add_argument("--duration", type=float, default=15)
    ap.add_argument("--base-truth", default="data/ground_truth.jsonl")
    ap.add_argument("--out", default="evaluation/reports")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    truth_path = Path("data/ground_truth_scale.jsonl")
    if not truth_path.exists():
        truth_path.write_text(Path(a.base_truth).read_text())
    needs = [json.loads(l) for l in open("evaluation/queries/needs.jsonl")]
    queries = [q for n in needs for q in n["q"].values()]
    report_path = out / "scale_test.json"
    steps = json.loads(report_path.read_text())["steps"] if report_path.exists() else []
    sizes = [catalogue_count()] + [int(x) for x in a.sizes.split(",")]
    headers = {"x-api-key": S.admin_api_key.get_secret_value()}
    for target in sizes:
        if any(s["size"] == target for s in steps):
            print(f"size {target} already measured; skipping")
            continue
        growth = grow_to(target, truth_path)
        size = catalogue_count()
        print(f"== size {size}: {growth}", flush=True)
        tts = httpx.post(f"{API}/catalogue/time-to-searchable", json={}, headers=headers, timeout=60).json()
        lat = []
        for mode in ("mosaic", "hybrid"):
            for conc in (1, 4):
                lat.append({"mode": mode, **latency(mode, conc, a.duration, queries)})
        truth = load_truth(truth_path)
        systems = {k: SYSTEMS[k] for k in ("BM25", "Dense", "Hybrid", "MOSAIC")}
        res = asyncio.run(run(API, needs, truth, systems))
        quality = {k: v for k, v in summarise(res["rows"])["overall"].items()}
        mem = {"retrieval": rss_mb("uvicorn services[.]retrieval"), "qdrant": rss_mb("[.]/qdrant"), "postgres": rss_mb("postgres"),
               "redis": rss_mb("redis-server")}
        step = {"size": size, "growth": growth, "tts": tts, "latency": lat, "quality": quality, "memory_mb": mem,
                "measured_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        steps.append(step)
        report_path.write_text(json.dumps({"steps": steps}, indent=1))
        (out / "scale_test.md").write_text(to_md(steps))
        print(json.dumps({k: v for k, v in step.items() if k != "quality"}, indent=None)[:1500], flush=True)
    print(to_md(steps))


if __name__ == "__main__":
    main()
