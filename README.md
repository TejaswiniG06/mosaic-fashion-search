# MOSAIC-Fashion

**Fashion search that understands the occasion, language and constraints behind a request.**

MOSAIC means **Multilingual Occasion- and Season-Aware Intent-Conditioned** fashion recommendation.
It is a production-oriented microservice prototype: users describe what they need in English,
Tamil, Tanglish, Hindi or Hinglish, optionally with a reference image. Results come from the
catalogue, with explanations and visible ranking signals. No paid API is required; the LLM is optional.

## The problem

A shopper asks, **“I need an outfit to go to the beach this summer.”** Keyword search may miss
suitable products whose titles never mention a beach. Similarity alone can also return an item
that exceeds the budget or is unavailable in the requested size.

MOSAIC separates **constraints to enforce** from **preferences to rank**. It combines multilingual
query understanding, semantic and keyword retrieval, visual similarity, and context-aware ranking.

## A search walkthrough

> `Chennai summer ku comfortable cotton dress venum under 2000`

1. **Understand:** detect Tanglish; extract dress, cotton, comfort, Chennai, summer and a ₹2,000 ceiling. Resolve Chennai + summer to a hot, humid climate.
2. **Filter:** enforce the recognised budget, explicit category, size/gender when applicable, and stock availability. Rules own hard constraints; optional validated LLM output adds semantic context.
3. **Retrieve:** combine multilingual e5 vectors and BM25 keyword matches using reciprocal rank fusion. CLIP adds visual signals; a reference image can also retrieve similar images.
4. **Rank:** adjust the importance of semantic, lexical, visual, occasion, climate, material and comfort signals for this query. Missing image evidence is handled explicitly.
5. **Explain:** return catalogue products with scores, constraint checks and template explanations. Optional LLM output may only select approved template sentences. If nothing matches, offer constraint-relaxation suggestions.

The API also returns the parsed intent, component timings and degraded-mode flags, so a reviewer
can see how a result was produced. [Detailed query flow](docs/ARCHITECTURE.md#query-path).

## How the system fits together

![Current MOSAIC architecture showing search services, optional LLM and catalogue indexing](docs/diagrams/architecture.png)

FastAPI services separate query orchestration, intent, embedding, retrieval and ranking from the
catalogue write path. PostgreSQL stores products; a transactional outbox publishes changes to
Redis Streams; consumers update Qdrant and the in-memory BM25 index incrementally. Updates are
asynchronous, so index freshness is measured rather than assumed.

Health endpoints, Prometheus metrics, request IDs, timeouts, retries and fallbacks expose system
behavior. Image loading in the embedding service restricts remote hosts and local paths and
bounds bytes/pixels. Strict LLM contracts protect hard constraints and explanation output.
See [Architecture](docs/ARCHITECTURE.md), [Design decisions](docs/DESIGN_DECISIONS.md) and [Security](docs/SECURITY.md).

## What the evaluation shows

**Historical baseline:** 5,000 synthetic products, 30 information needs translated into four
languages (120 queries). These measurements predate security commit `29901c6`; current-version
relevance and performance reruns are pending. Synthetic labels share a vocabulary with the system,
so the scores do not establish real-world quality.

| System | Relevant items in top 10 (P@10) | Ranking quality (NDCG@10) | Constraints satisfied |
|---|---:|---:|---:|
| BM25 keyword search | 0.346 | 0.306 | 0.361 |
| Dense semantic search | 0.378 | 0.331 | 0.438 |
| Hybrid retrieval | 0.471 | 0.412 | 0.521 |
| Hybrid + intent filters | 0.932 | 0.840 | 0.983 |
| **MOSAIC** | **0.954** | **0.916** | **0.983** |

Higher is better. P@10 measures relevant results; NDCG rewards placing the most relevant results first.

- **The largest gain came from understanding intent and enforcing constraints.** Hybrid + filters is the useful comparison for judging the extra ranking logic.
- **Context and visual ranking improved ordering.** Adaptive weights alone added 0.013 NDCG@10 over fixed weights; the gain is modest.
- **The original native run reached roughly 22 searches/s on 2 vCPU.** At 100K products, single-user P95 latency was 248 ms; in-memory BM25 became the scaling bottleneck.
- **Current security checks:** 31 tests passed for image restrictions, output validation, hard-constraint preservation and explanation rejection. Live CDN/provider validation remains pending.

Full results, ablations and caveats: [Evaluation](docs/EVALUATION.md). Growth measurements and
proposed deployment: [Scaling](docs/SCALING.md).

## Try it

**Windows without Docker:** install Python 3.12, run `setup_windows.bat` once, then
`start_windows.bat`. [Windows guide](docs/WINDOWS.md).

**Docker setup:**

```bash
./scripts/download_models.sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
PYTHONPATH=libs:. .venv/bin/python -m ingestion.synthetic_catalogue --n 5000 --out data --render
cp .env.example .env
docker compose up -d --build
docker compose run --rm seed
```

Open the UI at **http://localhost:8501** or API docs at **http://localhost:8000/docs**.
Try the Tanglish query above, compare BM25/Dense/Hybrid/MOSAIC, then add or update a catalogue
item and inspect its search visibility. Docker end-to-end validation is still pending;
reported measurements used the native stack. [Running guide](docs/RUNNING.md) covers native setup,
Amazon data, optional LLM providers and trusted image-host configuration.

### Demo captures

Earlier UI captures illustrate the interface; they predate the security changes and do not verify those protections.

| Parsed query and ranking signals | Retrieval comparison |
|---|---|
| ![Earlier Tanglish search demo](docs/screenshots/search_tanglish.png) | ![Earlier comparison demo](docs/screenshots/compare.png) |

## What needs improvement

The main priorities are independent human judgments on real products, broader multilingual
parsing (including negation and ambiguous categories), live LLM/CDN and Docker validation, and
stronger event recovery and cache/index consistency. The system still uses one admin key and
needs deployment authentication, TLS and shared rate limits before public exposure.

For larger catalogues, move lexical retrieval out of process and add version-safe distributed
indexing. With interaction data, evaluate a learned ranker and diversity against the current
interpretable rules. [Known limitations and next steps](docs/LIMITATIONS.md).

## Find your way around

| Location | Purpose |
|---|---|
| `services/` | Gateway, intent, embedding, retrieval, ranking, catalogue and indexer |
| `libs/mosaic_common/` | Shared schemas, configuration, filters and event/HTTP utilities |
| `ingestion/` and `ui/` | Catalogue adapters/generator and Streamlit demo |
| `evaluation/` and `tests/` | Reports, evaluation scripts and automated checks |
| `docs/` | Architecture, decisions, operations, security and limitations |
