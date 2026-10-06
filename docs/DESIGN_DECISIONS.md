# Design decisions (ADR-style)

Each entry: **decision → why → trade-off / what would change it.**

Numerical evidence below comes from runs before security commit `29901c6` on
5 October 2026. The current native rules/Groq relevance and performance comparison
is documented separately in [Full-stack evaluation](LLM_STACK_EVALUATION.md).

## 1. Problem framing: search is *constraint satisfaction + preference ranking*, not just similarity
Human queries mix three kinds of information:

| kind | example (Tanglish: "Chennai summer ku comfortable cotton dress venum under 2000") | correct treatment |
|---|---|---|
| hard constraints | "under 2000", "dress", size, in-stock | **filter** — a ₹2,500 dress is wrong however similar it is |
| contextual needs | Chennai + summer ⇒ hot & humid; comfort | **reason** — map to physical product properties (breathability, warmth) |
| soft descriptors | cotton, floral, red, "elegant" | **rank** — semantic / lexical / visual similarity |

Pure dense retrieval treats all three as one vector. That is why every baseline in our evaluation has low
constraint satisfaction (BM25 0.36, Dense 0.44, Hybrid 0.52 of top-10 items meet the stated constraints)
while MOSAIC is 0.98.

## 2. Microservice boundaries follow *change rate* and *resource profile*
| service | why separate |
|---|---|
| gateway | single public surface; orchestration, fallbacks, cache, rate limiting |
| intent | LLM latency/cost isolation; can be scaled/cached independently; swap providers without touching search |
| embedding | the only CPU/GPU-heavy, model-bound service; batching; future GPU pool |
| retrieval | index-bound (memory); stateful BM25 warm-up; scale by replicas/shards |
| ranking | pure CPU, stateless; where the research contribution lives — iterate independently |
| catalogue | system of record + write path; different SLOs (consistency) than the read path |
| indexer | asynchronous; absorbs bursts of catalogue changes without affecting query latency |

We did **not** split further (e.g. separate BM25 service, separate explanation service): those would add
network hops on the hot path without independent scaling needs at this size.

## 3. Models: multilingual-e5-small (int8 ONNX) + OpenCLIP ViT-B/32 (ONNX), torch-free serving
* e5 covers 100+ languages incl. Tamil and Hindi in one embedding space; small (118 MB int8) → ~550 short texts/s on 2 vCPU.
* CLIP is English-only, so the visual tower is fed the **English normalisation** produced by intent decomposition
  ("a photo of red silk saree"), which makes the image signal work for Tamil/Hindi queries too.
* ONNX Runtime removes PyTorch (≈2–3 GB) from the serving images; the CLIP export is verified against PyTorch
  (cosine 1.0000). All weights are free/open (MIT).
* Trade-off: e5-small is weaker than e5-large/BGE-M3; on Tamil queries dense-only NDCG@10 is 0.21. The architecture
  makes the model a config value (`TEXT_MODEL_DIR`), and the ablation shows intent decomposition recovers most of the gap.

## 4. Hybrid retrieval with Reciprocal Rank Fusion, then a learned-free context-adaptive reranker
* RRF (k=60) is parameter-light and robust to score-scale differences between BM25 and cosine.
* Both channels get **hard filters pushed down** (Qdrant payload filter; BM25 accept-function), so filtered-out items
  never waste candidate slots.
* Every candidate gets the *full* signal vector (BM25 computed for dense-only hits; cosine & CLIP from stored vectors for
  BM25-only hits) so the reranker is not biased toward the channel that found an item.

## 5. The contribution: intent-conditioned weights (`services/ranking/adaptive.py`)
`w(intent) = normalise(BASE ⊙ active(intent) ⊙ Π boosts(intent))`

* **Activation**: a signal with no evidence in the query is switched off (no occasion asked ⇒ occasion weight 0),
  instead of injecting noise.
* **Boosts** (all logged as human-readable rationale): query image ⇒ visual ×3.5; colour/pattern words ⇒ visual ×3;
  destination+season ⇒ climate ×2.07 and implied-fabric preference; explicit fabric ⇒ material ×1.8; comfort ⇒ ×1.7;
  occasion ⇒ ×1.5; brand/quoted terms ⇒ lexical ×2; native-script/code-mixed query ⇒ lexical ×0.6, semantic ×1.15;
  vague query ⇒ semantic ×1.4.
* **Per-item renormalisation**: if a product has no image, its visual weight is redistributed over its remaining signals
  (image fallback without penalising image-less products).
* **Why rules and not a learned ranker (LTR)?** There is no click/purchase log to train on; rules are transparent and every
  weight change is explainable to a merchandiser. The weights are an interface: a LambdaMART/GBDT model trained on
  interaction logs can later output `w(intent)` (or replace the fusion) behind the same API, with these rules as the cold-start prior.
* Evidence: adaptive vs fixed weights +0.013 NDCG@10 (p=0.0001); removing context signals −0.086; removing the image
  signal −0.022 (p=0.0002). Gains are modest because hard constraints + intent already do most of the work — reported as measured.

