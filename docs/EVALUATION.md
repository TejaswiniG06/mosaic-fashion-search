# Evaluation methodology & results

All numbers below were produced by the scripts in `evaluation/` against the running stack; raw per-query rows are in
`evaluation/reports/*.json`, rendered tables in `evaluation/reports/*.md`. Nothing is hand-entered.

## 1. Relevance evaluation (`make eval` → `evaluation/run_offline_eval.py`)
**Queries.** 30 information needs × 4 languages = **120 queries** (`evaluation/queries/needs.jsonl`): English, Tamil script,
Tanglish (romanised Tamil code-mixed with English), Hindi (Devanagari). Needs cover: climate/destination reasoning (Chennai,
Goa, Manali, Ooty, Delhi winter, Hyderabad summer, Mumbai monsoon), occasions (wedding, sangeet, Diwali, Pongal, office,
interview, gym, beach), explicit budgets / sizes / gender, colours / patterns, sustainability, and vague category-free needs
("an outfit for the beach").

**Judgments.** Each need has machine-checkable `req` (category, gender, max price, size; in-stock always) and `pref`
(material, occasion, climate, colour, pattern, comfort, sustainability). The judge (`evaluation/judge.py`) grades every
product against the **hidden ground truth** written by the catalogue generator, which no service can read:
0 = a requirement fails; 1 = <50 % of preferences; 2 = ≥50 %; 3 = all. Binary relevance = grade ≥ 2; NDCG uses 2^g − 1.
Because the whole catalogue is judged, recall is exact.

**Systems.** BM25 · Dense (e5) · Hybrid (RRF) · MOSAIC, plus ablations: fixed vs adaptive weights, text-only vs text+image,
dense vs hybrid candidate generation, without vs with intent decomposition, without context signals, and a constraint-aware
baseline *Hybrid+filters* (intent-derived hard filters + fixed semantic/lexical fusion, no image, no context).
Significance: two-sided paired randomisation test (10k resamples) over the 120 queries.

### Results — 5,000-product catalogue
See `evaluation/reports/offline_eval.md` for the full tables (generated). Summary:

| System | P@5 | P@10 | R@10 | NDCG@10 | MRR | MAP@10 | HitRate@10 | ConstraintSat@10 |
|---|---|---|---|---|---|---|---|---|
| BM25 | 0.342 | 0.346 | 0.047 | 0.306 | 0.395 | 0.309 | 0.467 | 0.361 |
| Dense | 0.403 | 0.378 | 0.045 | 0.331 | 0.553 | 0.298 | 0.750 | 0.438 |
| Hybrid | 0.498 | 0.471 | 0.059 | 0.412 | 0.588 | 0.397 | 0.783 | 0.521 |
| Hybrid+filters | 0.960 | 0.932 | 0.167 | 0.840 | 0.971 | 0.917 | 0.983 | 0.983 |
| **MOSAIC** | **0.965** | **0.954** | **0.174** | **0.916** | 0.968 | **0.943** | 0.983 | 0.983 |

NDCG@10 by language:

| System | en | ta | tanglish | hi |
|---|---|---|---|---|
| BM25 | 0.691 | 0.000 | 0.533 | 0.000 |
| Dense | 0.556 | 0.209 | 0.272 | 0.288 |
| Hybrid | 0.677 | 0.209 | 0.473 | 0.288 |
| MOSAIC | 0.947 | 0.877 | 0.943 | 0.896 |

Ablations (Δ = MOSAIC − variant, NDCG@10, paired permutation p):

| question | variant | NDCG@10 | Δ | p |
|---|---|---|---|---|
| fixed vs adaptive ranking | fixed weights | 0.903 | +0.013 | 0.0001 |
| text vs text+image | text only | 0.894 | +0.022 | 0.0002 |
| dense vs hybrid candidates | dense candidates | 0.901 | +0.014 | 0.0002 |
| without vs with intent decomposition | no intent | 0.384 | +0.532 | 0.0001 |
| without context signals | no context | 0.830 | +0.086 | 0.0001 |
| reranking on top of filters | Hybrid+filters | 0.840 | +0.076 | 0.0001 |

Language identification accuracy on the 120 queries: en 1.00 · ta 1.00 · tanglish 1.00 · hi 1.00.

