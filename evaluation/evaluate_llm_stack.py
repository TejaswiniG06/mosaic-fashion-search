"""Paired full-stack rules/Groq relevance, cold-call latency and warm-intent load.

Requires the running native or Docker stack and a completely indexed catalogue.
PYTHONPATH=libs:. python -m evaluation.evaluate_llm_stack --phase all
Synthetic evaluation only. API calls consume the configured provider's quota.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import platform
import statistics
import subprocess
import time
from importlib.metadata import version
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
import redis.asyncio as redis

from evaluation.judge import all_grades, load_truth, requirements_ok
from evaluation.load_test import level, pct
from evaluation.metrics import all_metrics, paired_permutation_test
from mosaic_common.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


async def provider_attempts(client, settings):
    response = await client.get(settings.intent_url.rstrip("/") + "/metrics")
    response.raise_for_status()
    for line in response.text.splitlines():
        if line.startswith("mosaic_component_seconds_count{") and 'component="llm"' in line and 'service="intent"' in line:
            return int(float(line.rsplit(" ", 1)[1]))
    return 0


def save(path, report, settings):
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if settings.llm_api_key and settings.llm_api_key.get_secret_value() in text:
        raise RuntimeError("Credential detected: report was not written.")
    path.write_text(text, encoding="utf-8")


def host_info():
    info = {"platform": platform.platform(), "logical_cpus": os.cpu_count()}
    if os.name == "nt":
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ["total", "available", "page_total", "page_available",
                                                       "virtual_total", "virtual_available", "virtual_extended"]]
        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            info["ram_gib"] = round(memory.total / 2**30, 2)
    return info


def write_summary(output):
    path = output / "relevance.json"
    if not path.exists():
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    if "summary" not in report:
        return
    meta, summary = report["meta"], report["summary"]
    lines = ["# Full-stack rules vs Groq evaluation\n",
             f"Generated {meta['generated_at']}. {meta['catalogue_size']} synthetic products; 120 queries across English, Tamil, Tanglish and Hindi.",
             f"Deployment: {meta['deployment']}. Host: {meta['host']}. Model: `{meta['model']}`.",
             "Real gateway, intent, embedding, retrieval, ranking, catalogue, indexer, Redis and Qdrant; no mocked services.",
             "\n## Relevance", "| System | P@10 | NDCG@10 | Constraints satisfied | HTTP errors | LLM fallbacks |",
             "|---|---:|---:|---:|---:|---:|"]
    for name in ["MOSAIC-rules", "MOSAIC-Groq"]:
        row = summary[name]
        m = row["metrics"]
        lines.append(f"| {name} | {m['P@10']:.3f} | {m['NDCG@10']:.3f} | {m['ConstraintSat@10']:.3f} | {row['http_errors']} | {row['llm_fallbacks']} |")
    paired = summary["paired_ndcg"]
    lines.append(f"\nPaired NDCG difference (Groq minus rules): {paired['delta_groq_minus_rules']:+.4f}; two-sided permutation p={paired['p_value']:.4f}, n={paired['n']}.")
    lines += ["\n### NDCG@10 by language", "| System | en | ta | tanglish | hi |", "|---|---:|---:|---:|---:|"]
    for name in ["MOSAIC-rules", "MOSAIC-Groq"]:
        values = summary[name]["per_language_ndcg"]
        lines.append(f"| {name} | " + " | ".join(f"{values[lang]:.3f}" for lang in ["en", "ta", "tanglish", "hi"]) + " |")
    lines += ["\n## Fresh intent end-to-end latency", "| System | P50 ms | P95 ms | Parser counts |", "|---|---:|---:|---|"]
    for name in ["MOSAIC-rules", "MOSAIC-Groq"]:
        row = summary[name]
        lines.append(f"| {name} | {row['latency_ms']['p50']} | {row['latency_ms']['p95']} | {row['parser_counts']} |")
    lines.append(f"\nResponse cache off; the exact LLM intent cache entry was deleted before each Groq request. Requests were spaced {meta['intent_call_spacing_s']} s apart for provider quota; the spacing is excluded from request latency. Embedding cache state varies with the query and is not a cold-encoder benchmark.")
    lines.append(f"Provider intent attempts observed in service metrics: {report['provider_attempts_after']-report['provider_attempts_before']}.")
    load = output / "load.json"
    if load.exists():
        data = json.loads(load.read_text(encoding="utf-8"))
        lines += ["\n## Warm-intent throughput", f"{data['query_count']} accepted LLM intents form the shared workload. Response cache and explanations off.",
                  "| System | Concurrent users | Requests | Req/s | P95 ms | HTTP error rate | Degraded | LLM fallbacks | Provider attempts |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for row in data["results"]:
            lines.append(f"| {row['system']} | {row['concurrency']} | {row['requests']} | {row['throughput_rps']} | {row['latency_ms']['p95']} | {row['error_rate']} | {row['degraded_responses']} | {row['llm_fallbacks']} | {row['provider_attempts_during_load']} |")
    explanation = output / "explanations.json"
    if explanation.exists():
        data = json.loads(explanation.read_text(encoding="utf-8"))
        lines += ["\n## Full-stack explanation samples", "| Language | HTTP status | Explanation source |", "|---|---:|---|"]
        for row in data["cases"]:
            products = (row.get("response") or {}).get("results", [])
            source = products[0]["explanation_source"] if products else "no result"
            lines.append(f"| {row['lang']} | {row['http_status']} | {source} |")
    audit = output / "analysis.json"
    if audit.exists():
        data = json.loads(audit.read_text(encoding="utf-8"))
        clustered = data["need_clustered_ndcg"]
        lines += ["\n## Need-clustered audit",
                  f"Keeping each need's four translations together gives {clustered['n_needs']} permutation blocks: p={clustered['two_sided_permutation_p']:.4f}. This accounts for translation dependence and also finds no significant overall gain.",
                  f"Rule-derived hard constraints were preserved in all {data['hard_constraints_preserved']} audited pairs. The audit is reproduced with `python -m evaluation.analyse_llm_stack`."]
    lines += ["\n## Limits", "Synthetic catalogue and shared canonical vocabulary; these scores are not evidence of real-shopper quality.",
              "Warm throughput measures the local search stack with cached intents; it does not measure uncached Groq capacity. Fresh-call latency includes provider/network behavior and any reported fallback.",
              "Explanations are disabled for the relevance/load comparisons so added explanation calls do not confound the intent comparison. Three separate explanation samples are not a quality benchmark.",
              "The native SQLite run does not validate PostgreSQL/Docker deployment, million-product scale or long-duration uptime. Historical results used different hardware and should not be used as a before/after latency comparison.",
              "\nRaw requests, ranking IDs, metrics, parser/fallback traces, model versions, dataset/source hashes and timings are in the JSON files beside this report."]
    (output/"summary.md").write_text("\n".join(lines)+"\n", encoding="utf-8")


def summarise(rows):
    output = {}
    for name in ["MOSAIC-rules", "MOSAIC-Groq"]:
        selected = [r for r in rows if r["system"] == name]
        ok = [r for r in selected if "error" not in r]
        metrics = ["P@10", "NDCG@10", "ConstraintSat@10", "R@10", "MRR", "MAP@10"]
        output[name] = {
            "queries": len(selected), "http_errors": len(selected)-len(ok),
            "metrics": {m: statistics.fmean(r[m] for r in ok if r[m] is not None) for m in metrics} if ok else {},
            "latency_ms": {"p50": pct([r["latency_ms"] for r in ok], 50), "p95": pct([r["latency_ms"] for r in ok], 95)},
            "parser_counts": dict(Counter(r["intent"]["parser"] for r in ok)),
            "llm_fallbacks": sum(any("llm unavailable" in w for w in r["intent"].get("warnings", [])) for r in ok),
            "degraded_responses": sum(bool(r["degraded"]) for r in ok),
            "per_language_ndcg": {lang: statistics.fmean(r["NDCG@10"] for r in ok if r["lang"] == lang)
                                  for lang in sorted({r["lang"] for r in ok})},
        }
    paired = {}
    for name in output:
        paired[name] = {(r["need"], r["lang"]): r for r in rows if r["system"] == name and "error" not in r}
    common = sorted(set(paired["MOSAIC-rules"]) & set(paired["MOSAIC-Groq"]))
    if common:
        a = [paired["MOSAIC-Groq"][key]["NDCG@10"] for key in common]
        b = [paired["MOSAIC-rules"][key]["NDCG@10"] for key in common]
        output["paired_ndcg"] = {"n": len(common), "delta_groq_minus_rules": statistics.fmean(a)-statistics.fmean(b),
                                  "p_value": paired_permutation_test(a, b)}
    return output


async def main(args):
    settings = Settings()
    output = ROOT / args.out
    output.mkdir(parents=True, exist_ok=True)
    needs = [json.loads(line) for line in (ROOT / "evaluation/queries/needs.jsonl").read_text(encoding="utf-8").splitlines()]
    truth = load_truth(ROOT / "data/ground_truth.jsonl")
    async with httpx.AsyncClient(base_url=args.api, timeout=45) as client:
        status = (await client.get("/system/status")).json()
        if not all(status.get("ready", {}).values()):
            raise RuntimeError("All query services must be ready before evaluating.")
        catalogue_size = status["catalogue_stats"]["products"]
        index_size = status["retrieval_stats"]["qdrant_points"]
        if catalogue_size != len(truth) or index_size != catalogue_size:
            raise RuntimeError("Catalogue, truth and vector index sizes must match.")
        metadata = {"generated_at": datetime.now(timezone.utc).isoformat(), "api": args.api,
                    "base_commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
                    "host": host_info(),
                    "catalogue_size": catalogue_size, "provider": settings.llm_provider, "model": settings.llm_model,
                    "deployment": args.deployment, "intent_call_spacing_s": args.pace,
                    "response_cache": False, "explanations_in_relevance_and_load": False,
                    "status": status, "source_sha256": {name: digest(ROOT/name) for name in [
                        "evaluation/evaluate_llm_stack.py", "evaluation/load_test.py", "services/intent/llm.py"]},
                    "dataset_sha256": {name: digest(ROOT/name) for name in [
                        "data/catalogue.jsonl", "data/ground_truth.jsonl", "evaluation/queries/needs.jsonl"]},
                    "runtime_versions": {name: version(name) for name in ["onnxruntime", "tokenizers", "numpy", "qdrant-client", "redis", "fastapi", "httpx"]},
                    "model_sha256": {label: digest(path) for label, path in {
                        "e5": settings.text_model_dir/settings.text_model_file,
                        "clip_text": settings.clip_model_dir/"textual.onnx",
                        "clip_image": settings.clip_model_dir/"visual.onnx"}.items()}}
        path = output / "relevance.json"
        if args.phase in ["all", "relevance"]:
            cache = redis.from_url(settings.redis_url, protocol=2)
            rows = []
            report = {"meta": metadata, "rows": rows}
            report["provider_attempts_before"] = await provider_attempts(client, settings)
            last_call = 0
            grades = {need["id"]: all_grades(truth, need) for need in needs}
            try:
                for need in needs:
                    for lang, query in need["q"].items():
                        for name, use_llm in [("MOSAIC-rules", False), ("MOSAIC-Groq", True)]:
                            if use_llm:
                                await asyncio.sleep(max(0, args.pace-(time.perf_counter()-last_call)))
                                key = "intent:" + hashlib.sha1(f"{settings.llm_model}|{query}".encode()).hexdigest()
                                await cache.delete(key)  # Only this evaluation query, never flush Redis.
                                last_call = time.perf_counter()
                            start = time.perf_counter()
                            response = await client.post("/search", json={"query": query, "mode": "mosaic", "top_k": 10,
                                                                         "use_llm": use_llm, "use_cache": False, "explain": False})
                            elapsed = (time.perf_counter()-start)*1000
                            row = {"system": name, "need": need["id"], "lang": lang, "query": query, "latency_ms": elapsed}
                            if response.status_code != 200:
                                row["error"] = response.status_code
                            else:
                                data = response.json()
                                ranked = [item["parent_asin"] for item in data["results"]]
                                cons = [requirements_ok(truth[a], need["req"]) if a in truth else False for a in ranked]
                                row.update(all_metrics(ranked, grades[need["id"]], cons))
                                row.update(intent=data["intent"], ranked=ranked, degraded=data["degraded"], timings_ms=data["timings_ms"])
                            rows.append(row)
                            save(path, report, settings)
                        print(f"{len(rows)//2}/120 paired queries: {need['id']} {lang}; parser={rows[-1].get('intent',{}).get('parser','error')}", flush=True)
                report["summary"] = summarise(rows)
                report["provider_attempts_after"] = await provider_attempts(client, settings)
                save(path, report, settings)
            finally:
                await cache.aclose()

        if args.phase in ["all", "load"]:
            relevance = json.loads(path.read_text(encoding="utf-8"))
            # Warm workload only includes intents which were genuinely accepted and cached.
            queries = [r["query"] for r in relevance["rows"] if r["system"] == "MOSAIC-Groq"
                       and "error" not in r and r["intent"]["parser"] == "llm+rules"]
            if not queries:
                raise RuntimeError("No verified warm LLM intents available.")
            report = {"meta": metadata, "workload": "warm intent/embedding caches; response cache off; no explanation calls",
                      "query_count": len(queries), "results": []}
            for concurrency in [1, 4, 8]:
                for name, use_llm in [("MOSAIC-rules", False), ("MOSAIC-Groq", True)]:
                    before = await provider_attempts(client, settings)
                    row = await level(args.api, queries, concurrency, args.duration, "mosaic", False,
                                      seed=concurrency, use_llm=use_llm, explain=False)
                    row["system"] = name
                    row["provider_attempts_during_load"] = (await provider_attempts(client, settings))-before
                    report["results"].append(row)
                    save(output/"load.json", report, settings)
                    print(f"{name} warm concurrency {concurrency}: {row['throughput_rps']} req/s, P95 {row['latency_ms']['p95']} ms", flush=True)

        if args.phase in ["all", "explanations"]:
            report = {"meta": metadata, "cases": []}
            for lang in ["en", "tanglish", "ta"]:
                query = needs[0]["q"][lang]
                response = await client.post("/search", json={"query": query, "mode": "mosaic", "top_k": 1,
                                                             "use_llm": True, "use_cache": False, "explain": True})
                report["cases"].append({"lang": lang, "query": query, "http_status": response.status_code,
                                         "response": response.json() if response.status_code==200 else None})
                save(output/"explanations.json", report, settings)
                print(f"Full-stack explanation {lang}: HTTP {response.status_code}", flush=True)
                await asyncio.sleep(args.pace)
        write_summary(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default="evaluation/reports/llm_stack")
    parser.add_argument("--phase", choices=["all", "relevance", "load", "explanations"], default="all")
    parser.add_argument("--pace", type=float, default=10, help="Seconds between fresh provider intent calls")
    parser.add_argument("--duration", type=float, default=20, help="Seconds per warm load condition")
    parser.add_argument("--deployment", default="native Windows / SQLite / Redis / Qdrant")
    asyncio.run(main(parser.parse_args()))
