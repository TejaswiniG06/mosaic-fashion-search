# MOSAIC-Fashion developer commands
PY ?= .venv/bin/python
export PYTHONPATH := $(CURDIR)/libs:$(CURDIR)

.PHONY: setup models data seed up down local stop test test-int eval load scale ui lint

setup:            ## create venv + install deps
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

models:           ## download free open-source models (e5 ONNX + OpenCLIP -> ONNX)
	./scripts/download_models.sh

data:             ## synthetic 5K catalogue (Amazon-2023 schema) + rendered images
	$(PY) -m ingestion.synthetic_catalogue --n 5000 --out data --render

amazon:           ## convert real Amazon Reviews 2023 metadata (set AMAZON_META=path/to/meta_Amazon_Fashion.jsonl[.gz])
	$(PY) -m ingestion.amazon_adapter --input $(AMAZON_META) --out data/amazon_catalogue.jsonl --limit 20000
	$(PY) -m ingestion.download_images --file data/amazon_catalogue.jsonl --out data/amazon_catalogue.local.jsonl

seed:             ## load catalogue through the live ADD path and wait for indexing
	$(PY) -m ingestion.load_catalogue --file $(or $(CATALOGUE_FILE),data/catalogue.jsonl)

up:               ## docker compose stack
	docker compose up -d --build

down:
	docker compose down

local:            ## run all services natively (needs local Postgres/Redis/Qdrant)
	./scripts/run_local.sh

stop:
	./scripts/stop_local.sh

test:             ## unit tests (no stack needed)
	$(PY) -m pytest -q -m "not integration"

test-int:         ## integration tests against the running stack
	$(PY) -m pytest -q -m integration

eval:             ## offline relevance evaluation + ablations (writes evaluation/reports/offline_eval.md)
	$(PY) -m evaluation.run_offline_eval

load:             ## system-health load test
	$(PY) -m evaluation.load_test --levels 1,4,8,16 --duration 20 --modes mosaic,hybrid,bm25

scale:            ## grow catalogue 20K -> 50K -> 100K and measure
	$(PY) -m evaluation.scale_test --sizes 20000,50000,100000

faults:           ## resilience drills (LLM down, Qdrant down, embedding down, image missing)
	$(PY) -m evaluation.fault_injection
