# Load test / system health report

_Generated 2026-10-03 13:58:13 · catalogue size 5000 · host: x86_64 · 2 vCPU (all services + Postgres/Redis/Qdrant on the same host) · closed-loop virtual users, 20.0s per level, random draw from 120 multilingual queries · all numbers measured in this run._

## End-to-end
| mode | cache | concurrency | requests | throughput (req/s) | P50 ms | P95 ms | P99 ms | error rate | degraded |
|---|---|---|---|---|---|---|---|---|---|
| mosaic | False | 1 | 253 | 12.66 | 80.9 | 110.9 | 129.7 | 0.0 | 0 |
| mosaic | False | 4 | 391 | 19.48 | 205.3 | 285.5 | 326.6 | 0.0 | 0 |
| mosaic | False | 8 | 443 | 21.94 | 365.9 | 503.7 | 615.0 | 0.0 | 0 |
| mosaic | False | 16 | 433 | 21.21 | 771.8 | 1031.5 | 1097.8 | 0.0 | 0 |
| hybrid | False | 1 | 372 | 18.59 | 52.2 | 63.1 | 81.3 | 0.0 | 0 |
| hybrid | False | 4 | 586 | 29.21 | 132.3 | 185.8 | 234.3 | 0.0 | 0 |
| hybrid | False | 8 | 607 | 29.96 | 264.4 | 377.4 | 440.8 | 0.0 | 0 |
| hybrid | False | 16 | 633 | 30.91 | 504.3 | 694.7 | 798.3 | 0.0 | 0 |
| bm25 | False | 1 | 1564 | 78.31 | 8.8 | 20.7 | 41.9 | 0.0 | 0 |
| bm25 | False | 4 | 2265 | 113.32 | 33.6 | 61.3 | 80.2 | 0.0 | 0 |
| bm25 | False | 8 | 2381 | 118.97 | 64.5 | 107.2 | 125.8 | 0.0 | 0 |
| bm25 | False | 16 | 2287 | 114.06 | 132.4 | 230.5 | 278.9 | 0.0 | 0 |

## Component timings (server-side, ms)

**mosaic · cache=False · concurrency 1**

| component | P50 | P95 | P99 |
|---|---|---|---|
| embedding | 5.6 | 7.0 | 8.4 |
| intent | 3.1 | 4.0 | 4.6 |
| ranking | 9.4 | 14.3 | 17.0 |
| ranking.constraints | 0.1 | 0.1 | 0.1 |
| ranking.explain | 0.2 | 0.5 | 0.7 |
| ranking.fusion | 0.5 | 1.0 | 1.3 |
| ranking.signals | 0.3 | 0.8 | 1.1 |
| retrieval | 57.9 | 82.9 | 102.8 |
| retrieval.bm25 | 3.1 | 11.1 | 12.6 |
| retrieval.dense_ann | 40.9 | 48.3 | 58.4 |
| retrieval.fusion | 0.7 | 1.1 | 1.4 |
| retrieval.signal_completion | 4.6 | 20.0 | 23.6 |
| total | 77.7 | 107.4 | 126.2 |

**mosaic · cache=False · concurrency 4**

| component | P50 | P95 | P99 |
|---|---|---|---|
| embedding | 13.5 | 26.1 | 34.9 |
| intent | 6.1 | 14.6 | 22.4 |
| ranking | 18.6 | 36.7 | 59.7 |
| ranking.constraints | 0.1 | 0.1 | 0.8 |
| ranking.explain | 0.2 | 0.5 | 4.4 |
| ranking.fusion | 0.5 | 2.6 | 6.6 |
| ranking.signals | 0.4 | 2.9 | 5.3 |
| retrieval | 155.2 | 216.6 | 267.8 |
| retrieval.bm25 | 3.1 | 14.7 | 20.8 |
| retrieval.dense_ann | 79.2 | 125.5 | 148.5 |
| retrieval.fusion | 0.8 | 2.1 | 4.0 |
| retrieval.signal_completion | 24.1 | 67.7 | 79.7 |
| total | 195.5 | 276.9 | 319.9 |

