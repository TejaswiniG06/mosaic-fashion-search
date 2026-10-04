# Offline evaluation report

_Generated 2026-10-03 13:58:12 from 120 queries (30 information needs × 4 languages) against a live stack with a 5000-product catalogue (synthetic, Amazon-2023 schema). Relevance judged against hidden ground truth (see evaluation/judge.py). All numbers are from this run._

## Overall
| System | P@5 | P@10 | R@10 | NDCG@10 | MRR | MAP@10 | HitRate@10 | ConstraintSat@10 | mean latency (ms) |
|---|---|---|---|---|---|---|---|---|---|
| BM25 | 0.342 | 0.346 | 0.047 | 0.306 | 0.395 | 0.309 | 0.467 | 0.361 | 36 |
| Dense | 0.403 | 0.378 | 0.045 | 0.331 | 0.553 | 0.298 | 0.750 | 0.438 | 127 |
| Hybrid | 0.498 | 0.471 | 0.059 | 0.412 | 0.588 | 0.397 | 0.783 | 0.521 | 142 |
| MOSAIC | 0.965 | 0.954 | 0.174 | 0.916 | 0.968 | 0.943 | 0.983 | 0.983 | 196 |
| MOSAIC-fixed-weights | 0.965 | 0.949 | 0.172 | 0.903 | 0.965 | 0.938 | 0.983 | 0.983 | 198 |
| MOSAIC-text-only | 0.963 | 0.948 | 0.170 | 0.894 | 0.975 | 0.937 | 0.983 | 0.983 | 164 |
| MOSAIC-dense-candidates | 0.968 | 0.954 | 0.174 | 0.901 | 0.969 | 0.944 | 0.983 | 0.983 | 166 |
| MOSAIC-no-intent | 0.463 | 0.435 | 0.053 | 0.384 | 0.603 | 0.360 | 0.767 | 0.494 | 209 |
| MOSAIC-no-context | 0.947 | 0.912 | 0.163 | 0.830 | 0.974 | 0.893 | 0.983 | 0.983 | 194 |
| Hybrid+filters | 0.960 | 0.932 | 0.167 | 0.840 | 0.971 | 0.917 | 0.983 | 0.983 | 164 |

## NDCG@10 by language
| System | en | ta | tanglish | hi |
|---|---|---|---|---|
| BM25 | 0.691 | 0.000 | 0.533 | 0.000 |
| Dense | 0.556 | 0.209 | 0.272 | 0.288 |
| Hybrid | 0.677 | 0.209 | 0.473 | 0.288 |
| MOSAIC | 0.947 | 0.877 | 0.943 | 0.896 |
| MOSAIC-fixed-weights | 0.929 | 0.865 | 0.933 | 0.883 |
| MOSAIC-text-only | 0.932 | 0.855 | 0.915 | 0.875 |
| MOSAIC-dense-candidates | 0.941 | 0.868 | 0.921 | 0.875 |
| MOSAIC-no-intent | 0.637 | 0.211 | 0.399 | 0.287 |
| MOSAIC-no-context | 0.879 | 0.808 | 0.830 | 0.803 |
| Hybrid+filters | 0.874 | 0.818 | 0.843 | 0.824 |

## Constraint satisfaction@10 by language
| System | en | ta | tanglish | hi |
|---|---|---|---|---|
| BM25 | 0.780 | 0.000 | 0.663 | 0.000 |
| Dense | 0.677 | 0.307 | 0.383 | 0.383 |
| Hybrid | 0.780 | 0.307 | 0.613 | 0.383 |
| MOSAIC | 1.000 | 0.967 | 1.000 | 0.967 |
| MOSAIC-fixed-weights | 1.000 | 0.967 | 1.000 | 0.967 |
| MOSAIC-text-only | 1.000 | 0.967 | 1.000 | 0.967 |
| MOSAIC-dense-candidates | 1.000 | 0.967 | 1.000 | 0.967 |
| MOSAIC-no-intent | 0.743 | 0.307 | 0.540 | 0.387 |
| MOSAIC-no-context | 1.000 | 0.967 | 1.000 | 0.967 |
| Hybrid+filters | 1.000 | 0.967 | 1.000 | 0.967 |

## MOSAIC vs others (paired permutation test, 10k resamples)
| Compared system | ΔNDCG@10 | p | ΔP@10 | p |
|---|---|---|---|---|
| BM25 | +0.610 | 0.0001 | +0.608 | 0.0001 |
| Dense | +0.585 | 0.0001 | +0.577 | 0.0001 |
| Hybrid | +0.504 | 0.0001 | +0.483 | 0.0001 |
| MOSAIC-fixed-weights | +0.013 | 0.0001 | +0.005 | 0.2105 |
| MOSAIC-text-only | +0.022 | 0.0002 | +0.007 | 0.1319 |
| MOSAIC-dense-candidates | +0.014 | 0.0002 | +0.000 | 1.0000 |
| MOSAIC-no-intent | +0.532 | 0.0001 | +0.519 | 0.0001 |
| MOSAIC-no-context | +0.086 | 0.0001 | +0.043 | 0.0001 |
| Hybrid+filters | +0.076 | 0.0001 | +0.022 | 0.0036 |

## Language identification accuracy (MOSAIC run)
| en | ta | tanglish | hi |
|---|---|---|---|
| 1.0 | 1.0 | 1.0 | 1.0 |

Request errors: 0
