# One image for every Python service (gateway, intent, embedding, retrieval, ranking, catalogue, indexer, ui).
# The service is selected by the compose `command`. Models are mounted read-only from ./models.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app/libs:/app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY libs ./libs
COPY services ./services
COPY ingestion ./ingestion
COPY evaluation ./evaluation
COPY ui ./ui
COPY pyproject.toml .
RUN useradd -u 10001 -m mosaic && chown -R mosaic /app
USER mosaic
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD curl -fs http://localhost:${PORT:-8000}/health || exit 1
CMD ["uvicorn", "services.gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
