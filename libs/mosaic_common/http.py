"""Resilient inter-service HTTP client: timeouts, bounded retries with backoff, circuit breaker,
request-id propagation. A tripped breaker fails fast so callers can take their fallback path."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .config import get_settings
from .logging import request_id_var


class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    def __init__(self, name: str, fail_threshold: int, reset_s: float):
        self.name, self.fail_threshold, self.reset_s = name, fail_threshold, reset_s
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if time.monotonic() - self.opened_at >= self.reset_s:
            return "half_open"
        return "open"

    def before(self) -> None:
        if self.state == "open":
            raise CircuitOpenError(f"circuit '{self.name}' open")

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.fail_threshold or self.state == "half_open":
            self.opened_at = time.monotonic()


class ServiceClient:
    def __init__(self, name: str, base_url: str, timeout_s: float | None = None, retries: int | None = None):
        s = get_settings()
        self.name = name
        self.retries = s.http_retries if retries is None else retries
        self.breaker = CircuitBreaker(name, s.breaker_fail_threshold, s.breaker_reset_s)
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s or s.http_timeout_s,
                                         limits=httpx.Limits(max_connections=100, max_keepalive_connections=20))

    async def request(self, method: str, path: str, **kw) -> Any:
        self.breaker.before()
        headers = kw.pop("headers", {}) or {}
        headers.setdefault("x-request-id", request_id_var.get())
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = await self._client.request(method, path, headers=headers, **kw)
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"{self.name} {r.status_code}", request=r.request, response=r)
                self.breaker.success()
                if r.status_code >= 400:
                    r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                if e.response is not None and e.response.status_code < 500:
                    raise
                last_exc = e
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_exc = e
            if attempt < self.retries:
                await asyncio.sleep(0.05 * (2 ** attempt))
        self.breaker.failure()
        raise last_exc  # type: ignore[misc]

    async def post(self, path: str, json: Any = None, **kw) -> Any:
        return await self.request("POST", path, json=json, **kw)

    async def get(self, path: str, **kw) -> Any:
        return await self.request("GET", path, **kw)

    async def ready(self) -> bool:
        try:
            r = await self._client.get("/ready", timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
