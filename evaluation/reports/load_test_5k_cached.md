# Load test / system health report

_Generated 2026-10-03 14:02:24 · catalogue size 5000 · host: x86_64 · 2 vCPU (all services + Postgres/Redis/Qdrant on the same host) · closed-loop virtual users, 10.0s per level, random draw from 120 multilingual queries · all numbers measured in this run._

## End-to-end
| mode | cache | concurrency | requests | throughput (req/s) | P50 ms | P95 ms | P99 ms | error rate | degraded |
|---|---|---|---|---|---|---|---|---|---|
| mosaic | True | 8 | 2450 | 245.58 | 11.5 | 194.4 | 451.3 | 0.0 | 0 |

## Component timings (server-side, ms)

**mosaic · cache=True · concurrency 8**

| component | P50 | P95 | P99 |
|---|---|---|---|
| embedding | 19.4 | 54.4 | 76.4 |
| intent | 8.0 | 26.0 | 45.8 |
| ranking | 27.1 | 62.4 | 85.5 |
| ranking.constraints | 0.0 | 0.1 | 3.5 |
| ranking.explain | 0.2 | 3.4 | 8.5 |
| ranking.fusion | 0.5 | 4.5 | 5.6 |
| ranking.signals | 0.3 | 0.9 | 4.9 |
| retrieval | 280.1 | 425.7 | 557.5 |
| retrieval.bm25 | 2.5 | 17.4 | 31.6 |
| retrieval.dense_ann | 138.8 | 232.7 | 252.4 |
| retrieval.fusion | 0.8 | 2.3 | 3.8 |
| retrieval.signal_completion | 38.0 | 120.4 | 136.0 |
| total | 338.5 | 503.7 | 636.3 |
