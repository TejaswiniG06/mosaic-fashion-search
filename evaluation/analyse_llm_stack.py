"""Offline audit and need-clustered significance for the saved full-stack run.

PYTHONPATH=libs:. python -m evaluation.analyse_llm_stack
No provider calls or credentials required. Translation pairs share one need.
"""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics

from evaluation.metrics import paired_permutation_test


def main():
    root = Path(__file__).resolve().parents[1]
    folder = root / "evaluation/reports/llm_stack"
    report = json.loads((folder/"relevance.json").read_text(encoding="utf-8"))
    pairs = defaultdict(dict)
    for row in report["rows"]:
        key = (row["need"], row["lang"])
        assert row["system"] not in pairs[key], "Duplicate query/system row"
        pairs[key][row["system"]] = row
    assert len(pairs) == 120 and len(report["rows"]) == 240
    clusters = defaultdict(list)
    deltas = []
    preserved = 0
    for (need, language), systems in pairs.items():
        rules, llm = systems["MOSAIC-rules"], systems["MOSAIC-Groq"]
        assert "error" not in rules and "error" not in llm
        assert llm["intent"]["parser"] == "llm+rules"
        a, b = llm["intent"], rules["intent"]
        fields = ["budget_min", "budget_max", "size", "gender", "category_explicit"]
        assert all(a[field] == b[field] for field in fields)
        assert not b["category_explicit"] or a["category"] == b["category"]
        preserved += 1
        delta = llm["NDCG@10"]-rules["NDCG@10"]
        clusters[need].append(delta)
        deltas.append({"need": need, "language": language, "query": llm["query"], "delta_ndcg": delta})
    assert len(clusters) == 30 and all(len(values)==4 for values in clusters.values())
    block_means = [statistics.fmean(values) for values in clusters.values()]
    load = json.loads((folder/"load.json").read_text(encoding="utf-8"))
    assert len(load["results"]) == 6
    assert all(row["error_rate"] == 0 and row["degraded_responses"] == 0
               and row["llm_fallbacks"] == 0 and row["provider_attempts_during_load"] == 0 for row in load["results"])
    output = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "analysis_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "summary_renderer_source_sha256": hashlib.sha256((root/"evaluation/evaluate_llm_stack.py").read_bytes()).hexdigest(),
              "relevance_report_sha256": hashlib.sha256((folder/"relevance.json").read_bytes()).hexdigest(),
              "audited_pairs": 120, "hard_constraints_preserved": preserved,
              "warm_requests_without_errors_or_provider_attempts": sum(row["requests"] for row in load["results"]),
              "need_clustered_ndcg": {"n_needs": 30, "translations_per_need": 4,
                                       "mean_delta_groq_minus_rules": statistics.fmean(block_means),
                                       "two_sided_permutation_p": paired_permutation_test(block_means, [0]*len(block_means))},
              "largest_gains": sorted(deltas, key=lambda row: row["delta_ndcg"], reverse=True)[:5],
              "largest_losses": sorted(deltas, key=lambda row: row["delta_ndcg"])[:5],
              "scope": "Offline consistency audit. Permutations flip mean differences across 30 needs to keep their four translations together. No independent human relevance judgments."}
    (folder/"analysis.json").write_text(json.dumps(output,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    from evaluation.evaluate_llm_stack import write_summary
    write_summary(folder)
    print(json.dumps({key:output[key] for key in ["audited_pairs", "hard_constraints_preserved", "warm_requests_without_errors_or_provider_attempts", "need_clustered_ndcg"]}))


if __name__ == "__main__":
    main()
