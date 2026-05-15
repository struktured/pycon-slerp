import hashlib
import os
from typing import Any

import httpx

from . import db

SERPAPI_BASE = "https://serpapi.com/search.json"


class SerpApiError(RuntimeError):
    pass


class SerpApiClient:
    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or os.environ.get("SERPAPI_API_KEY")
        if not self.api_key:
            raise SerpApiError("SERPAPI_API_KEY not set")
        self.client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> "SerpApiClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def search(self, query: str, engine: str = "google", **extra: Any) -> dict:
        params: dict[str, Any] = {
            "engine": engine,
            "q": query,
            "api_key": self.api_key,
            **extra,
        }
        key_material = f"{engine}|{query}|" + "|".join(
            f"{k}={v}" for k, v in sorted(extra.items())
        )
        query_hash = hashlib.sha256(key_material.encode()).hexdigest()

        cached = db.get_cached_search(query_hash)
        if cached is not None:
            return cached

        resp = await self.client.get(SERPAPI_BASE, params=params)
        if resp.status_code != 200:
            raise SerpApiError(f"SerpApi {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if "error" in data:
            raise SerpApiError(f"SerpApi error: {data['error']}")

        db.cache_search(query_hash, query, engine, data)
        return data

    @staticmethod
    def organic_results(response: dict) -> list[dict]:
        return response.get("organic_results", []) or []

    @staticmethod
    def news_results(response: dict) -> list[dict]:
        return response.get("news_results", []) or []

    @staticmethod
    def video_results(response: dict) -> list[dict]:
        return response.get("video_results", []) or []

    @staticmethod
    def knowledge_graph(response: dict) -> dict | None:
        return response.get("knowledge_graph")
