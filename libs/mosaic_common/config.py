"""Centralised, validated configuration loaded from environment / `.env`.

Every service imports `get_settings()`; nothing reads os.environ directly, so
configuration is typed, documented in one place and safe to override per
deployment (Docker Compose, Kubernetes ConfigMap/Secret, local `.env`).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True

    # ---- service URLs (overridden in docker-compose with service DNS names)
    gateway_url: str = "http://localhost:8000"
    intent_url: str = "http://localhost:8001"
    embedding_url: str = "http://localhost:8002"
    retrieval_url: str = "http://localhost:8003"
    ranking_url: str = "http://localhost:8004"
    catalogue_url: str = "http://localhost:8005"
    indexer_url: str = "http://localhost:8006"

    # ---- infrastructure
    catalogue_db: Literal["postgres", "sqlite"] = "postgres"   # sqlite = zero-install single-node mode
    sqlite_path: Path = REPO_ROOT / "data" / "catalogue.db"
    postgres_dsn: SecretStr = SecretStr("postgresql://mosaic:mosaic_dev_pw@localhost:5432/mosaic")
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "products"
    event_stream: str = "catalogue.events"

    # ---- models (all free / open-source, run locally on CPU through ONNX Runtime)
    text_model_dir: Path = REPO_ROOT / "models" / "multilingual-e5-small"
    text_model_file: str = "model_int8.onnx"
    clip_model_dir: Path = REPO_ROOT / "models" / "clip-vit-b32"
    onnx_threads: int = 2
    image_root: Path = REPO_ROOT / "data" / "images"
    image_fetch_timeout_s: float = 3.0

    # ---- LLM (optional; free providers supported). "none" => deterministic rule engine only
    llm_provider: Literal["none", "openai_compat", "gemini", "ollama"] = "none"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-20b"
    llm_api_key: SecretStr | None = None
    llm_timeout_s: float = 6.0
    llm_explanations: bool = False  # polish template explanations with the LLM (grounding-checked)

    # ---- retrieval / ranking
    candidate_pool: int = 100
    rrf_k: int = 60
    default_top_k: int = 10
    search_cache_ttl_s: int = 300

    # ---- resilience
    http_timeout_s: float = 5.0
    http_retries: int = 2
    breaker_fail_threshold: int = 5
    breaker_reset_s: float = 15.0

    # ---- security
    admin_api_key: SecretStr = SecretStr("change-me-admin-key")
    rate_limit_rps: float = 50.0     # per client IP token bucket at the gateway; 0 disables (benchmarks)
    rate_limit_burst: int = 100
    max_query_chars: int = 500
    max_image_bytes: int = Field(default=4_000_000, gt=0)
    max_image_pixels: int = Field(default=20_000_000, gt=0)
    image_allowed_hosts: list[str] = ["m.media-amazon.com", "images-na.ssl-images-amazon.com", "images-eu.ssl-images-amazon.com"]

    @field_validator("text_model_dir", "clip_model_dir", "image_root", "sqlite_path", mode="after")
    @classmethod
    def _resolve(cls, v: Path) -> Path:
        return v if v.is_absolute() else (REPO_ROOT / v).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
