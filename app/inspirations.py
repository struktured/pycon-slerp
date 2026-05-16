"""Talks, sponsors, and tech from PyCon US 2026 that this project draws on.

Each entry in INSPIRATIONS shows up in the sidebar under "Powered by PyCon
talks" and can be pinned into the graph as a real `talk` node with the
speaker(s) attached.

KNOWN_SPONSORS is pre-seeded into the graph on startup so it never starts
empty — and when later crawls find news/pages about them, the same node
collects the new sources.

The point: this app *participates in* the conference rather than just
indexing it.

Edit freely as you confirm names from the actual PyCon 2026 program.
"""
from __future__ import annotations

INSPIRATIONS: list[dict] = [
    {
        "tag": "pyscript",
        "talk": "PyScript & in-browser Python — running agents at the edge",
        "speakers": ["Antonio Cuni", "Fabio Pliger"],
        "affiliation": "Anaconda",
        "url": "https://us.pycon.org/2026/",
        "used_for": "In-browser LLM extraction (WebLLM) — no API key required",
    },
    {
        "tag": "granian",
        "talk": "Containerization, async I/O, and agent-friendly Python services",
        "speakers": ["Giovanni Barillari"],  # Granian author — edit if you know the actual speaker
        "affiliation": "—",
        "url": "https://us.pycon.org/2026/",
        "used_for": "Granian as the production ASGI server (Rust-powered, container-friendly)",
    },
    {
        "tag": "anyio",
        "talk": "Structured concurrency for Python agents",
        "speakers": ["—"],
        "affiliation": "—",
        "url": "https://us.pycon.org/2026/",
        "used_for": "anyio task groups to parallelize the multi-engine SerpApi ingest",
    },
]


# Sponsors and vendors confirmed at PyCon US 2026. Pre-seeded into the graph
# so it boots with substance and matches incoming search results when the
# crawl runs.
KNOWN_SPONSORS: list[dict] = [
    {"label": "Temporal", "url": "https://temporal.io"},
    {"label": "GitHub", "url": "https://github.com"},
    {"label": "Pydantic", "url": "https://pydantic.dev"},
    {"label": "Streamlit", "url": "https://streamlit.io"},
    {"label": "kraken.tech", "url": "https://kraken.tech"},
    {"label": "Jane Street", "url": "https://janestreet.com"},
    {"label": "Hudson River Trading", "url": "https://www.hudsonrivertrading.com"},
    {"label": "OpenAI", "url": "https://openai.com"},
    {"label": "Capital One", "url": "https://www.capitalone.com"},
    {"label": "Point72", "url": "https://point72.com"},
]


def seed_known_entities(conn) -> int:
    """Pre-load the PyCon 2026 event anchor + known sponsors. Idempotent."""
    from . import db
    from .entity_extractor import _id_for

    count = 0
    pycon_id = _id_for("event", "PyCon 2026")
    db.upsert_node(
        conn, pycon_id, "event", "PyCon 2026",
        "https://us.pycon.org/2026/",
        {"seed": True, "venue": "Long Beach Convention Center"},
    )
    count += 1
    for s in KNOWN_SPONSORS:
        node_id = _id_for("sponsor", s["label"])
        db.upsert_node(
            conn, node_id, "sponsor", s["label"], s.get("url"),
            {"seed": True},
        )
        try:
            db.upsert_edge(conn, pycon_id, node_id, "sponsors")
        except Exception:
            pass
        count += 1
    return count


def pinnable_entities(item: dict) -> list[dict]:
    """Return entity dicts to inject when the user pins an inspiration."""
    out: list[dict] = []
    talk = item.get("talk") or ""
    if talk:
        out.append({
            "type": "talk",
            "label": talk[:140],
            "url": item.get("url"),
            "metadata": {
                "source": "inspirations",
                "affiliation": item.get("affiliation"),
                "used_for": item.get("used_for"),
            },
        })
    for sp in item.get("speakers", []) or []:
        if sp and sp != "—":
            out.append({
                "type": "speaker",
                "label": sp,
                "url": item.get("url"),
                "metadata": {"source": "inspirations", "affiliation": item.get("affiliation")},
            })
    return out


def pinnable_relations(item: dict) -> list[dict]:
    talk = item.get("talk") or ""
    rels = []
    if not talk:
        return rels
    for sp in item.get("speakers", []) or []:
        if sp and sp != "—":
            rels.append({
                "source_label": sp,
                "source_type": "speaker",
                "target_label": talk[:140],
                "target_type": "talk",
                "edge_type": "presents",
            })
    rels.append({
        "source_label": "PyCon 2026",
        "source_type": "event",
        "target_label": talk[:140],
        "target_type": "talk",
        "edge_type": "features",
    })
    return rels
