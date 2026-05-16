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

    # -- Result accessors --------------------------------------------------
    # Each engine has its own response shape. These helpers pull the
    # "primary list of hits" out in a consistent way.

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
    def local_results(response: dict) -> list[dict]:
        local = response.get("local_results")
        if isinstance(local, dict):
            return local.get("places", []) or []
        return local or []

    @staticmethod
    def places_results(response: dict) -> list[dict]:
        return response.get("places_results", []) or []

    @staticmethod
    def related_searches(response: dict) -> list[dict]:
        return response.get("related_searches", []) or []

    @staticmethod
    def related_questions(response: dict) -> list[dict]:
        # SerpApi exposes "People Also Ask" as `related_questions`.
        return response.get("related_questions", []) or []

    @staticmethod
    def knowledge_graph(response: dict) -> dict | None:
        return response.get("knowledge_graph")

    @staticmethod
    def inline_videos(response: dict) -> list[dict]:
        return response.get("inline_videos", []) or []

    @staticmethod
    def primary_hits(response: dict, engine: str) -> list[dict]:
        """Normalize the main result list across engines into a single list
        of `{title, link, snippet, ...}` dicts."""
        if engine == "youtube":
            return [
                {
                    "title": v.get("title") or "",
                    "link": v.get("link") or "",
                    "snippet": v.get("description") or "",
                    "_youtube": v,
                }
                for v in SerpApiClient.video_results(response)
            ]
        if engine in {"google_local", "google_maps"}:
            return [
                {
                    "title": p.get("title") or "",
                    "link": p.get("website") or p.get("link") or "",
                    "snippet": p.get("description") or p.get("type") or "",
                    "_local": p,
                }
                for p in SerpApiClient.local_results(response) + SerpApiClient.places_results(response)
            ]
        if engine == "google_scholar":
            return [
                {
                    "title": r.get("title") or "",
                    "link": r.get("link") or "",
                    "snippet": r.get("snippet") or "",
                    "_scholar": r,
                }
                for r in SerpApiClient.organic_results(response)
            ]
        if engine == "google_news":
            return SerpApiClient.news_results(response)
        # default: standard google
        return SerpApiClient.organic_results(response)