**mosaic · cache=False · concurrency 8**

| component | P50 | P95 | P99 |
|---|---|---|---|
| embedding | 16.9 | 43.4 | 59.4 |
| intent | 7.8 | 26.7 | 39.1 |
| ranking | 28.4 | 60.9 | 81.4 |
| ranking.constraints | 0.0 | 0.1 | 0.2 |
| ranking.explain | 0.2 | 2.2 | 6.7 |
| ranking.fusion | 0.5 | 4.5 | 7.5 |
| ranking.signals | 0.4 | 3.9 | 7.1 |
| retrieval | 289.4 | 409.9 | 514.1 |
| retrieval.bm25 | 2.6 | 17.0 | 26.0 |
| retrieval.dense_ann | 139.8 | 214.0 | 297.6 |
| retrieval.fusion | 0.7 | 2.1 | 8.0 |
| retrieval.signal_completion | 43.7 | 121.9 | 187.8 |
| total | 353.1 | 486.2 | 594.0 |

**mosaic · cache=False · concurrency 16**

| component | P50 | P95 | P99 |
|---|---|---|---|
| embedding | 28.8 | 127.6 | 169.6 |
| intent | 12.1 | 68.3 | 121.7 |
| ranking | 43.6 | 123.7 | 182.2 |
| ranking.constraints | 0.1 | 0.1 | 1.6 |
| ranking.explain | 0.2 | 2.9 | 6.3 |
| ranking.fusion | 0.6 | 4.8 | 9.4 |
| ranking.signals | 0.4 | 4.9 | 9.2 |
| retrieval | 632.1 | 820.6 | 909.2 |
| retrieval.bm25 | 2.7 | 17.9 | 30.1 |
| retrieval.dense_ann | 305.3 | 428.5 | 533.1 |
| retrieval.fusion | 0.7 | 3.8 | 9.5 |
| retrieval.signal_completion | 100.0 | 236.3 | 305.8 |
| total | 755.5 | 1004.0 | 1051.9 |

**hybrid · cache=False · concurrency 1**

| component | P50 | P95 | P99 |
|---|---|---|---|
| embedding | 3.6 | 4.4 | 4.8 |
| ranking | 8.9 | 12.6 | 34.4 |
| ranking.constraints | 0.0 | 0.1 | 0.1 |
| ranking.explain | 0.1 | 0.2 | 0.2 |
| ranking.signals | 0.1 | 0.2 | 0.3 |
| retrieval | 35.4 | 41.4 | 51.2 |
| retrieval.bm25 | 0.3 | 4.0 | 4.7 |
| retrieval.dense_ann | 27.3 | 31.2 | 35.7 |
| retrieval.fusion | 0.8 | 1.3 | 1.7 |
| total | 49.1 | 59.8 | 78.4 |

**hybrid · cache=False · concurrency 4**

| component | P50 | P95 | P99 |
|---|---|---|---|
| embedding | 6.4 | 14.3 | 18.7 |
| ranking | 20.3 | 37.3 | 63.8 |
| ranking.constraints | 0.0 | 0.1 | 0.1 |
| ranking.explain | 0.1 | 0.2 | 2.2 |
| ranking.signals | 0.1 | 0.2 | 2.8 |
| retrieval | 97.8 | 132.4 | 186.7 |
| retrieval.bm25 | 0.0 | 4.1 | 6.9 |
| retrieval.dense_ann | 54.9 | 88.6 | 103.1 |
| retrieval.fusion | 0.9 | 1.8 | 4.0 |
| total | 126.1 | 176.3 | 229.7 |

**hybrid · cache=False · concurrency 8**

