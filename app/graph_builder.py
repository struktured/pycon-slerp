"""Orchestrate SerpApi searches + entity extraction to populate the graph."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import anyio

from . import db
from .entity_extractor import Entity, Relation, _id_for, extract, extract_related
from .inspirations import seed_known_entities
from .query_template import safe_query
from .serpapi_client import SerpApiClient

log = logging.getLogger(__name__)

# Multi-engine seed plan: each tuple is (query, engine, extra_params).
# This is what makes the graph cross-source: same conference, six different
# SerpApi engines, joined on entity identity.
SEED_QUERIES: list[tuple[str, str, dict]] = [
    ("PyCon US 2026 schedule talks", "google", {}),
    ("PyCon 2026 keynote speakers", "google", {}),
    ("PyCon 2026 sponsors", "google", {}),
    ("PyCon 2026 tutorials", "google", {}),
    ("site:us.pycon.org 2026", "google", {}),
    ("PyCon 2026", "google_news", {}),
    # YouTube — talk recordings (PyCon 2025 is what's actually online before 2026)
    ("PyCon 2025 talk", "youtube", {}),
    ("PyCon 2025 keynote", "youtube", {}),
    # Scholar — papers by PyCon-adjacent authors / on Python tooling
    ("python pep tooling", "google_scholar", {"hl": "en"}),
    # Long Beach venue intel
    ("coffee near Long Beach Convention Center", "google_local", {"location": "Long Beach,California,United States"}),
    ("restaurants near Long Beach Convention Center", "google_local", {"location": "Long Beach,California,United States"}),
    # Reddit discussion
    ("site:reddit.com PyCon 2026", "google", {}),
]


@dataclass
class IngestStats:
    queries_run: int = 0
    entities_added: int = 0
    relations_added: int = 0
    questions_added: int = 0
    kg_cards_captured: int = 0
    engines: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def bootstrap() -> None:
    """One-shot init: schema + pre-seed the known PyCon 2026 lineup so the
    graph is never empty. Safe to call repeatedly."""
    db.init_db()
    with db.connect() as conn:
        seed_known_entities(conn)


async def run_ingest(
    extra_queries: list[str] | None = None,
    use_claude: bool = False,
    expand_speakers: bool = True,
    max_speakers_to_expand: int = 8,
    engines: list[str] | None = None,
) -> IngestStats:
    """Run the full multi-engine ingest.

    Searches are fired in parallel via anyio task groups (structured
    concurrency — credit to the PyCon talk on async-IO + agents). Response
    processing is then serialized to keep the single SQLite writer happy.
    """
    bootstrap()
    stats = IngestStats()

    async with SerpApiClient() as client:
        seeds = list(SEED_QUERIES)
        for q in extra_queries or []:
            seeds.append((_scope_to_pycon(q), "google", {}))
        if engines:
            seeds = [s for s in seeds if s[1] in engines]

        await _run_parallel(client, seeds, use_claude, stats)

        # Expansion pass: pick top speakers, follow them in parallel.
        if expand_speakers:
            speakers = _top_speakers(max_speakers_to_expand)
            follow_ups: list[tuple[str, str, dict]] = []
            for speaker_label in speakers:
                # PEP 750-style safe templating — credit: Vinicus Gubiana
                # Ferreria's PyCon 2026 t-strings talk. Keeps stray quotes
                # or whitespace in a speaker name from breaking the query.
                follow_ups.append((
                    safe_query('"{speaker}" PyCon python', speaker=speaker_label),
                    "google", {},
                ))
                follow_ups.append((
                    safe_query('"{speaker}"', speaker=speaker_label),
                    "google_scholar", {},
                ))
            await _run_parallel(client, follow_ups, use_claude, stats)

    return stats


async def _run_parallel(
    client: SerpApiClient,
    plan: list[tuple[str, str, dict]],
    use_claude: bool,
    stats: IngestStats,
) -> None:
    """Fire `plan` searches concurrently with anyio, then ingest serially."""
    results: list[tuple[str, str, dict | None, Exception | None]] = []

    async def _one(query: str, engine: str, params: dict) -> None:
        try:
            response = await client.search(query, engine=engine, **params)
            results.append((query, engine, response, None))
        except Exception as exc:
            log.exception("query failed: [%s] %s", engine, query)
            results.append((query, engine, None, exc))

    async with anyio.create_task_group() as tg:
        for query, engine, params in plan:
            tg.start_soon(_one, query, engine, params)

    for query, engine, response, exc in results:
        if exc is not None:
            stats.errors.append(f"[{engine}] {query}: {exc}")
            continue
        stats.queries_run += 1
        stats.engines[engine] = stats.engines.get(engine, 0) + 1
        _ingest_response(query, engine, response, use_claude, stats)


def _ingest_response(query: str, engine: str, response: dict, use_claude: bool, stats: IngestStats) -> None:
    organic = SerpApiClient.primary_hits(response, engine)

    entities, relations = ([], [])
    if organic:
        entities, relations = extract(query, organic, use_claude=use_claude, engine=engine)

    # Related searches + People-Also-Ask → free density (Google engines only)
    rel_entities, rel_relations = extract_related(query, response)
    entities = entities + rel_entities
    relations = relations + rel_relations
    stats.questions_added += sum(1 for e in rel_entities if e.type == "question")

    # Capture a Knowledge Graph card if present
    kg = response.get("knowledge_graph")
    kg_for_label: dict[str, dict] = {}
    if isinstance(kg, dict) and kg.get("title"):
        kg_card = _shape_kg_card(kg)
        kg_for_label[kg["title"].strip().lower()] = kg_card
        stats.kg_cards_captured += 1

    with db.connect() as conn:
        for ent in entities:
            # Attach KG card if this entity matches the KG title
            if ent.label.strip().lower() in kg_for_label:
                ent.metadata["kg"] = kg_for_label[ent.label.strip().lower()]
            db.upsert_node(conn, ent.id, ent.type, ent.label, ent.url, ent.metadata)
            stats.entities_added += 1

        for rel in relations:
            try:
                db.upsert_edge(conn, rel.source_id, rel.target_id, rel.edge_type)
                stats.relations_added += 1
            except Exception:
                pass

        # Attribute every node mentioned in this query to the query as a source
        for result in organic[:10]:
            url = result.get("link") or ""
            title = result.get("title") or ""
            snippet = result.get("snippet") or ""
            if not url:
                continue
            for ent in entities:
                if ent.url == url or (ent.label and ent.label.lower() in (title + snippet).lower()):
                    db.add_source(conn, ent.id, url, title, snippet, f"[{engine}] {query}")


def _shape_kg_card(kg: dict) -> dict:
    """Slim a SerpApi knowledge_graph payload down to the bits the UI uses."""
    image = kg.get("image") or kg.get("thumbnail")
    header_images = kg.get("header_images")
    if not image and isinstance(header_images, list) and header_images:
        image = header_images[0].get("image") if isinstance(header_images[0], dict) else None
    return {
        "title": kg.get("title"),
        "type": kg.get("type"),
        "description": kg.get("description") or kg.get("snippet"),
        "image": image,
        "source": kg.get("source"),
        "website": kg.get("website"),
        "facts": _kg_facts(kg),
    }


def _kg_facts(kg: dict) -> list[dict]:
    """Pull simple key→value attributes out of a knowledge_graph block."""
    facts: list[dict] = []
    skip = {"title", "type", "description", "snippet", "image", "header_images",
            "source", "website", "kgmid", "knowledge_graph_search_link",
            "serpapi_knowledge_graph_search_link", "thumbnail", "tabs"}
    for k, v in kg.items():
        if k in skip:
            continue
        if isinstance(v, (str, int, float)):
            label = k.replace("_", " ").strip()
            facts.append({"label": label, "value": str(v)})
        elif isinstance(v, list) and v and isinstance(v[0], (str, int, float)):
            label = k.replace("_", " ").strip()
            facts.append({"label": label, "value": ", ".join(str(x) for x in v[:5])})
    return facts[:8]


def _scope_to_pycon(query: str) -> str:
    """Auto-scope a user-supplied extra query to PyCon/Python context.

    The whole app is about PyCon 2026 — users shouldn't have to repeat that
    in every search. Only adds tokens that aren't already present so a query
    like "pycon 2026 lightning talks" stays unchanged.
    """
    q = query.strip()
    lower = q.lower()
    if not q:
        return q
    additions: list[str] = []
    if "pycon" not in lower:
        additions.append("PyCon 2026")
    if "python" not in lower and "py " not in lower:
        additions.append("python")
    return " ".join([q, *additions]) if additions else q


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


# -- Ask the graph ------------------------------------------------------------

@dataclass
class AskResult:
    plan: list[dict]
    stats: IngestStats
    summary: str


async def ask_the_graph(question: str, use_claude: bool = True) -> AskResult:
    """Take a natural-language question, ask Claude to write a SerpApi search
    plan, execute it, and inject the results into the graph live.

    Falls back to a heuristic plan if Claude isn't available.
    """
    plan = _plan_searches(question, use_claude=use_claude)
    stats = IngestStats()

    plan_tuples: list[tuple[str, str, dict]] = []
    for step in plan:
        q = step.get("query") or ""
        engine = step.get("engine") or "google"
        params = step.get("params") or {}
        if q:
            plan_tuples.append((q, engine, params))

    async with SerpApiClient() as client:
        await _run_parallel(client, plan_tuples, use_claude, stats)

    summary = (
        f"Ran {stats.queries_run} searches across "
        f"{len(stats.engines)} engine(s); added {stats.entities_added} entities "
        f"and {stats.relations_added} edges."
    )
    return AskResult(plan=plan, stats=stats, summary=summary)


_DEFAULT_PLAN_FALLBACK = [
    {"engine": "google", "query": "PyCon 2026 {q}"},
    {"engine": "google_news", "query": "{q}"},
]


def _plan_searches(question: str, use_claude: bool) -> list[dict]:
    """Use Claude to design a SerpApi search plan, or fall back to a template."""
    if not use_claude or not _claude_available():
        return _heuristic_plan(question)

    try:
        from anthropic import Anthropic
        client = Anthropic()
        prompt = f"""You are a SerpApi search planner for a PyCon 2026 knowledge graph
