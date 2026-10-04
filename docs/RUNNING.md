# Running MOSAIC-Fashion

Everything is free/open-source. No paid API key is needed.

## Option A — Docker Compose (recommended)
```bash
git clone <your-repo-url> mosaic-fashion && cd mosaic-fashion
./scripts/download_models.sh            # ~83 MB e5 ONNX (SHA-pinned) + OpenCLIP weights -> ONNX (one-off torch export)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHONPATH=libs:. .venv/bin/python -m ingestion.synthetic_catalogue --n 5000 --out data --render   # or use Amazon data, below
cp .env.example .env                    # optional: configure a free LLM
docker compose up -d --build
docker compose run --rm seed            # loads data/catalogue.jsonl through the live ADD path
```
* UI: http://localhost:8501 · API docs: http://localhost:8000/docs · Qdrant dashboard: http://localhost:6333/dashboard
* Monitoring (optional): `docker compose --profile monitoring up -d prometheus` → http://localhost:9090

## Option B — native (what the reported numbers were produced with)
Prerequisites: Python 3.11+, PostgreSQL 16, Redis 7, Qdrant binary (https://github.com/qdrant/qdrant/releases).
```bash
make setup models data
# start infra (example)
sudo -u postgres psql -c "CREATE USER mosaic WITH PASSWORD 'mosaic_dev_pw';" -c "CREATE DATABASE mosaic OWNER mosaic;"
redis-server --daemonize yes
./qdrant &                               # storage path via QDRANT__STORAGE__STORAGE_PATH
cp .env.example .env
make local                               # starts 6 services + indexer + UI, waits for readiness
make seed                                # bulk load + wait until fully indexed
make test test-int                       # unit + integration tests
make eval load                           # offline relevance + ablations, load test
make faults                              # resilience drills
make scale                               # 20K -> 50K -> 100K growth test (long)
make stop
```

## Using the real Amazon Reviews 2023 data
```bash
wget https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw/meta_categories/meta_Amazon_Fashion.jsonl
make amazon AMAZON_META=meta_Amazon_Fashion.jsonl         # convert (20K items) + download images
make seed CATALOGUE_FILE=data/amazon_catalogue.local.jsonl
```
Notes: Amazon prices are USD → converted to INR (`--usd-inr`, default 83); stock is not in the dataset (`--default-stock`);
sizes are parsed from `details` when present. The offline relevance evaluation needs ground truth and therefore uses the synthetic
catalogue; on Amazon data use the UI/compare mode and the load/scale/fault tests (which do not need labels).

## Environment variables
See `.env.example` (documented inline). The important ones:

| variable | default | purpose |
|---|---|---|
| `LLM_PROVIDER` | `none` | `none` · `openai_compat` (Groq / OpenRouter free / local vLLM) · `gemini` · `ollama` |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | Groq / llama-3.1-8b-instant | free-tier provider settings |
| `LLM_EXPLANATIONS` | `false` | polish explanations with the LLM (grounding-checked) |
| `ADMIN_API_KEY` | `change-me-admin-key` | required header `x-api-key` for catalogue writes — **change it** |
| `POSTGRES_DSN`, `REDIS_URL`, `QDRANT_URL` | localhost | infrastructure |
| `TEXT_MODEL_DIR`, `CLIP_MODEL_DIR`, `IMAGE_ROOT` | `./models/...`, `./data/images` | model and image locations |
| `CANDIDATE_POOL`, `RRF_K` | 100, 60 | retrieval breadth / fusion |
| `RATE_LIMIT_RPS`, `RATE_LIMIT_BURST` | 50, 100 | per-IP limit at the gateway; set `RATE_LIMIT_RPS=0` for benchmarks |

Free LLM examples:
```bash
# Groq (free tier key from console.groq.com)
LLM_PROVIDER=openai_compat LLM_BASE_URL=https://api.groq.com/openai/v1 LLM_MODEL=llama-3.1-8b-instant LLM_API_KEY=gsk_...
# Google AI Studio (free tier)
LLM_PROVIDER=gemini LLM_MODEL=gemini-2.0-flash LLM_API_KEY=...
# Fully local
ollama pull qwen2.5:3b && LLM_PROVIDER=ollama LLM_BASE_URL=http://localhost:11434 LLM_MODEL=qwen2.5:3b
```

## API quick reference
```bash
curl -s localhost:8000/search -H 'content-type: application/json' \
  -d '{"query":"Chennai summer ku comfortable cotton dress venum under 2000","top_k":5}'
curl -s localhost:8000/compare -H 'content-type: application/json' -d '{"query":"शादी के लिए लाल लहंगा","top_k":5}'
# ablations: {"mode":"mosaic","ablation":{"adaptive":false,"use_visual":false,"use_intent":false,"use_context":false,"retrieval":"dense"}}
curl -s -X POST localhost:8000/catalogue/products -H 'x-api-key: change-me-admin-key' -H 'content-type: application/json' \
  -d '{"parent_asin":"NEW001","title":"Women Linen Kaftan Dress","price":1499,"stock_qty":10,"sizes":["M"]}'
curl -s -X PATCH localhost:8000/catalogue/products/NEW001 -H 'x-api-key: change-me-admin-key' -H 'content-type: application/json' -d '{"price":999}'
curl -s -X DELETE localhost:8000/catalogue/products/NEW001 -H 'x-api-key: change-me-admin-key'
curl -s -X POST localhost:8000/catalogue/time-to-searchable -H 'x-api-key: change-me-admin-key' -H 'content-type: application/json' -d '{}'
curl -s localhost:8000/system/status
```