## 6. Context signals are physical, not lexical
"Chennai summer" rarely appears in product text. We resolve destination+season → climate (`hot_humid`) and score products
on **material physics** (breathability, warmth, rain suitability from a material table), garment type (no coats for Chennai)
and season cues. This generalises to items whose text never mentions the weather.

## 7. LLM: optional, free, constrained, never selects products
* Providers: OpenAI-compatible (Groq free tier, OpenRouter `:free` models, local vLLM/LM Studio), Gemini free tier, Ollama.
  Default `LLM_PROVIDER=none` ⇒ fully offline, zero cost.
* Queries are serialized as untrusted data. Fresh and cached intent output must satisfy a strict, bounded JSON contract
  before canonical vocabulary normalisation. Unknown keys, wrong types, nonfinite budgets and invalid ranges are rejected.
* **Rules own hard constraints.** Budget, size and gender are never filled by the LLM, and explicit rule categories cannot
  be expanded by model output. This limits model-created filters, but unsupported numeric/size expressions need parser
  improvements. A wrong rule category still needs a parser fix or a separately designed relaxation policy.
* Optional explanations select ordered complete sentences from the approved template. Exact sentence validation replaces
  the earlier number/vocabulary check, which could accept unsupported claims. The trade-off is reduced wording freedom;
  neither user needs nor raw catalogue text can authorize new explanation claims.
* Failure/timeout ⇒ deterministic multilingual rule parser (tested drill: unreachable LLM ⇒ 100% answered by rules).

## 8. Evolving catalogue: transactional outbox → Redis Streams → incremental indexers
* Write path: row + outbox event in **one Postgres transaction** (no lost/phantom events if a process dies between DB write and publish).
* Relay uses `FOR UPDATE SKIP LOCKED` ⇒ safe with N catalogue replicas.
* Redis Streams consumer groups give at-least-once delivery and replay; consumers are idempotent (version checks).
* Qdrant points are upserted/deleted per product; BM25 has O(|doc|) add/delete (custom index, because `rank_bm25`
  requires full rebuilds). **No rebuilds anywhere.** Measured time-to-searchable ≈ 0.2 s (lexical) / 0.25 s (dense).
* Search cache keys include `catalogue_version`, so any catalogue change invalidates stale cached results.
* **Why Redis Streams instead of RabbitMQ/Kafka?** Redis is already required (cache); Streams provide the semantics we need
  (consumer groups, acks, pending-entry recovery, replay). Adding a broker would add an operational component without new
  capability at this scale. At millions of products / multi-region, move to Kafka (partition by product id) — the
  `EventBus` class is the only code that changes.

## 9. Reliability posture
* Every hop: timeout + bounded retries with backoff + circuit breaker (`mosaic_common/http.py`).
* Degraded modes are explicit and returned to the client in `degraded[]`:
  intent down ⇒ passthrough query; embedding down ⇒ BM25-only; Qdrant down ⇒ BM25-only; ranking down ⇒ retrieval order;
  image missing ⇒ text-only point; LLM down ⇒ rules.
* `/health` (liveness) vs `/ready` (dependencies) on every service; Prometheus `/metrics` (request latency histograms,
  component latency, fallback counters, indexer lag).
* Structured JSON logs with a propagated `x-request-id`.
* Input validation with Pydantic (query length, image size, product schema, ASIN pattern); admin key on catalogue writes;
  path-traversal guard for local images; non-root container user.

## 10. Data: Amazon Reviews 2023 schema; synthetic catalogue for the sandboxed run
* `ingestion/amazon_adapter.py` maps the official `meta_Amazon_Fashion.jsonl` (title, features, description, details,
  images, price, store, categories) to the product schema; USD→INR conversion and missing stock/size handling are explicit options.
* The build sandbox could not reach HuggingFace or Amazon's image CDN, so evaluation runs on a **synthetic catalogue in the
  same schema** with procedurally rendered product images and a hidden ground truth. This makes relevance labels exact and
  recall computable, but it also means absolute numbers are optimistic versus real, noisier Amazon data (see EVALUATION.md §Limitations).

## 11. Explainability as a first-class output
Every result carries: match score, raw signal values, weighted contributions, the weight vector with rationale, the hard
constraints it satisfied, and an explanation assembled only from intent + product fields (each clause traceable to a field).

## 12. Image fetching uses an explicit trust boundary

The embedding service accepts exact configured HTTPS CDN hosts on port 443, requires all DNS answers to be public,
and pins the connection to a validated IP with the original hostname used for TLS verification. Redirects are rejected
instead of followed, preventing an approved URL from redirecting to an internal service. Environment proxies are disabled.
Local files must resolve inside `IMAGE_ROOT`; bounded reads, strict base64 decoding and pixel limits constrain processing.

The trade-off is that custom CDNs need configuration, HTTP/redirecting URLs are unsupported, and large or unsupported
images use the text-only fallback. These controls currently cover the embedding service; standalone ingestion/download
tools and UI image display have separate paths and are not covered by this loader. Network egress restrictions and
trusted catalogue ingestion remain complementary controls. See [Security](SECURITY.md).
