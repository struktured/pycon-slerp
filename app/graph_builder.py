"""Orchestrate SerpApi searches + entity extraction to populate the graph."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Iterable

from . import db
from .entity_extractor import Entity, Relation, extract
from .serpapi_client import SerpApiClient

log = logging.getLogger(__name__)

SEED_QUERIES = [
    ("PyCon US 2026 schedule talks", "google"),
    ("PyCon 2026 keynote speakers", "google"),
    ("PyCon 2026 sponsors", "google"),
    ("PyCon 2026 tutorials", "google"),
    ("site:us.pycon.org 2026", "google"),
    ("PyCon 2026", "google_news"),
]


@dataclass
class IngestStats:
    queries_run: int = 0
    entities_added: int = 0
    relations_added: int = 0
    errors: list[str] = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


async def run_ingest(
    extra_queries: list[str] | None = None,
    use_claude: bool = False,
    expand_speakers: bool = True,
    max_speakers_to_expand: int = 8,
) -> IngestStats:
    db.init_db()
    stats = IngestStats()

    async with SerpApiClient() as client:
        # Seed pass
        seeds = list(SEED_QUERIES)
        for q in extra_queries or []:
            seeds.append((q, "google"))

        for query, engine in seeds:
            try:
                response = await client.search(query, engine=engine)
                stats.queries_run += 1
                _ingest_response(query, response, use_claude, stats)
            except Exception as exc:
                log.exception("seed query failed: %s", query)
                stats.errors.append(f"{query}: {exc}")

        # Expansion pass: pick top speakers, search for them
        if expand_speakers:
            speakers = _top_speakers(max_speakers_to_expand)
            for speaker_label in speakers:
                follow_up = f'"{speaker_label}" PyCon python'
                try:
                    response = await client.search(follow_up, engine="google")
                    stats.queries_run += 1
                    _ingest_response(follow_up, response, use_claude, stats)
                except Exception as exc:
                    log.exception("speaker expansion failed: %s", speaker_label)
                    stats.errors.append(f"{follow_up}: {exc}")

    return stats


def _ingest_response(query: str, response: dict, use_claude: bool, stats: IngestStats) -> None:
    organic = (
        response.get("organic_results")
        or response.get("news_results")
        or []
    )
    if not organic:
        return

    entities, relations = extract(query, organic, use_claude=use_claude)

    with db.connect() as conn:
        for ent in entities:
            db.upsert_node(conn, ent.id, ent.type, ent.label, ent.url, ent.metadata)
            stats.entities_added += 1

        for rel in relations:
            try:
                db.upsert_edge(conn, rel.source_id, rel.target_id, rel.edge_type)
                stats.relations_added += 1
            except Exception:
                # Source/target may not exist if extraction missed an entity; skip.
                pass

        # Attribute every node mentioned in this query to the query as a source
        for result in organic[:10]:
            url = result.get("link") or ""
            title = result.get("title") or ""
            snippet = result.get("snippet") or ""
            for ent in entities:
                if ent.url == url or (ent.label.lower() in (title + snippet).lower()):
                    db.add_source(conn, ent.id, url, title, snippet, query)


def _top_speakers(limit: int) -> list[str]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT n.label, COUNT(e.id) AS degree
               FROM nodes n
               LEFT JOIN edges e ON e.source_id = n.id OR e.target_id = n.id
               WHERE n.type = 'speaker'
               GROUP BY n.id
               ORDER BY degree DESC, n.label
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [r["label"] for r in rows]


def run_ingest_sync(**kwargs) -> IngestStats:
    return asyncio.run(run_ingest(**kwargs))
