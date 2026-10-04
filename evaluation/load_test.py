"""System-health load test against the live gateway (closed-loop virtual users).

Measures end-to-end P50/P95/P99 latency, throughput (req/s), error rate and per-component timing
percentiles (from the `timings_ms` every response carries) for several concurrency levels.
Queries are the 120 multilingual evaluation queries; cache disabled unless --cache.

    python -m evaluation.load_test --levels 1,4,8 --duration 30 --mode mosaic
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from collections import defaultdict
from pathlib import Path

import httpx


def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    f, c = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 1)


async def level(api: str, queries: list[str], conc: int, duration: float, mode: str, cache: bool, seed: int) -> dict:
    rng = random.Random(seed)
    lat: list[float] = []
    comps: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    degraded = 0
    stop = time.perf_counter() + duration
    async with httpx.AsyncClient(base_url=api, timeout=30, limits=httpx.Limits(max_connections=conc * 2)) as c:
        async def user():
            nonlocal degraded
            while time.perf_counter() < stop:
                q = rng.choice(queries)
                t0 = time.perf_counter()
                try:
                    r = await c.post("/search", json={"query": q, "mode": mode, "top_k": 10, "use_cache": cache})
                    dt = (time.perf_counter() - t0) * 1000
                    if r.status_code == 200:
                        lat.append(dt)
                        d = r.json()
                        degraded += bool(d.get("degraded"))
                        for k, v in d["timings_ms"].items():
                            comps[k].append(v)
                    else:
                        errors[str(r.status_code)] += 1
                except Exception as e:
                    errors[type(e).__name__] += 1
        t_start = time.perf_counter()
        await asyncio.gather(*(user() for _ in range(conc)))
        wall = time.perf_counter() - t_start
    n_err = sum(errors.values())
    total = len(lat) + n_err
    return {
        "concurrency": conc, "mode": mode, "cache": cache, "requests": total, "duration_s": round(wall, 1),
        "throughput_rps": round(len(lat) / wall, 2), "error_rate": round(n_err / total, 4) if total else None, "errors": dict(errors),
        "degraded_responses": degraded,
        "latency_ms": {"p50": pct(lat, 50), "p95": pct(lat, 95), "p99": pct(lat, 99), "mean": round(statistics.fmean(lat), 1) if lat else None,
                       "max": round(max(lat), 1) if lat else None},
        "components_ms": {k: {"p50": pct(v, 50), "p95": pct(v, 95), "p99": pct(v, 99)} for k, v in sorted(comps.items())},
    }


def to_md(results: list[dict], meta: dict) -> str:
    L = ["# Load test / system health report\n",
         f"_Generated {meta['generated']} · catalogue size {meta['catalogue_size']} · host: {meta['host']} · "
         f"closed-loop virtual users, {meta['duration']}s per level, random draw from {meta['n_queries']} multilingual queries · all numbers measured in this run._\n",
         "## End-to-end", "| mode | cache | concurrency | requests | throughput (req/s) | P50 ms | P95 ms | P99 ms | error rate | degraded |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        l = r["latency_ms"]
        L.append(f"| {r['mode']} | {r['cache']} | {r['concurrency']} | {r['requests']} | {r['throughput_rps']} | {l['p50']} | {l['p95']} | {l['p99']} | "
                 f"{r['error_rate']} | {r['degraded_responses']} |")
    L.append("\n## Component timings (server-side, ms)")
    for r in results:
        L += [f"\n**{r['mode']} · cache={r['cache']} · concurrency {r['concurrency']}**\n", "| component | P50 | P95 | P99 |", "|---|---|---|---|"]
        for k, v in r["components_ms"].items():
            L.append(f"| {k} | {v['p50']} | {v['p95']} | {v['p99']} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--levels", default="1,4,8")
    ap.add_argument("--duration", type=float, default=30)
    ap.add_argument("--modes", default="mosaic")
    ap.add_argument("--cache", action="store_true")
    ap.add_argument("--out", default="evaluation/reports")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    needs = [json.loads(l) for l in open("evaluation/queries/needs.jsonl")]
    queries = [q for n in needs for q in n["q"].values()]
    import os
    import platform
    st = httpx.get(f"{a.api}/system/status", timeout=10).json()
    meta = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "catalogue_size": st.get("catalogue_stats", {}).get("products"),
            "host": f"{platform.machine()} · {os.cpu_count()} vCPU (all services + Postgres/Redis/Qdrant on the same host)",
            "duration": a.duration, "n_queries": len(queries)}
    results = []
    for mode in a.modes.split(","):
        for conc in [int(x) for x in a.levels.split(",")]:
            r = asyncio.run(level(a.api, queries, conc, a.duration, mode, a.cache, seed=conc))
            print(json.dumps({k: v for k, v in r.items() if k != "components_ms"}))
            results.append(r)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    name = f"load_test{a.tag}"
    (out / f"{name}.json").write_text(json.dumps({"meta": meta, "results": results}, indent=1))
    (out / f"{name}.md").write_text(to_md(results, meta))
    print(to_md(results, meta))


if __name__ == "__main__":
    main()
