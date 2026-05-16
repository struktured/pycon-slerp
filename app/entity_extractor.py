"""Extract entities (speakers, talks, repos, topics, papers, places, questions)
from SerpApi results.

Two paths:
- Heuristic: URL-pattern matching + engine-aware rules. No external deps. Always available.
- Claude: structured extraction via Anthropic SDK. Activates if ANTHROPIC_API_KEY is set.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class Entity:
    type: str
    label: str
    url: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        key = f"{self.type}|{normalize(self.label)}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]


@dataclass
class Relation:
    source_label: str
    source_type: str
    target_label: str
    target_type: str
    edge_type: str

    @property
    def source_id(self) -> str:
        return hashlib.sha1(f"{self.source_type}|{normalize(self.source_label)}".encode()).hexdigest()[:16]

    @property
    def target_id(self) -> str:
        return hashlib.sha1(f"{self.target_type}|{normalize(self.target_label)}".encode()).hexdigest()[:16]


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _id_for(type_: str, label: str) -> str:
    return hashlib.sha1(f"{type_}|{normalize(label)}".encode()).hexdigest()[:16]


_GITHUB_PATH_RE = re.compile(r"^/([^/?#]+)(?:/([^/?#]+))?")
_YOUTUBE_VIDEO_PATH_RE = re.compile(r"^/watch")
_ARXIV_PATH_RE = re.compile(r"^/abs/([\d.v]+)")

_GITHUB_NON_USER_PATHS = {
    "orgs", "sponsors", "topics", "marketplace", "settings", "notifications",
    "search", "pulls", "issues", "explore", "trending", "collections",
    "codespaces", "features", "about", "pricing", "enterprise", "security",
    "login", "join", "new", "site", "readme",
}

_TOPIC_KEYWORDS = {
    "async", "asyncio", "type hints", "typing", "fastapi", "django", "flask",
    "pytest", "testing", "data science", "machine learning", "ml", "ai",
    "llm", "agents", "rag", "embeddings", "pandas", "numpy", "polars",
    "duckdb", "sqlalchemy", "pydantic", "rust", "performance", "concurrency",
    "packaging", "uv", "poetry", "ruff", "mypy", "security", "supply chain",
    "observability", "logging", "deployment", "docker", "kubernetes",
    "wasm", "webassembly", "jupyter", "scientific computing", "education",
    "open source", "community", "diversity", "accessibility",
}


def heuristic_extract(query: str, organic: list[dict], engine: str = "google") -> tuple[list[Entity], list[Relation]]:
    entities: dict[str, Entity] = {}
    relations: list[Relation] = []

    def add(e: Entity) -> Entity:
        if e.id in entities:
            existing = entities[e.id]
            existing.url = existing.url or e.url
            existing.metadata.update(e.metadata)
            return existing
        entities[e.id] = e
        return e

    for result in organic:
        title = (result.get("title") or "").strip()
        link = result.get("link") or ""
        snippet = (result.get("snippet") or "").strip()
        if not title:
            continue

        # Engine-specific rich extraction (uses raw payload).
        if yt := result.get("_youtube"):
            _extract_youtube(yt, title, link, snippet, add, relations)
            continue
        if local := result.get("_local"):
            _extract_local(local, title, link, add, relations)
            continue
        if sch := result.get("_scholar"):
            _extract_scholar(sch, title, link, snippet, add, relations)
            continue

        if not link:
            continue

        parsed = urlparse(link)
        host = parsed.netloc.lower()
        path = parsed.path

        # Talk pages on pycon.org
        if "pycon.org" in host and ("/talk" in path or "/schedule" in path or "/speakers" in path):
            talk = add(Entity(type="talk", label=title, url=link,
                              metadata={"snippet": snippet, "source": "pycon.org"}))
            for topic in _detect_topics(f"{title} {snippet}"):
                t = add(Entity(type="topic", label=topic))
                relations.append(Relation(talk.label, "talk", t.label, "topic", "about"))

        # GitHub repos and users — host must be exactly github.com (no subdomains).
        if host == "github.com":
            m = _GITHUB_PATH_RE.match(path)
            if m:
                user, repo = m.group(1), m.group(2)
                if user and user.lower() not in _GITHUB_NON_USER_PATHS:
                    if not repo:
                        add(Entity(type="speaker", label=user,
                                   url=f"https://github.com/{user}",
                                   metadata={"github": user}))
                    else:
                        repo_label = f"{user}/{repo}"
                        add(Entity(type="repo", label=repo_label,
                                   url=f"https://github.com/{user}/{repo}",
                                   metadata={"snippet": snippet}))
                        if user_node := entities.get(_id_for("speaker", user)):
                            relations.append(Relation(user_node.label, "speaker",
                                                      repo_label, "repo", "authored"))

        # YouTube videos found via google.com searches.
        if host in {"www.youtube.com", "youtube.com", "m.youtube.com"} and _YOUTUBE_VIDEO_PATH_RE.match(path):
            add(Entity(type="video", label=title, url=link,
                       metadata={"snippet": snippet, "platform": "youtube"}))
        elif host == "youtu.be" and len(path) > 1:
            add(Entity(type="video", label=title, url=link,
                       metadata={"snippet": snippet, "platform": "youtube"}))

        # arXiv papers
        if host in {"arxiv.org", "www.arxiv.org"} and _ARXIV_PATH_RE.match(path):
            add(Entity(type="paper", label=title, url=link,
                       metadata={"snippet": snippet, "platform": "arxiv"}))

        # Reddit threads — surface as `discussion` so they aren't lost in `article`.
        if host.endswith("reddit.com"):
            add(Entity(type="discussion", label=title[:90], url=link,
                       metadata={"snippet": snippet, "platform": "reddit"}))
            for topic in _detect_topics(f"{title} {snippet}"):
                t = add(Entity(type="topic", label=topic))
                relations.append(Relation(title[:90], "discussion", t.label, "topic", "about"))

        # Speaker pages (heuristic: title looks like "Person Name - PyCon ...")
        speaker_match = re.match(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z'\-]+){1,3})\s*[-|–]", title)
        if speaker_match and "pycon" in (title + snippet).lower():
            name = speaker_match.group(1)
            add(Entity(type="speaker", label=name, url=link, metadata={"snippet": snippet}))

        # Topic extraction from any snippet
        for topic in _detect_topics(f"{title} {snippet}"):
            add(Entity(type="topic", label=topic))

    # Surface generic results as `article` so the graph isn't sparse
    for result in organic[:5]:
        title = (result.get("title") or "").strip()
        link = result.get("link") or ""
        if not title or not link or any(k in result for k in ("_youtube", "_local", "_scholar")):
            continue
        if any(pat in link for pat in ("pycon.org", "github.com", "youtube.com", "arxiv.org", "reddit.com")):
            continue
        add(Entity(type="article", label=title[:80], url=link,
                   metadata={"snippet": (result.get("snippet") or "")[:200]}))

    # Anchor the conference event and link feature nodes
    if "pycon" in query.lower() or engine in {"google_local"}:
        pycon = add(Entity(type="event", label="PyCon 2026"))
        for ent in list(entities.values()):
            if ent.type in {"talk", "speaker", "video", "place"} and ent is not pycon:
                edge = "near" if ent.type == "place" else "features"
                relations.append(Relation(pycon.label, "event", ent.label, ent.type, edge))

    return list(entities.values()), relations


# -- Engine-specific extractors -----------------------------------------------

def _extract_youtube(yt: dict, title: str, link: str, snippet: str, add, relations) -> None:
    views = yt.get("views")
    channel = yt.get("channel") or {}
    channel_name = (channel.get("name") if isinstance(channel, dict) else channel) or ""
    meta = {
        "platform": "youtube",
        "views": views,
        "channel": channel_name,
        "published": yt.get("published_date"),
        "length": yt.get("length"),
        "snippet": snippet,
    }
    video = add(Entity(type="video", label=title[:120], url=link, metadata=meta))
    if channel_name:
        speaker = add(Entity(type="speaker", label=channel_name,
                             url=channel.get("link") if isinstance(channel, dict) else None,
                             metadata={"platform": "youtube"}))
        relations.append(Relation(speaker.label, "speaker", video.label, "video", "presents"))
    for topic in _detect_topics(f"{title} {snippet}"):
        t = add(Entity(type="topic", label=topic))
        relations.append(Relation(video.label, "video", t.label, "topic", "about"))


def _extract_local(local: dict, title: str, link: str, add, relations) -> None:
    addr = local.get("address") or ""
    rating = local.get("rating")
    reviews = local.get("reviews")
    place_type = local.get("type")
    if not place_type:
        types = local.get("types")
        if isinstance(types, list) and types:
            place_type = types[0]
    coords = local.get("gps_coordinates") or {}
    meta = {
        "platform": "google_local",
        "address": addr,
        "rating": rating,
        "reviews": reviews,
        "type": place_type,
        "lat": coords.get("latitude"),
        "lng": coords.get("longitude"),
        "hours": local.get("hours"),
        "phone": local.get("phone"),
    }
    place = add(Entity(type="place", label=title[:90], url=link or None, metadata=meta))
    # Auto-link to the PyCon event so it shows up near the conference
    pycon = add(Entity(type="event", label="PyCon 2026"))
    relations.append(Relation(pycon.label, "event", place.label, "place", "near"))


def _extract_scholar(sch: dict, title: str, link: str, snippet: str, add, relations) -> None:
    pub = sch.get("publication_info") or {}
    authors_raw = pub.get("authors") or []
    cited_by = ((sch.get("inline_links") or {}).get("cited_by") or {}).get("total")
    summary = pub.get("summary") or ""
    meta = {
        "platform": "google_scholar",
        "snippet": snippet or summary,
        "cited_by": cited_by,
        "year": _extract_year(summary),
        "venue": summary,
    }
    paper = add(Entity(type="paper", label=title[:140], url=link, metadata=meta))
    for a in authors_raw:
        if not isinstance(a, dict):
            continue
        name = a.get("name") or ""
        if not name:
            continue
        speaker = add(Entity(type="speaker", label=name,
                             url=a.get("link"), metadata={"platform": "google_scholar"}))
        relations.append(Relation(speaker.label, "speaker", paper.label, "paper", "authored"))
    for topic in _detect_topics(f"{title} {snippet} {summary}"):
        t = add(Entity(type="topic", label=topic))
        relations.append(Relation(paper.label, "paper", t.label, "topic", "about"))


_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _extract_year(text: str) -> str | None:
    m = _YEAR_RE.search(text or "")
    return m.group(0) if m else None


def _detect_topics(text: str) -> set[str]:
    t = text.lower()
    return {kw for kw in _TOPIC_KEYWORDS if kw in t}


# -- Related searches & PAA → free graph edges -------------------------------

def extract_related(query: str, response: dict) -> tuple[list[Entity], list[Relation]]:
    """Turn People-Also-Ask + Related Searches into question/topic nodes and edges.

    These come back on virtually every SerpApi Google response — they're a
    nearly-free way to densify the graph with real Google co-occurrence signal.
    """
    entities: dict[str, Entity] = {}
    relations: list[Relation] = []

    def add(e: Entity) -> Entity:
        if e.id in entities:
            return entities[e.id]
        entities[e.id] = e
        return e

    # Anchor topic from the query (use the query string as a coarse topic)
    query_topics = _detect_topics(query)

    for q in (response.get("related_questions") or [])[:10]:
        text = (q.get("question") or "").strip()
        if not text:
            continue
        snippet = (q.get("snippet") or "").strip()
        link = q.get("link") or ""
        question = add(Entity(type="question", label=text[:140], url=link or None,
                              metadata={"snippet": snippet, "source": "people_also_ask"}))
        for topic in _detect_topics(f"{text} {snippet}") | query_topics:
            t = add(Entity(type="topic", label=topic))
            relations.append(Relation(question.label, "question", t.label, "topic", "about"))

    for r in (response.get("related_searches") or [])[:10]:
        text = (r.get("query") or r.get("name") or "").strip()
        if not text:
            continue
        related_topics = _detect_topics(text)
        # If the related-search phrase contains a known topic, link query topics → that topic
        for rt in related_topics:
            target = add(Entity(type="topic", label=rt))
            for qt in query_topics:
                if qt == rt:
                    continue
                src = add(Entity(type="topic", label=qt))
                relations.append(Relation(src.label, "topic", target.label, "topic", "related"))

    return list(entities.values()), relations


# -- Optional Claude path -----------------------------------------------------

CLAUDE_AVAILABLE = bool(os.environ.get("ANTHROPIC_API_KEY"))


def claude_extract(query: str, organic: list[dict], engine: str = "google") -> tuple[list[Entity], list[Relation]]:
    if not CLAUDE_AVAILABLE:
        return heuristic_extract(query, organic, engine=engine)
    try:
        from anthropic import Anthropic
    except ImportError:
        return heuristic_extract(query, organic, engine=engine)

    client = Anthropic()
    compact_results = [
        {"title": r.get("title", ""), "link": r.get("link", ""), "snippet": r.get("snippet", "")}
        for r in organic[:10]
    ]

    prompt = f"""Extract entities and relationships from these search results.