(PyCon US 2026, May 13–19, Long Beach Convention Center).

User's question: {question}

Return JSON: an array of 3–6 SerpApi search steps that, together, best answer
the question by adding rich entities to the graph. Use a mix of engines to
cross-reference sources.

Available engines and when to use them:
- "google": general web, talk pages, PEPs, news, sponsor pages
- "google_news": time-sensitive news / announcements
- "google_scholar": papers by speakers, academic context
- "youtube": recorded talks, channels, keynotes
- "google_local": physical venue intel (Long Beach), needs `params.location`

Each step is {{"engine": "...", "query": "...", "params": {{...}}}}.
For google_local always pass `{{"params": {{"location": "Long Beach,California,United States"}}}}`.

Return ONLY a JSON array — no prose, no markdown fences."""
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        import json as _json
        import re as _re
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = _re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=_re.MULTILINE)
        plan = _json.loads(text)
        if isinstance(plan, list):
            return [p for p in plan if isinstance(p, dict) and p.get("query")][:6]
    except Exception:
        log.exception("plan generation failed; falling back")

    return _heuristic_plan(question)


def _claude_available() -> bool:
    import os
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _heuristic_plan(question: str) -> list[dict]:
    q = question.strip()
    return [
        {"engine": "google", "query": f"PyCon 2026 {q}", "params": {}},
        {"engine": "google_news", "query": q, "params": {}},
        {"engine": "youtube", "query": f"PyCon {q}", "params": {}},
    ]


def run_ingest_sync(**kwargs) -> IngestStats:
    return asyncio.run(run_ingest(**kwargs))
