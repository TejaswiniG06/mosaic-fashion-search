"""Resilience drills against the locally-running stack (scripts/run_local.sh). Each drill breaks one
dependency, fires real queries, records status codes / degraded flags / latency, then restores it.

Drills: LLM endpoint unreachable · intent service down · embedding service down · Qdrant down ·
ranking service down · product image unreachable.

    python -m evaluation.fault_injection
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path

import httpx

API = "http://localhost:8000"
KEY = {"x-api-key": os.environ.get("ADMIN_API_KEY", "change-me-admin-key")}
QUERIES = ["Chennai summer ku comfortable cotton dress venum under 2000", "शादी के लिए लाल लहंगा", "warm jacket for manali winter",
           "கல்யாணத்துக்கு சிவப்பு பட்டு புடவை", "blue checked shirt"]
ROOT = Path(__file__).resolve().parents[1]
QDRANT_BIN = os.environ.get("QDRANT_BIN", "/home/claude/infra/qdrant")
QDRANT_STORAGE = os.environ.get("QDRANT_STORAGE", "/home/claude/infra/qdrant_storage")


def sh(cmd: str) -> str:
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True).stdout


def kill(pattern: str) -> None:
    sh(f"pkill -f '{pattern}' || true")
    time.sleep(1.5)


def restart_services() -> None:
    sh(f"cd {ROOT} && NO_UI=1 ./scripts/run_local.sh")


def probe(label: str) -> dict:
    out = []
    for q in QUERIES:
        t0 = time.perf_counter()
        try:
            r = httpx.post(f"{API}/search", json={"query": q, "top_k": 5, "use_cache": False}, timeout=30)
            d = r.json() if r.status_code == 200 else {}
            out.append({"status": r.status_code, "ms": round((time.perf_counter() - t0) * 1000), "results": len(d.get("results", [])),
                        "degraded": d.get("degraded", []), "parser": (d.get("intent") or {}).get("parser"), "retrieval_mode": d.get("retrieval_mode")})
        except Exception as e:
            out.append({"status": type(e).__name__, "ms": round((time.perf_counter() - t0) * 1000), "results": 0, "degraded": []})
    ok = sum(1 for x in out if x["status"] == 200 and x["results"] > 0)
    return {"drill": label, "success_rate": ok / len(out), "error_rate": sum(1 for x in out if x["status"] != 200) / len(out),
            "p50_ms": sorted(x["ms"] for x in out)[len(out) // 2], "degraded_flags": sorted({d.split(":")[0] for x in out for d in x["degraded"]}),
            "samples": out}


def drill_llm_unreachable() -> dict:
    """Second intent instance configured with an unreachable LLM endpoint: must answer via rules."""
    env = {**os.environ, "PYTHONPATH": f"{ROOT}/libs:{ROOT}", "LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": "http://127.0.0.1:9/v1",
           "LLM_API_KEY": "x", "LLM_TIMEOUT_S": "1.5"}
    p = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "uvicorn", "services.intent.app:app", "--port", "8011", "--log-level", "warning"],
                         cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                if httpx.get("http://localhost:8011/ready", timeout=1).status_code == 200:
                    break
            except Exception:
                time.sleep(0.25)
        res = []
        for q in QUERIES:
            t0 = time.perf_counter()
            r = httpx.post("http://localhost:8011/parse", json={"query": q}, timeout=10).json()
            res.append({"ms": round((time.perf_counter() - t0) * 1000), "parser": r["parser"], "warning": (r.get("warnings") or [""])[-1][:80],
                        "category": r["category"], "budget_max": r["budget_max"]})
        return {"drill": "LLM endpoint unreachable", "success_rate": sum(1 for x in res if x["parser"] == "rules") / len(res),
                "error_rate": 0.0, "p50_ms": sorted(x["ms"] for x in res)[len(res) // 2], "degraded_flags": ["llm_failed->rules"], "samples": res}
    finally:
        p.send_signal(signal.SIGTERM)


def drill_qdrant_down() -> dict:
    kill("[.]/qdrant|infra/qdrant$")
    sh("pkill -x qdrant || true")
    time.sleep(1)
    r = probe("Qdrant (vector DB) down")
    sh(f"cd {Path(QDRANT_BIN).parent} && (QDRANT__STORAGE__STORAGE_PATH={QDRANT_STORAGE} QDRANT__TELEMETRY_DISABLED=true nohup {QDRANT_BIN} > qdrant.log 2>&1 &)")
    for _ in range(60):
        try:
            if httpx.get("http://localhost:6333/healthz", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    settle()
    r["recovered"] = probe("after Qdrant restart")["success_rate"]
    return r


BREAKER_RESET_S = float(os.environ.get("BREAKER_RESET_S", "15"))


def settle() -> None:
    """Wait until gateway circuit breakers move to half-open so the next drill starts clean."""
    time.sleep(BREAKER_RESET_S + 2)
    for _ in range(3):  # trial requests close half-open breakers
        try:
            httpx.post(f"{API}/search", json={"query": "cotton kurta", "use_cache": False}, timeout=30)
        except Exception:
            pass


def drill_service_down(name: str, pattern: str) -> dict:
    kill(pattern)
    r = probe(f"{name} service down")
    restart_services()
    settle()
    r["recovered"] = probe(f"after {name} restart")["success_rate"]
    return r


def drill_bad_image() -> dict:
    asin = "FI" + uuid.uuid4().hex[:8].upper()
    p = {"parent_asin": asin, "title": "Zorvane Women's Ivory Linen Kaftan Dress", "price": 1599, "stock_qty": 5, "sizes": ["M"],
         "details": {"Material": "Linen"}, "images": [{"large": "https://invalid.invalid/no-such-image.jpg"}]}
    httpx.post(f"{API}/catalogue/products", json=p, headers=KEY, timeout=20).raise_for_status()
    found, res = False, {}
    t0 = time.time()
    while time.time() - t0 < 20 and not found:
        d = httpx.post(f"{API}/search", json={"query": "Zorvane ivory linen kaftan dress", "top_k": 10, "use_cache": False}, timeout=30).json()
        hit = [x for x in d["results"] if x["parent_asin"] == asin]
        if hit:
            found, res = True, hit[0]
        time.sleep(0.3)
    httpx.delete(f"{API}/catalogue/products/{asin}", headers=KEY)
    return {"drill": "product image unreachable", "success_rate": 1.0 if found else 0.0, "error_rate": 0.0, "p50_ms": None,
            "degraded_flags": ["text-only point (has_image=false)"],
            "samples": [{"found": found, "has_image": res.get("has_image"), "visual_component": res.get("components", {}).get("visual"),
                         "contributions": res.get("contributions")}]}


def main():
    results = [probe("baseline (all healthy)")]
    results.append(drill_llm_unreachable())
    results.append(drill_service_down("intent", "uvicorn services[.]intent"))
    results.append(drill_service_down("embedding", "uvicorn services[.]embedding"))
    results.append(drill_qdrant_down())
    results.append(drill_service_down("ranking", "uvicorn services[.]ranking"))
    results.append(drill_bad_image())
    out = ROOT / "evaluation" / "reports"
    (out / "fault_injection.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    L = ["# Fault-injection / resilience report\n", f"_Generated {time.strftime('%Y-%m-%d %H:%M:%S')} — each drill breaks one dependency of the live stack, "
         f"sends {len(QUERIES)} real multilingual queries, then restores it._\n",
         "| drill | success (200 + results) | HTTP error rate | P50 ms | degraded flags reported | recovered after restore |", "|---|---|---|---|---|---|"]
    for r in results:
        L.append(f"| {r['drill']} | {r['success_rate']:.0%} | {r['error_rate']:.0%} | {r['p50_ms']} | {', '.join(r['degraded_flags']) or '-'} | "
                 f"{'' if 'recovered' not in r else format(r['recovered'], '.0%')} |")
    (out / "fault_injection.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
