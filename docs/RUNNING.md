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
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | Groq / openai/gpt-oss-20b | provider settings; keep the key in local `.env` |
| `LLM_EXPLANATIONS` | `false` | allow the LLM to select complete approved template sentences; rewritten output retains the template |
| `ADMIN_API_KEY` | `change-me-admin-key` | required header `x-api-key` for catalogue writes — **change it** |
| `POSTGRES_DSN`, `REDIS_URL`, `QDRANT_URL` | localhost | infrastructure |
| `TEXT_MODEL_DIR`, `CLIP_MODEL_DIR`, `IMAGE_ROOT` | `./models/...`, `./data/images` | model and image locations |
| `IMAGE_ALLOWED_HOSTS` | Amazon CDN hostnames in `.env.example` | JSON array of exact allowed HTTPS image hosts; no wildcards |
| `MAX_IMAGE_BYTES` | 4000000 | maximum bytes per embedding-service image; base64 and local reads are also bounded |
| `MAX_IMAGE_PIXELS` | 20000000 | maximum decoded width × height; JPEG, PNG and WebP only |
| `IMAGE_FETCH_TIMEOUT_S` | 3 | embedding-service remote fetch deadline in seconds, including DNS and streaming |
| `CANDIDATE_POOL`, `RRF_K` | 100, 60 | retrieval breadth / fusion |
| `RATE_LIMIT_RPS`, `RATE_LIMIT_BURST` | 50, 100 | per-IP limit at the gateway; set `RATE_LIMIT_RPS=0` for benchmarks |

Free LLM examples:
```bash
# Groq (free tier key from console.groq.com)
LLM_PROVIDER=openai_compat LLM_BASE_URL=https://api.groq.com/openai/v1 LLM_MODEL=openai/gpt-oss-20b LLM_API_KEY=gsk_...
# Google AI Studio (free tier)
LLM_PROVIDER=gemini LLM_MODEL=gemini-2.0-flash LLM_API_KEY=...
# Fully local
ollama pull qwen2.5:3b && LLM_PROVIDER=ollama LLM_BASE_URL=http://localhost:11434 LLM_MODEL=qwen2.5:3b
```

## Verify the optional LLM

For Groq GPT-OSS models, the client uses low reasoning effort and a 1,024-token
completion budget, including reasoning. The intent prompt explicitly requires empty
arrays rather than null for absent list fields. Strict validation remains in place.
The older Llama default was retired for developer-tier usage; see
[Groq's deprecation notice](https://console.groq.com/docs/deprecations).

To run the opt-in provider check after configuring `.env`:

```bash
PYTHONPATH=libs:. python -m evaluation.validate_llm
```

On PowerShell, set `$env:PYTHONPATH="libs;."` before the Python command.
The check makes a small number of real API calls using synthetic requests and writes
`evaluation/reports/llm_live.json`; it does not measure full-stack search quality.
See [Live LLM verification](LLM_LIVE.md) for results and scope.

For the fully indexed real stack, compare rules against Groq and measure fresh-call
latency and warm-intent throughput with:

```bash
PYTHONPATH=libs:. python -m evaluation.evaluate_llm_stack --pace 8 --duration 20
```

See [Full-stack evaluation](LLM_STACK_EVALUATION.md) for deployment settings,
provider-quota considerations, results and interpretation.

## Configure image security

Keep the default Amazon hosts when using Amazon image URLs. To add a trusted CDN,
retain the hosts you need and add its exact hostname to the JSON array in `.env`:

```dotenv
IMAGE_ALLOWED_HOSTS=["m.media-amazon.com","images-na.ssl-images-amazon.com","images-eu.ssl-images-amazon.com","cdn.your-store.example"]
MAX_IMAGE_BYTES=4000000
MAX_IMAGE_PIXELS=20000000
IMAGE_FETCH_TIMEOUT_S=3
```

Replace `cdn.your-store.example` with your actual trusted host and restart the
embedding service after changing its settings. `IMAGE_ALLOWED_HOSTS=[]` disables
remote image downloads while leaving local images and uploaded base64 images
available. Wildcards and subdomains are not implicitly allowed. Remote URLs must
use HTTPS on port 443, resolve exclusively to public IPs and return the image
directly without redirects or HTTP compression. Local paths must be inside
`IMAGE_ROOT`; `local://dress.png` resolves relative to that directory.

Blocked, unreadable or oversized images use the existing text-only fallback. The
controls cover embedding-service loading, not the standalone image downloader
or the browser/UI display path. See [Security](SECURITY.md) for the full scope.

## Verify security behavior

After installing `requirements-dev.txt`, run:

```bash
python -m pytest tests/test_image_security.py tests/test_llm_security.py -q
```

These tests use fake DNS and HTTP transports and require no model weights, running
datastores or provider credentials. Before deployment, separately validate a real
approved CDN URL, an uploaded image and the configured live LLM provider. Rerun
`make eval load faults` and the scale test when publishing current-version metrics;
the checked-in measurements predate security commit `29901c6`.

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
