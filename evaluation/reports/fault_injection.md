# Fault-injection / resilience report

_Generated 2026-10-03 15:06:00 — each drill breaks one dependency of the live stack, sends 5 real multilingual queries, then restores it._

| drill | success (200 + results) | HTTP error rate | P50 ms | degraded flags reported | recovered after restore |
|---|---|---|---|---|---|
| baseline (all healthy) | 100% | 0% | 209 | - |  |
| LLM endpoint unreachable | 100% | 0% | 42 | llm_failed->rules |  |
| intent service down | 100% | 0% | 316 | intent_unavailable | 100% |
| embedding service down | 100% | 0% | 243 | embedding_clip_unavailable, embedding_text_unavailable, no_query_vector | 100% |
| Qdrant (vector DB) down | 100% | 0% | 105 | vector_search_unavailable | 100% |
| ranking service down | 100% | 0% | 330 | ranking_unavailable | 100% |
| product image unreachable | 100% | 0% | None | text-only point (has_image=false) |  |
