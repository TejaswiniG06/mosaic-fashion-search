"""Offline relevance evaluation against the running stack (all numbers produced by real API calls).

Systems:  BM25 | Dense | Hybrid (RRF) | MOSAIC
Ablations (MOSAIC variants): fixed vs adaptive weights · text vs text+image · dense vs hybrid
candidates · without vs with intent decomposition · without context signals.
Breakdowns: per language (en / ta / tanglish / hi). Significance: paired permutation test.

    python -m evaluation.run_offline_eval --truth data/ground_truth.jsonl --out evaluation/reports
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path

import httpx

from evaluation.judge import all_grades, load_truth, requirements_ok
from evaluation.metrics import all_metrics, paired_permutation_test
from services.intent.language import detect_language

SYSTEMS = {
    "BM25": {"mode": "bm25"},
    "Dense": {"mode": "dense"},
    "Hybrid": {"mode": "hybrid"},
    "MOSAIC": {"mode": "mosaic"},
    "MOSAIC-fixed-weights": {"mode": "mosaic", "ablation": {"adaptive": False}},
    "MOSAIC-text-only": {"mode": "mosaic", "ablation": {"use_visual": False}},
    "MOSAIC-dense-candidates": {"mode": "mosaic", "ablation": {"retrieval": "dense"}},
    "MOSAIC-no-intent": {"mode": "mosaic", "ablation": {"use_intent": False}},
    "MOSAIC-no-context": {"mode": "mosaic", "ablation": {"use_context": False}},
    # constraint-aware baseline: intent-derived hard filters + fixed semantic/lexical fusion, no image, no context
    "Hybrid+filters": {"mode": "mosaic", "ablation": {"adaptive": False, "use_visual": False, "use_context": False}},
}
METRICS = ["P@5", "P@10", "R@10", "NDCG@10", "MRR", "MAP@10", "HitRate@10", "ConstraintSat@10"]
LANGS = ["en", "ta", "tanglish", "hi"]


async def run(api: str, needs: list[dict], truth: dict, systems: dict, concurrency: int = 4) -> dict:
    sem = asyncio.Semaphore(concurrency)
    grades_cache = {n["id"]: all_grades(truth, n) for n in needs}
    rows: list[dict] = []
    async with httpx.AsyncClient(base_url=api, timeout=60) as c:
        async def one(sys_name: str, cfg: dict, need: dict, lang: str):
            q = need["q"][lang]
            body = {"query": q, "top_k": 10, "explain": False, "use_cache": False, **cfg}
            async with sem:
                t0 = time.perf_counter()
                r = await c.post("/search", json=body)
                dt = (time.perf_counter() - t0) * 1000
            if r.status_code != 200:
                rows.append({"system": sys_name, "need": need["id"], "lang": lang, "error": r.status_code})
                return
            data = r.json()
            ranked = [x["parent_asin"] for x in data["results"]]
            cons = [requirements_ok(truth[a], need["req"]) if a in truth else False for a in ranked]
            m = all_metrics(ranked, grades_cache[need["id"]], cons)
            rows.append({"system": sys_name, "need": need["id"], "lang": lang, "latency_ms": round(dt, 1),
                         "server_ms": data["timings_ms"].get("total"), "detected_lang": data["intent"]["language"] if data.get("intent") else None,
                         "n_results": len(ranked), "degraded": data.get("degraded", []), **m})

        await asyncio.gather(*(one(s, cfg, n, l) for s, cfg in systems.items() for n in needs for l in LANGS))
    return {"rows": rows, "n_relevant": {k: sum(1 for g in v.values() if g >= 2) for k, v in grades_cache.items()}}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 4) if xs else None


def summarise(rows: list[dict]) -> dict:
    by_sys: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if "error" not in r:
            by_sys[r["system"]].append(r)
    overall = {s: {m: mean([r[m] for r in rs]) for m in METRICS} | {"queries": len(rs), "mean_latency_ms": mean([r["latency_ms"] for r in rs])}
               for s, rs in by_sys.items()}
    per_lang = {s: {l: {m: mean([r[m] for r in rs if r["lang"] == l]) for m in ("NDCG@10", "P@10", "MRR", "ConstraintSat@10")} for l in LANGS}
                for s, rs in by_sys.items()}
    sig = {}
    if "MOSAIC" in by_sys:
        key = lambda r: (r["need"], r["lang"])
        mos = {key(r): r for r in by_sys["MOSAIC"]}
        for s, rs in by_sys.items():
            if s == "MOSAIC":
                continue
            other = {key(r): r for r in rs}
            common = sorted(set(mos) & set(other))
            for m in ("NDCG@10", "P@10"):
                a = [mos[k][m] for k in common]
                b = [other[k][m] for k in common]
                sig.setdefault(s, {})[m] = {"delta": round(statistics.fmean(a) - statistics.fmean(b), 4), "p_value": round(paired_permutation_test(a, b), 4),
                                             "n": len(common)}
    lang_acc = {}
    for l in LANGS:
        rs = [r for r in by_sys.get("MOSAIC", []) if r["lang"] == l]
        if rs:
            lang_acc[l] = round(sum(1 for r in rs if r["detected_lang"] == l) / len(rs), 3)
    errors = sum(1 for r in rows if "error" in r)
    return {"overall": overall, "per_language": per_lang, "significance_vs_mosaic": sig, "language_id_accuracy": lang_acc, "errors": errors}


def to_markdown(summary: dict, meta: dict) -> str:
    L = [f"# Offline evaluation report\n", f"_Generated {meta['generated']} from {meta['queries']} queries "
         f"({meta['needs']} information needs × {len(LANGS)} languages) against a live stack with a {meta['catalogue_size']}-product catalogue "
         f"(synthetic, Amazon-2023 schema). Relevance judged against hidden ground truth (see evaluation/judge.py). All numbers are from this run._\n"]
    head = "| System | " + " | ".join(METRICS) + " | mean latency (ms) |"
    L += ["## Overall", head, "|" + "---|" * (len(METRICS) + 2)]
    for s, m in summary["overall"].items():
        L.append(f"| {s} | " + " | ".join(f"{m[k]:.3f}" if m[k] is not None else "-" for k in METRICS) + f" | {m['mean_latency_ms']:.0f} |")
    L += ["\n## NDCG@10 by language", "| System | " + " | ".join(LANGS) + " |", "|" + "---|" * (len(LANGS) + 1)]
    for s, d in summary["per_language"].items():
        L.append(f"| {s} | " + " | ".join(f"{d[l]['NDCG@10']:.3f}" if d[l]["NDCG@10"] is not None else "-" for l in LANGS) + " |")
    L += ["\n## Constraint satisfaction@10 by language", "| System | " + " | ".join(LANGS) + " |", "|" + "---|" * (len(LANGS) + 1)]
    for s, d in summary["per_language"].items():
        L.append(f"| {s} | " + " | ".join(f"{d[l]['ConstraintSat@10']:.3f}" if d[l]["ConstraintSat@10"] is not None else "-" for l in LANGS) + " |")
    L += ["\n## MOSAIC vs others (paired permutation test, 10k resamples)", "| Compared system | ΔNDCG@10 | p | ΔP@10 | p |", "|---|---|---|---|---|"]
    for s, d in summary["significance_vs_mosaic"].items():
        L.append(f"| {s} | {d['NDCG@10']['delta']:+.3f} | {d['NDCG@10']['p_value']:.4f} | {d['P@10']['delta']:+.3f} | {d['P@10']['p_value']:.4f} |")
    L += ["\n## Language identification accuracy (MOSAIC run)", "| " + " | ".join(LANGS) + " |", "|" + "---|" * len(LANGS),
          "| " + " | ".join(str(summary["language_id_accuracy"].get(l, "-")) for l in LANGS) + " |"]
    L.append(f"\nRequest errors: {summary['errors']}")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--needs", default="evaluation/queries/needs.jsonl")
    ap.add_argument("--truth", default="data/ground_truth.jsonl")
    ap.add_argument("--out", default="evaluation/reports")
    ap.add_argument("--systems", default="all", help="comma-separated subset of: " + ",".join(SYSTEMS))
    ap.add_argument("--concurrency", type=int, default=4)
    a = ap.parse_args()
    needs = [json.loads(l) for l in open(a.needs) if l.strip()]
    truth = load_truth(a.truth)
    systems = SYSTEMS if a.systems == "all" else {k: SYSTEMS[k] for k in a.systems.split(",")}
    st = httpx.get(f"{a.api}/system/status", timeout=10).json()
    n_cat = st.get("catalogue_stats", {}).get("products")
    truth = {k: v for k, v in truth.items()}  # judge covers whole truth file; products not in the live index can't be retrieved anyway
    t0 = time.time()
    res = asyncio.run(run(a.api, needs, truth, systems, a.concurrency))
    summary = summarise(res["rows"])
    meta = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "queries": len(needs) * len(LANGS), "needs": len(needs), "catalogue_size": n_cat,
            "wall_seconds": round(time.time() - t0, 1), "systems": systems, "relevant_per_need": res["n_relevant"]}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "offline_eval.json").write_text(json.dumps({"meta": meta, "summary": summary, "rows": res["rows"]}, indent=1, ensure_ascii=False))
    (out / "offline_eval.md").write_text(to_markdown(summary, meta))
    print(to_markdown(summary, meta))
    print(f"wall time {meta['wall_seconds']}s; wrote {out/'offline_eval.md'}")


if __name__ == "__main__":
    main()