| component | P50 | P95 | P99 |
|---|---|---|---|
| embedding | 10.4 | 33.3 | 45.3 |
| ranking | 39.8 | 80.6 | 99.2 |
| ranking.constraints | 0.0 | 0.1 | 0.1 |
| ranking.explain | 0.1 | 0.3 | 4.1 |
| ranking.signals | 0.1 | 0.2 | 4.1 |
| retrieval | 198.9 | 272.8 | 357.8 |
| retrieval.bm25 | 0.3 | 4.5 | 7.7 |
| retrieval.dense_ann | 106.8 | 178.1 | 211.9 |
| retrieval.fusion | 0.9 | 2.0 | 5.5 |
| total | 252.2 | 356.6 | 428.1 |

**hybrid · cache=False · concurrency 16**

| component | P50 | P95 | P99 |
|---|---|---|---|
| embedding | 15.9 | 57.7 | 88.3 |
| ranking | 78.9 | 146.3 | 194.3 |
| ranking.constraints | 0.0 | 0.1 | 0.2 |
| ranking.explain | 0.1 | 0.2 | 3.9 |
| ranking.signals | 0.1 | 0.2 | 2.9 |
| retrieval | 388.0 | 518.2 | 572.2 |
| retrieval.bm25 | 0.2 | 3.2 | 7.0 |
| retrieval.dense_ann | 222.4 | 328.5 | 366.6 |
| retrieval.fusion | 0.8 | 1.7 | 5.6 |
| total | 485.3 | 663.4 | 758.2 |

**bm25 · cache=False · concurrency 1**

| component | P50 | P95 | P99 |
|---|---|---|---|
| ranking | 2.8 | 8.4 | 10.4 |
| ranking.constraints | 0.0 | 0.0 | 0.1 |
| ranking.explain | 0.0 | 0.4 | 0.5 |
| ranking.signals | 0.0 | 0.1 | 0.1 |
| retrieval | 2.9 | 8.9 | 10.9 |
| retrieval.bm25 | 0.0 | 3.1 | 4.9 |
| retrieval.fusion | 0.0 | 0.7 | 1.1 |
| total | 6.3 | 18.1 | 39.4 |

**bm25 · cache=False · concurrency 4**

| component | P50 | P95 | P99 |
|---|---|---|---|
| ranking | 11.5 | 23.9 | 46.7 |
| ranking.constraints | 0.0 | 0.0 | 0.1 |
| ranking.explain | 0.0 | 0.4 | 1.8 |
| ranking.signals | 0.0 | 0.1 | 0.2 |
| retrieval | 11.4 | 23.6 | 34.3 |
| retrieval.bm25 | 0.0 | 4.1 | 6.5 |
| retrieval.fusion | 0.0 | 0.9 | 3.0 |
| total | 25.4 | 49.9 | 70.8 |

**bm25 · cache=False · concurrency 8**

| component | P50 | P95 | P99 |
|---|---|---|---|
| ranking | 21.5 | 49.6 | 68.5 |
| ranking.constraints | 0.0 | 0.0 | 0.1 |
| ranking.explain | 0.0 | 0.4 | 4.3 |
| ranking.signals | 0.1 | 0.1 | 0.2 |
| retrieval | 21.6 | 43.2 | 60.1 |
| retrieval.bm25 | 0.1 | 4.8 | 8.3 |
| retrieval.fusion | 0.1 | 1.0 | 4.2 |
| total | 47.8 | 88.8 | 107.0 |

**bm25 · cache=False · concurrency 16**

| component | P50 | P95 | P99 |
|---|---|---|---|
| ranking | 42.3 | 106.5 | 154.5 |
| ranking.constraints | 0.0 | 0.0 | 0.1 |
| ranking.explain | 0.0 | 0.5 | 4.5 |
| ranking.signals | 0.0 | 0.1 | 0.3 |
| retrieval | 46.2 | 105.6 | 148.3 |
| retrieval.bm25 | 0.0 | 5.9 | 10.8 |
| retrieval.fusion | 0.0 | 2.0 | 5.6 |
| total | 100.7 | 193.3 | 241.1 |
