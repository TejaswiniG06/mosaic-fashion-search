# Full-stack rules vs Groq evaluation

Generated 2026-10-05T16:09:17.509668+00:00. 5000 synthetic products; 120 queries across English, Tamil, Tanglish and Hindi.
Deployment: native Windows / SQLite / Redis / Qdrant. Host: {'platform': 'Windows-11-10.0.26200-SP0', 'logical_cpus': 12, 'ram_gib': 15.44}. Model: `openai/gpt-oss-20b`.
Real gateway, intent, embedding, retrieval, ranking, catalogue, indexer, Redis and Qdrant; no mocked services.

## Relevance
| System | P@10 | NDCG@10 | Constraints satisfied | HTTP errors | LLM fallbacks |
|---|---:|---:|---:|---:|---:|
| MOSAIC-rules | 0.954 | 0.915 | 0.983 | 0 | 0 |
| MOSAIC-Groq | 0.953 | 0.917 | 0.983 | 0 | 0 |

Paired NDCG difference (Groq minus rules): +0.0016; two-sided permutation p=0.8011, n=120.

### NDCG@10 by language
| System | en | ta | tanglish | hi |
|---|---:|---:|---:|---:|
| MOSAIC-rules | 0.949 | 0.876 | 0.945 | 0.890 |
| MOSAIC-Groq | 0.949 | 0.898 | 0.935 | 0.884 |

## Fresh intent end-to-end latency
| System | P50 ms | P95 ms | Parser counts |
|---|---:|---:|---|
| MOSAIC-rules | 148.4 | 304.5 | {'rules': 120} |
| MOSAIC-Groq | 2064.1 | 3266.5 | {'llm+rules': 120} |

Response cache off; the exact LLM intent cache entry was deleted before each Groq request. Requests were spaced 8.0 s apart for provider quota; the spacing is excluded from request latency. Embedding cache state varies with the query and is not a cold-encoder benchmark.
Provider intent attempts observed in service metrics: 120.

## Warm-intent throughput
120 accepted LLM intents form the shared workload. Response cache and explanations off.
| System | Concurrent users | Requests | Req/s | P95 ms | HTTP error rate | Degraded | LLM fallbacks | Provider attempts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MOSAIC-rules | 1 | 166 | 8.26 | 148.6 | 0.0 | 0 | 0 | 0 |
| MOSAIC-Groq | 1 | 163 | 8.13 | 147.6 | 0.0 | 0 | 0 | 0 |
| MOSAIC-rules | 4 | 475 | 23.5 | 227.5 | 0.0 | 0 | 0 | 0 |
| MOSAIC-Groq | 4 | 466 | 23.17 | 226.0 | 0.0 | 0 | 0 | 0 |
| MOSAIC-rules | 8 | 548 | 27.16 | 410.5 | 0.0 | 0 | 0 | 0 |
| MOSAIC-Groq | 8 | 497 | 24.64 | 473.9 | 0.0 | 0 | 0 | 0 |

## Full-stack explanation samples
| Language | HTTP status | Explanation source |
|---|---:|---|
| en | 200 | llm |
| tanglish | 200 | llm |
| ta | 200 | llm |

## Need-clustered audit
Keeping each need's four translations together gives 30 permutation blocks: p=0.7988. This accounts for translation dependence and also finds no significant overall gain.
Rule-derived hard constraints were preserved in all 120 audited pairs. The audit is reproduced with `python -m evaluation.analyse_llm_stack`.

## Limits
Synthetic catalogue and shared canonical vocabulary; these scores are not evidence of real-shopper quality.
Warm throughput measures the local search stack with cached intents; it does not measure uncached Groq capacity. Fresh-call latency includes provider/network behavior and any reported fallback.
Explanations are disabled for the relevance/load comparisons so added explanation calls do not confound the intent comparison. Three separate explanation samples are not a quality benchmark.
The native SQLite run does not validate PostgreSQL/Docker deployment, million-product scale or long-duration uptime. Historical results used different hardware and should not be used as a before/after latency comparison.

Raw requests, ranking IDs, metrics, parser/fallback traces, model versions, dataset/source hashes and timings are in the JSON files beside this report.