Query: {query}
Engine: {engine}

Results:
{json.dumps(compact_results, indent=2)}

Return JSON with this exact shape:
{{
  "entities": [{{"type": "speaker|talk|topic|repo|paper|video|sponsor|event|article|place|question|discussion", "label": "...", "url": "optional"}}],
  "relations": [{{"source_label": "...", "source_type": "...", "target_label": "...", "target_type": "...", "edge_type": "presents|about|authored|works_on|sponsors|features|references|near|related"}}]
}}

Rules:
- Only extract entities clearly identifiable from the results.
- Speaker names are full names (e.g. "Guido van Rossum"), not handles.
- Topics are short noun phrases (e.g. "async", "type hints").
- Talks are full talk titles.
- Don't invent relationships not implied by the snippets.

Return only JSON, no prose."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
        data = json.loads(text)
    except Exception:
        return heuristic_extract(query, organic, engine=engine)

    entities = [
        Entity(type=e["type"], label=e["label"], url=e.get("url"), metadata={"source": "claude"})
        for e in data.get("entities", []) if e.get("label") and e.get("type")
    ]
    relations = [
        Relation(
            source_label=r["source_label"], source_type=r["source_type"],
            target_label=r["target_label"], target_type=r["target_type"],
            edge_type=r["edge_type"],
        )
        for r in data.get("relations", [])
        if all(r.get(k) for k in ("source_label", "source_type", "target_label", "target_type", "edge_type"))
    ]
    # Merge with heuristic so both signals contribute
    h_ent, h_rel = heuristic_extract(query, organic, engine=engine)
    return entities + h_ent, relations + h_rel


def extract(query: str, organic: list[dict], use_claude: bool = False, engine: str = "google") -> tuple[list[Entity], list[Relation]]:
    if use_claude and CLAUDE_AVAILABLE:
        return claude_extract(query, organic, engine=engine)
    return heuristic_extract(query, organic, engine=engine)
