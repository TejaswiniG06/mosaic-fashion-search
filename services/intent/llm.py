"""LLM provider abstraction (free options): OpenAI-compatible APIs (Groq free tier, OpenRouter
free models, Together, local vLLM/LM Studio), Google Gemini free tier, or local Ollama.

The LLM is used ONLY for (1) intent decomposition and (2) explanation polishing. It never sees the
catalogue and never selects products. Outputs are JSON-schema validated and normalised onto the
canonical vocabulary; anything unparseable => caller falls back to the deterministic engine.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

# Use the operating-system certificate store for outbound HTTPS (needed behind antivirus / corporate
# HTTPS inspection, e.g. Kaspersky, where Python's bundled CA list rejects the connection).
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from mosaic_common.config import Settings

INTENT_SYSTEM = """You are a query-understanding module for an Indian fashion e-commerce search engine.
The user query may be English, Tamil (script), Tanglish (romanised Tamil mixed with English), Hindi, or Hinglish.
Decompose it into JSON with exactly these keys (use null / [] / false when absent; never invent values):
{"normalized_query_en": str (fluent English rewrite of the request),
 "category": [str] (garment types, e.g. dress, saree, kurta, shirt, t-shirt, jeans, sneakers, sandals, jacket),
 "category_explicit": bool (true only if the user named a garment type),
 "occasion": [str] from [casual, office, party, wedding, festive, beach, sports, lounge, travel, traditional],
 "season": one of [summer, winter, monsoon] or null,
 "destination": str city/place or null,
 "comfort": bool, "style": [str], "material": [str], "colour": [str], "pattern": [str],
 "budget_min": number or null, "budget_max": number or null (INR; "2k" = 2000),
 "size": str or null, "gender": one of [men, women, kids] or null, "sustainability": bool, "brand": [str]}
Return ONLY the JSON object."""

EXPLAIN_SYSTEM = """You write one-sentence shopping explanations (max 35 words).
Use ONLY the facts given in PRODUCT_FACTS and USER_NEEDS. Do not add any number, material, colour, brand,
occasion or claim that is not present in the facts. No marketing fluff."""


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, s: Settings):
        self.s = s
        self.enabled = s.llm_provider != "none"
        self._http = httpx.AsyncClient(timeout=s.llm_timeout_s)

    async def _chat(self, system: str, user: str, json_mode: bool) -> str:
        s = self.s
        key = s.llm_api_key.get_secret_value() if s.llm_api_key else None
        if s.llm_provider == "openai_compat":
            body: dict[str, Any] = {"model": s.llm_model, "temperature": 0, "max_tokens": 400,
                                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            r = await self._http.post(f"{s.llm_base_url.rstrip('/')}/chat/completions", json=body,
                                      headers={"Authorization": f"Bearer {key}"} if key else {})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        if s.llm_provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{s.llm_model}:generateContent"
            body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": 400, **({"responseMimeType": "application/json"} if json_mode else {})}}
            r = await self._http.post(url, json=body, headers={"x-goog-api-key": key or ""})
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if s.llm_provider == "ollama":
            body = {"model": s.llm_model, "stream": False, "options": {"temperature": 0},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            if json_mode:
                body["format"] = "json"
            r = await self._http.post(f"{s.llm_base_url.rstrip('/')}/api/chat", json=body)
            r.raise_for_status()
            return r.json()["message"]["content"]
        raise LLMError("llm disabled")

    async def decompose(self, query: str) -> dict[str, Any]:
        if not self.enabled:
            raise LLMError("llm disabled")
        try:
            txt = await self._chat(INTENT_SYSTEM, f"Query: {query}", json_mode=True)
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise LLMError(f"llm call failed: {type(e).__name__}") from e
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            raise LLMError("no json in llm output")
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise LLMError("invalid json") from e

    async def explain(self, facts: str, needs: str) -> str:
        if not self.enabled:
            raise LLMError("llm disabled")
        try:
            return (await self._chat(EXPLAIN_SYSTEM, f"USER_NEEDS: {needs}\nPRODUCT_FACTS: {facts}", json_mode=False)).strip()
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise LLMError(f"llm call failed: {type(e).__name__}") from e
