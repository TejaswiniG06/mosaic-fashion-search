"""FastAPI service factory: health/readiness/metrics endpoints, request-id + timing middleware,
uniform error envelopes. Every microservice is created through `create_service`."""
from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from .config import get_settings
from .logging import configure_logging, log_event, new_request_id, request_id_var

REQUESTS = Counter("mosaic_http_requests_total", "HTTP requests", ["service", "path", "status"])
LATENCY = Histogram(
    "mosaic_http_request_seconds", "HTTP request latency", ["service", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
COMPONENT_LATENCY = Histogram(
    "mosaic_component_seconds", "Internal component latency", ["service", "component"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
)
FALLBACKS = Counter("mosaic_fallbacks_total", "Degraded-mode fallbacks taken", ["service", "kind"])

ReadyCheck = Callable[[], Awaitable[dict[str, bool]]]


def create_service(name: str, version: str = "1.0.0", ready_check: ReadyCheck | None = None) -> FastAPI:
    settings = get_settings()
    logger = configure_logging(name, settings.log_level, settings.log_json)
    app = FastAPI(title=f"MOSAIC {name} service", version=version)
    app.state.service_name = name
    app.state.started_at = time.time()

    @app.middleware("http")
    async def _context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or new_request_id()
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = rid
            return response
        except Exception:  # pragma: no cover - logged & re-raised to the exception handler
            logger.exception("unhandled error")
            raise
        finally:
            dt = time.perf_counter() - t0
            path = request.scope.get("route").path if request.scope.get("route") else request.url.path
            if path not in ("/metrics", "/health"):
                REQUESTS.labels(name, path, str(status)).inc()
                LATENCY.labels(name, path).observe(dt)
                log_event(logger, "request", method=request.method, path=path, status=status, ms=round(dt * 1000, 2))
            request_id_var.reset(token)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": "validation_error", "detail": exc.errors()[:10]})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("unhandled exception")
        return JSONResponse(status_code=500, content={"error": "internal_error", "detail": type(exc).__name__,
                                                      "request_id": request_id_var.get()})

    @app.get("/health", tags=["ops"])
    async def health():
        """Liveness: the process is up and serving."""
        return {"status": "ok", "service": name, "version": version, "uptime_s": round(time.time() - app.state.started_at, 1)}

    @app.get("/ready", tags=["ops"])
    async def ready():
        """Readiness: dependencies reachable / models loaded. 503 if not ready."""
        checks = await ready_check() if ready_check else {}
        ok = all(checks.values()) if checks else True
        return JSONResponse(status_code=200 if ok else 503, content={"ready": ok, "service": name, "checks": checks})

    @app.get("/metrics", tags=["ops"])
    async def metrics():
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.state.logger = logger
    return app


class Timer:
    """Context manager collecting component timings (ms) into a dict + Prometheus histogram."""

    def __init__(self, sink: dict[str, float], key: str, service: str = "-"):
        self.sink, self.key, self.service = sink, key, service

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        dt = time.perf_counter() - self.t0
        self.sink[self.key] = round(self.sink.get(self.key, 0.0) + dt * 1000, 2)
        COMPONENT_LATENCY.labels(self.service, self.key).observe(dt)
        return False


def log() -> logging.Logger:
    return logging.getLogger("mosaic")
