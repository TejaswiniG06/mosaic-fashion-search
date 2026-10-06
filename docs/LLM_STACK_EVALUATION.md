# Provider-backed full-stack evaluation

This evaluation compares **MOSAIC with rules only** against **MOSAIC with Groq +
rules** on the same 5,000-product synthetic catalogue and 120 queries: 30 needs
in English, Tamil, Tanglish and Hindi. Both use the real gateway, embedding,
retrieval, ranking and catalogue/indexing services, with Redis and Qdrant.

**Finding:** Groq worked for all 120 queries, but NDCG@10 was 0.917 versus 0.915
with rules, a non-significant difference of +0.0016. Fresh-call P95 latency rose
from 305 ms to 3.27 s. With cached intents, Groq reached 24.64 searches/s at
474 ms P95 with eight concurrent users and no additional provider calls.
This supports keeping Groq optional; it does not establish a general relevance gain.

The tested deployment is native Windows with the supported SQLite catalogue
backend, CPU e5/CLIP ONNX models, 12 logical CPUs and approximately 15.4 GiB RAM.
It does not validate the PostgreSQL/Docker deployment. All 90 non-integration
tests and seven live API integration tests passed before the benchmark, with
no model-dependent tests skipped. The catalogue was fully indexed before querying.
Of the 5,000 products, 4,668 had CLIP image vectors; the rest used text and attributes.

## Results and evidence

Read the [generated results](../evaluation/reports/llm_stack/summary.md) for relevance,
language breakdowns, fresh-call latency, warm-intent throughput and explanation samples.
The adjacent JSON reports retain ranking IDs, metrics, parser/fallback traces,
component timings, environment versions and source/dataset/model hashes.
The [offline audit](../evaluation/reports/llm_stack/analysis.json) confirms hard
constraint preservation in all 120 pairs and 2,315 error-free warm searches.
It also groups each need's four translations into one permutation block:
30 needs, two-sided p=0.7988. The original query-level p=0.8011 is retained in
the generated report. Neither analysis indicates a significant overall gain.

There are individual gains and losses: Tamil N08 improved by 0.454 NDCG, while
Hindi N06 declined by 0.203. These examples illustrate variability, not independent
holdout evidence. Rule-category mistakes still require parser fixes; the LLM cannot
replace an explicit hard category.

## How to interpret the comparison

- **Relevance:** each query runs with the same retrieval and ranking settings; only
  `use_llm` changes. Rules still own hard budget, size, gender and explicit categories.
  The paired comparison therefore measures the LLM's contribution to semantic slots
  and query rewriting, including any fallback observed in this run.
- **Fresh-call latency:** response caching is disabled, and the exact intent cache
  entry is removed before each Groq query. Provider calls are paced eight seconds
  apart for the observed account quota. That waiting time is excluded from request
  latency; throughput of uncached Groq calls is not stress-tested.
- **Warm throughput:** both systems use the same workload drawn from accepted,
  cached LLM intents. Tests use 1, 4 and 8 concurrent users, 20 seconds per condition,
  with response caching off. Intent-service metrics show whether additional provider
  attempts occurred. These are short local capacity measurements.
- **Explanations:** disabled during the comparisons to isolate intent behavior.
  Three separate end-to-end samples request a top-one explanation with the optional
  explanation feature enabled.

The synthetic labels share the system's canonical vocabulary. The absolute scores
do not establish quality on real product photos or real shopper judgments. Earlier
tables used different hardware and configuration, so they are not a before/after
latency comparison. Provider reliability, broader adversarial coverage, long-running
load and independent real-data relevance evaluation remain future work.

## Reproduce

Start the real stack, configure Groq in local `.env`, index the catalogue completely,
and enable `LLM_EXPLANATIONS=true` in the ranking service for the explanation samples.
For native Windows, use `CATALOGUE_DB=sqlite`; launcher setup preserves an existing
`.env`, so it will not change an earlier PostgreSQL setting automatically.
Use `RATE_LIMIT_RPS=0` only for the local benchmark. Then run:

```bash
PYTHONPATH=libs:. python -m evaluation.evaluate_llm_stack --pace 8 --duration 20
```

On PowerShell, set `$env:PYTHONPATH="libs;."` before the Python command. The runner
uses Redis protocol 2 for compatibility with portable Windows Redis. It deletes
only each tested query's intent-cache entry, and overwrites its own report files.
Use `--phase relevance`, `--phase load` or `--phase explanations` to run individual
stages. The workload and waiting period must be appropriate for your provider quota.
Keep API keys in the ignored local `.env`; report writing checks for the configured key.

Run `python -m evaluation.analyse_llm_stack` to reproduce the offline audit and
need-clustered significance calculation without further API calls.
