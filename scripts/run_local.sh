#!/usr/bin/env bash
# Run the whole MOSAIC stack natively (no Docker): infra + 6 services + indexer + UI.
# Infra expected locally: PostgreSQL (5432), Redis (6379), Qdrant (6333). See docs/RUNNING.md.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/libs:$PWD"
PY=${PY:-.venv/bin/python}
mkdir -p logs
start() { # name module port
  local name=$1 mod=$2 port=$3
  if curl -sf "localhost:$port/health" >/dev/null 2>&1; then echo "  $name already up on :$port"; return; fi
  nohup $PY -m uvicorn "$mod" --host 0.0.0.0 --port "$port" --workers "${WORKERS:-1}" --log-level warning > "logs/$name.log" 2>&1 &
  echo "  started $name on :$port (pid $!)"
}
echo "starting services..."
start catalogue services.catalogue.app:app 8005
start embedding services.embedding.app:app 8002
start intent    services.intent.app:app    8001
start ranking   services.ranking.app:app   8004
for i in $(seq 1 60); do curl -sf localhost:8005/ready >/dev/null 2>&1 && break; sleep 1; done
start retrieval services.retrieval.app:app 8003
start indexer   services.indexer.worker:app 8006
start gateway   services.gateway.app:app   8000
for i in $(seq 1 120); do curl -sf localhost:8002/ready >/dev/null 2>&1 && break; sleep 1; done
if [ "${NO_UI:-0}" != "1" ] && ! curl -sf localhost:8501 >/dev/null 2>&1; then
  nohup .venv/bin/streamlit run ui/streamlit_app.py --server.port 8501 --server.headless true > logs/ui.log 2>&1 &
  echo "  started ui on :8501"
fi
echo "waiting for readiness..."
for p in 8005 8002 8001 8004 8003 8006 8000; do
  for i in $(seq 1 120); do curl -sf "localhost:$p/ready" >/dev/null 2>&1 && break; sleep 1; done
  printf "  :%s %s\n" "$p" "$(curl -s localhost:$p/ready)"
done