### Reading the results honestly
* **The biggest jump comes from intent decomposition + hard constraints.** Baselines can't turn "under 2000", "size L"
  or "dress" into filters, so 48–64 % of their top-10 items break a stated constraint. *Hybrid+filters* isolates this:
  0.412 → 0.840 NDCG@10.
* **Context-adaptive reranking adds on top of that**: 0.840 → 0.916 (+0.076, p=0.0001). Adaptive weights beat a fixed
  weight vector (+0.013 NDCG@10, significant, but small), and the image signal adds +0.022. P@10 differences for these
  two ablations are not significant (p=0.21 and p=0.13). The gain shows up in *ordering* (NDCG), not in which items make the top 10.
* **Multilingual**: BM25 scores 0 on Tamil- and Hindi-script queries because the catalogue is English. Dense e5-small
  only reaches 0.21–0.29 on them. Decomposing the query into canonical slots lifts Tamil to 0.877 and Hindi to 0.896.
* **Failure analysis** (lowest-NDCG MOSAIC queries in `offline_eval.json`):
  * *N26 Tamil/Hindi "formal shoes" → NDCG 0.* The rule lexicon maps "ஷூ"/"जूते" (shoes) to *sneakers*, and the
    explicit-category hard filter then excludes every formal shoe. This is the main risk of hard category filters on
    imperfect parsing. With an LLM configured, this is the kind of case the LLM path is there to fix. A production safeguard
    is to relax the category filter when parser confidence is low (listed under limitations).
  * *N22 Tamil/Hindi "sangeet"* is not in the occasion lexicon, so the occasion signal is lost (0.49–0.62).
  * *N25 hoodie / N08 Tamil eco t-shirt*: few relevant items, and "ஆர்கானிக்" (organic) is not in the lexicon.
  These were deliberately **not** patched into the lexicon after seeing them. Doing so would tune on the test set.

### Validity caveats (important)
1. **Synthetic catalogue.** The sandbox could not reach HuggingFace or the Amazon image CDN, so labels come from a
   generator, not from humans. Product text mentions attributes incompletely and noisily (occasion stated in ~70 % of
   items, season in ~55 %, material missing from details in ~15 %, ~7 % without images). It is still cleaner than real Amazon data.
2. **Shared vocabulary.** The judge, the generator and the rule parser share the canonical attribute vocabulary.
   Structured systems therefore have an advantage that real data would shrink. Treat absolute values as an upper bound;
   the **relative** ordering and ablation deltas are the meaningful results.
3. **Rendered images.** Images are procedural flat-lays (colour, pattern, silhouette), not photos. CLIP colour/pattern
   discrimination on them is verified (`tests/test_encoders.py`), but the visual gain on real photos may differ.
4. The weights were set a priori, with one change during development (colour/pattern visual boost, made on a non-eval
   query). They were not tuned on the evaluation queries.

## 2. System health (`make load` → `evaluation/load_test.py`)
Closed-loop virtual users draw random queries from the 120-query set. The response cache is off unless stated. Every
response carries server-side component timings, which are aggregated into P50/P95/P99. Host: 2 vCPU / 7 GB with all
services and datastores co-located. Full tables: `evaluation/reports/load_test_5k.md`, `load_test_5k_cached.md`.

| mode | concurrency | throughput (req/s) | P50 ms | P95 ms | P99 ms | error rate |
|---|---|---|---|---|---|---|
| MOSAIC | 1 | 12.7 | 80.9 | 110.9 | 129.7 | 0 |
| MOSAIC | 4 | 19.5 | 205.3 | 285.5 | 326.6 | 0 |
| MOSAIC | 8 | 21.9 | 365.9 | 503.7 | 615.0 | 0 |
| MOSAIC | 16 | 21.2 | 771.8 | 1031.5 | 1097.8 | 0 |
| Hybrid | 1 | 18.6 | 52.2 | 63.1 | 81.3 | 0 |
| Hybrid | 4 | 29.2 | 132.3 | 185.8 | 234.3 | 0 |
| BM25 | 4 | 113.3 | 33.6 | 61.3 | 80.2 | 0 |
| MOSAIC, response cache on | 8 | 245.6 | 11.5 | 194.4 | 451.3 | 0 |

