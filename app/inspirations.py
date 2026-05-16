"""Talks, speakers, sponsors, and tech from PyCon US 2026 that this project draws on.

INSPIRATIONS list = the six talks attended (per the curator's notes), each
mapped to where in this codebase that talk's ideas / tech show up. Each entry
is pinnable from the sidebar into the graph as a real `talk` node with the
speaker(s) attached.

KNOWN_SPONSORS + KNOWN_SPEAKERS get pre-seeded into the graph on startup so
it never starts empty — and when later crawls find news/pages about them,
the same node collects the new sources.

The point: this app *participates in* the conference rather than just
indexing it.
"""
from __future__ import annotations


INSPIRATIONS: list[dict] = [
    {
        "tag": "pyscript",
        "talk": "Distributing AI with Python in the Browser: Edge Inference Flexibility Without Infra",
        "speakers": ["Fabio Pliger"],
        "affiliation": "Anaconda",
        "url": "https://us.pycon.org/2026/schedule/presentation/126/",
        "used_for": "In-browser LLM extraction via WebLLM + WebGPU (no API key)",
    },
    {
        "tag": "pep750",
        "talk": "PEP 750: t-strings — Safer and Smarter String Processing",
        "speakers": ["Vinicus Gubiana Ferreria"],
        "affiliation": "—",
        "url": "https://us.pycon.org/2026/",
        "used_for": "PEP 750-style structured query templating in app/query_template.py — safe SerpApi search-query interpolation for speaker names",
    },
    {
        "tag": "ai-contrib",
        "talk": "AI-Assisted Contributions and Maintainer Load",
        "speakers": ["Palao Melichorre"],
        "affiliation": "Django",
        "url": "https://us.pycon.org/2026/",
        "used_for": "Multi-backend extraction (heuristic / Claude / WebLLM) — judge the code, not the coder: each backend's output is merged on equal terms",
    },
    {
        "tag": "beyond-hype",
        "talk": "Beyond the Hype: A Pragmatic Look at How Developers Actually Use AI Tools",
        "speakers": [
            "Carol Willing", "Catherine Nelson", "Jelle Zijlstra",
            "Jodie Burchell", "Lais Carvalho", "Maike Scherer",
        ],
        "affiliation": "Panel — JetBrains, OpenAI, Pydantic, others",
        "url": "https://us.pycon.org/2026/",
        "used_for": "Ask-the-graph implements the agentic loop the panel described: generate plan → execute → evaluate → iterate, with the search results as the verifier",
    },
    {
        "tag": "cap1",
        "talk": "Building Enterprise Python Libraries in a Modern Way",
        "speakers": ["Dan Furman", "David Hoover"],
        "affiliation": "Capital One",
        "url": "https://us.pycon.org/2026/",
        "used_for": "Layered library abstraction — SerpApi engine wrappers → entity extractors → graph builder, each a clean layer (the Cap One ladder applied)",
    },
    {
        "tag": "swe-vs-de",
        "talk": "Why SWE Best Practices Fail in Data Engineering",
        "speakers": ["Constance Martineau"],
        "affiliation": "Astronomer",
        "url": "https://us.pycon.org/2026/",
        "used_for": "Provenance-first design — every node carries its source query and result snippet, because in data work the data is the variable, not the code",
    },
]


# Sponsors confirmed at PyCon US 2026. Pre-seeded into the graph so live
# crawls attach sources to existing nodes rather than create duplicates.
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
    {"label": "Anaconda", "url": "https://www.anaconda.com"},
    {"label": "JetBrains", "url": "https://www.jetbrains.com"},
    {"label": "Astronomer", "url": "https://www.astronomer.io"},
]


# Speakers from the talks attended (KNOWN_SPEAKERS) — also pre-seeded so any
# follow-up Scholar/web crawl on them attaches sources to an existing node.
KNOWN_SPEAKERS: list[dict] = [
    {"label": "Fabio Pliger", "affiliation": "Anaconda"},
    {"label": "Vinicus Gubiana Ferreria", "affiliation": "—"},
    {"label": "Palao Melichorre", "affiliation": "Django"},
    {"label": "Carol Willing", "affiliation": "PSF · Jupyter"},
    {"label": "Catherine Nelson", "affiliation": "—"},
    {"label": "Jelle Zijlstra", "affiliation": "OpenAI"},
    {"label": "Jodie Burchell", "affiliation": "JetBrains"},
    {"label": "Lais Carvalho", "affiliation": "Pydantic"},
    {"label": "Maike Scherer", "affiliation": "American Airlines"},
    {"label": "Dan Furman", "affiliation": "Capital One"},
    {"label": "David Hoover", "affiliation": "Capital One"},
    {"label": "Constance Martineau", "affiliation": "Astronomer"},
]


def seed_known_entities(conn) -> int:
    """Pre-load the PyCon 2026 event anchor + known sponsors + known speakers
    + the attended talks. Idempotent — safe to call repeatedly.
    """
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
        db.upsert_node(conn, node_id, "sponsor", s["label"], s.get("url"), {"seed": True})
        try:
            db.upsert_edge(conn, pycon_id, node_id, "sponsors")
        except Exception:
            pass
        count += 1

    # Speakers we know are on the program
    for sp in KNOWN_SPEAKERS:
        node_id = _id_for("speaker", sp["label"])
        db.upsert_node(
            conn, node_id, "speaker", sp["label"], None,
            {"seed": True, "affiliation": sp.get("affiliation")},
        )
        count += 1

    # The attended talks, linked to speakers and to the event
    for item in INSPIRATIONS:
        talk_label = (item.get("talk") or "")[:140]
        if not talk_label:
            continue
        talk_id = _id_for("talk", talk_label)
        db.upsert_node(
            conn, talk_id, "talk", talk_label, item.get("url"),
            {
                "seed": True,
                "affiliation": item.get("affiliation"),
                "used_for": item.get("used_for"),
                "tag": item.get("tag"),
            },
        )
        count += 1
        try:
            db.upsert_edge(conn, pycon_id, talk_id, "features")
        except Exception:
            pass
        for sp in item.get("speakers") or []:
            if not sp or sp == "—":
                continue
            sp_id = _id_for("speaker", sp)
            db.upsert_node(conn, sp_id, "speaker", sp, None, {"seed": True})
            try:
                db.upsert_edge(conn, sp_id, talk_id, "presents")
            except Exception:
                pass
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
