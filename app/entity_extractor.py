"""Extract entities (speakers, talks, repos, topics, papers) from SerpApi results.

Two paths:
- Heuristic: URL-pattern matching + keyword rules. No external deps. Always available.
- Claude: structured extraction via Anthropic SDK. Activates if ANTHROPIC_API_KEY is set.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Iterable
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


_GITHUB_PATH_RE = re.compile(r"^/([^/?#]+)(?:/([^/?#]+))?")
_YOUTUBE_VIDEO_PATH_RE = re.compile(r"^/watch")
_ARXIV_PATH_RE = re.compile(r"^/abs/([\d.v]+)")

# Reserved first-path segments on github.com that are not user accounts.
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


def heuristic_extract(query: str, organic: list[dict]) -> tuple[list[Entity], list[Relation]]:
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
        if not title or not link:
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

        # YouTube videos — host must be a youtube domain.
        if host in {"www.youtube.com", "youtube.com", "m.youtube.com"} and _YOUTUBE_VIDEO_PATH_RE.match(path):
            add(Entity(type="video", label=title, url=link,
                       metadata={"snippet": snippet, "platform": "youtube"}))
        elif host == "youtu.be" and len(path) > 1:
            add(Entity(type="video", label=title, url=link,
                       metadata={"snippet": snippet, "platform": "youtube"}))

        # arXiv papers — host must be arxiv.org.
        if host in {"arxiv.org", "www.arxiv.org"} and _ARXIV_PATH_RE.match(path):
            add(Entity(type="paper", label=title, url=link,
                       metadata={"snippet": snippet, "platform": "arxiv"}))

        # Speaker pages (heuristic: title looks like "Person Name - PyCon ...")
        speaker_match = re.match(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z'\-]+){1,3})\s*[-|–]", title)
        if speaker_match and "pycon" in (title + snippet).lower():
            name = speaker_match.group(1)
            add(Entity(type="speaker", label=name, url=link, metadata={"snippet": snippet}))

        # Topic extraction from any snippet
        for topic in _detect_topics(f"{title} {snippet}"):
            add(Entity(type="topic", label=topic))

    # Also surface generic results as "page" nodes so the graph isn't sparse
    for result in organic[:5]:
        title = (result.get("title") or "").strip()
        link = result.get("link") or ""
        if title and link and not any(
            pat in link for pat in ("pycon.org", "github.com", "youtube.com", "arxiv.org")
        ):
            add(Entity(type="article", label=title[:80], url=link,
                       metadata={"snippet": (result.get("snippet") or "")[:200]}))

    # Link the query itself as a topic-ish anchor if it mentions PyCon
    if "pycon" in query.lower():
        pycon = add(Entity(type="event", label="PyCon 2026"))
        for ent in list(entities.values()):
            if ent.type in {"talk", "speaker", "video"} and ent is not pycon:
                relations.append(Relation(pycon.label, "event", ent.label, ent.type, "features"))

    return list(entities.values()), relations


def _id_for(type_: str, label: str) -> str:
    return hashlib.sha1(f"{type_}|{normalize(label)}".encode()).hexdigest()[:16]


def _detect_topics(text: str) -> set[str]:
    t = text.lower()
    return {kw for kw in _TOPIC_KEYWORDS if kw in t}


# -- Optional Claude path -----------------------------------------------------

CLAUDE_AVAILABLE = bool(os.environ.get("ANTHROPIC_API_KEY"))


def claude_extract(query: str, organic: list[dict]) -> tuple[list[Entity], list[Relation]]:
    if not CLAUDE_AVAILABLE:
        return heuristic_extract(query, organic)
    try:
        from anthropic import Anthropic
    except ImportError:
        return heuristic_extract(query, organic)

    client = Anthropic()
    compact_results = [
        {"title": r.get("title", ""), "link": r.get("link", ""), "snippet": r.get("snippet", "")}
        for r in organic[:10]
    ]

    prompt = f"""Extract entities and relationships from these search results.

Query: {query}

Results:
{json.dumps(compact_results, indent=2)}

Return JSON with this exact shape:
{{
  "entities": [{{"type": "speaker|talk|topic|repo|paper|video|sponsor|event|article", "label": "...", "url": "optional"}}],
  "relations": [{{"source_label": "...", "source_type": "...", "target_label": "...", "target_type": "...", "edge_type": "presents|about|authored|works_on|sponsors|features|references"}}]
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
        return heuristic_extract(query, organic)

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
    return entities, relations


def extract(query: str, organic: list[dict], use_claude: bool = False) -> tuple[list[Entity], list[Relation]]:
    if use_claude and CLAUDE_AVAILABLE:
        return claude_extract(query, organic)
    return heuristic_extract(query, organic)