The system saturates at about 20 MOSAIC req/s on 2 vCPU. Past that point, latency grows linearly with concurrency
(queueing), with no errors. In the per-component breakdown, Qdrant ANN and the embedding/intent hops dominate. Query
embeddings repeat across the 120-query pool, so the embedding cache is warm in this test.

## 3. Freshness (time-to-searchable)
`POST /catalogue/time-to-searchable` adds a probe product and polls search until it appears through each path:
**≈200 ms via BM25 and ≈250 ms via dense/Qdrant at 5K products** (write ack ≈12 ms). Values at larger sizes are in the
scale report.

## 4. Scale (`make scale` → `evaluation/scale_test.py`)
The live catalogue grew 5K → 20K → 50K → 100K through the normal ADD path (outbox → stream → incremental indexing).
Every number was measured at that size on the same 2 vCPU host. Full report: `evaluation/reports/scale_test.md`.

| size | ingest rate (products/s) | time-to-searchable lexical / dense (ms) | MOSAIC P50 / P95 (ms, 1 user) | Hybrid P50 (ms) | BM25 component P50 (ms) | MOSAIC NDCG@10 | Hybrid NDCG@10 | retrieval RSS / Qdrant RSS (MB) |
|---|---|---|---|---|---|---|---|---|
| 5,000 | – (initial load ≈ 46) | 200 / 249 | 77 / 109 | 52 | 2.8 | 0.916 | 0.412 | 223 / 124 |
| 20,000 | 42.2 | 260 / 319 | 109 / 135 | 59 | 11.4 | 0.921 | 0.407 | 322 / 208 |
| 50,000 | 39.3 | 297 / 191 | 132 / 176 | 57 | 28.2 | 0.948 | 0.416 | 569 / 342 |
| 100,000 | 27.4 | 538 / 396 | 176 / 248 | 61 | 65.0 | 0.951 | 0.418 | 977 / 563 |

Findings:
* **Relevance holds at scale**: MOSAIC NDCG@10 stays at 0.92–0.95 from 5K to 100K, and constraint satisfaction stays at
  0.983. More candidates per need make it slightly easier to fill the top 10 with relevant items.
* **Qdrant ANN latency is nearly flat** (P50 39 → 48 ms with filters, 100 candidates, payload + vectors), as expected for HNSW.
* **The in-process Python BM25 is the scaling bottleneck**: 2.8 ms → 65 ms (linear in posting-list length). MOSAIC's English
  normalisation adds common tokens, which makes posting lists longer. This is measured evidence for the planned move of the
  lexical channel to OpenSearch or Qdrant sparse vectors (docs/SCALING.md).
* Ingestion is CPU-bound by e5 passage encoding on 2 shared vCPUs (27–42 products/s). It scales horizontally with indexer
  and embedding replicas, or with a GPU.
* Freshness stays sub-second at 100K (0.54 s lexical / 0.40 s dense).
* At 100K, 11.5 % of products have no image vector. About 7 % have no image by design; the rest reference procedural
  renders that were never generated for colour/pattern combinations new in the scale step. They are indexed text-only
  (image fallback), which exercises the fallback at scale.

## 5. Resilience (`make faults` → `evaluation/fault_injection.py`)
Each drill breaks one dependency of the live 100K stack, sends real multilingual queries, then restores it
(`evaluation/reports/fault_injection.md`):

| drill | queries answered (200 + results) | HTTP errors | degraded flag returned to client | recovered |
|---|---|---|---|---|
| all healthy | 100 % | 0 % | – | – |
| LLM endpoint unreachable | 100 % (rules parser) | 0 % | `llm unavailable … used deterministic parser` | – |
| intent service killed | 100 % | 0 % | `intent_unavailable` | 100 % |
| embedding service killed | 100 % (BM25 on English normalisation) | 0 % | `embedding_*_unavailable`, `no_query_vector` | 100 % |
| Qdrant killed | 100 % (BM25-only) | 0 % | `vector_search_unavailable` | 100 % |
| ranking service killed | 100 % (retrieval order) | 0 % | `ranking_unavailable` | 100 % |
| product with unreachable image URL | indexed and found | 0 % | `has_image=false` (text + attribute appearance) | – |

Circuit breakers fail fast while a dependency is down. They recover through half-open trials about 15 s after it returns.
