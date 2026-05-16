"""Claude-generated 2-sentence summary cards for nodes.

Summaries are cached in nodes.metadata.summary so a given node is only billed once.
"""
from __future__ import annotations

import json
import logging
import os

from . import db

log = logging.getLogger(__name__)


def claude_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def get_or_create_summary(node_id: str) -> dict:
    """Return {summary, cached, available}. Generates lazily on first call."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT type, label, url, metadata FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if not row:
            return {"summary": None, "cached": False, "available": False, "error": "node not found"}
        meta = json.loads(row["metadata"] or "{}")
        if cached := meta.get("summary"):
            return {"summary": cached, "cached": True, "available": True}

        if not claude_available():
            return {"summary": None, "cached": False, "available": False}

        sources = conn.execute(
            "SELECT url, title, snippet, query FROM sources WHERE node_id = ? LIMIT 8",
            (node_id,),
        ).fetchall()

        neighbor_labels = [
            r["label"]
            for r in conn.execute(
                """SELECT n.label FROM edges e JOIN nodes n ON n.id = e.target_id
                   WHERE e.source_id = ?
                   UNION
                   SELECT n.label FROM edges e JOIN nodes n ON n.id = e.source_id
                   WHERE e.target_id = ? LIMIT 12""",
                (node_id, node_id),
            )
        ]

    try:
        summary = _generate(
            node_type=row["type"],
            label=row["label"],
            url=row["url"],
            sources=[{"title": s["title"], "snippet": s["snippet"], "url": s["url"]} for s in sources],
            neighbors=neighbor_labels,
        )
    except GenerationError as exc:
        return {
            "summary": None, "cached": False, "available": True,
            "error": str(exc), "error_kind": exc.kind,
        }
    if not summary:
        return {"summary": None, "cached": False, "available": True, "error": "Generation returned empty result."}

    meta["summary"] = summary
    with db.connect() as conn:
        conn.execute(
            "UPDATE nodes SET metadata = ? WHERE id = ?",
            (json.dumps(meta), node_id),
        )
    return {"summary": summary, "cached": False, "available": True}


class GenerationError(RuntimeError):
    def __init__(self, message: str, kind: str = "unknown") -> None:
        super().__init__(message)
        self.kind = kind


def _generate(node_type: str, label: str, url: str | None,
              sources: list[dict], neighbors: list[str]) -> str | None:
    try:
        from anthropic import Anthropic
        from anthropic import BadRequestError, AuthenticationError, RateLimitError
    except ImportError:
        return None

    if not sources and not neighbors:
        return None

    sources_text = "\n".join(
        f"- {(s.get('title') or '').strip()} — {(s.get('snippet') or '').strip()}"
        for s in sources if s.get("snippet") or s.get("title")
    )[:3000]
    neighbors_text = ", ".join(neighbors[:12])

    prompt = f"""Write a 2-sentence summary of this entity in the context of PyCon US 2026.

Entity type: {node_type}
Entity name: {label}
URL: {url or "(none)"}
Connected in graph to: {neighbors_text or "(nothing yet)"}

Source snippets from SerpApi search results:
{sources_text or "(no snippets)"}

Rules:
- Exactly 2 sentences, each under 25 words.
- Do not start with "This is..." or "The entity..."
- Be specific: name talks, repos, topics, dates, or affiliations when supported by the snippets.
- If the snippets are sparse, write what you can verify and stop — do not speculate.
- No emojis, no markdown, plain prose.

Return only the summary text, nothing else."""

    try:
        client = Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        return text or None
    except BadRequestError as exc:
        body = str(exc)
        if "credit balance" in body.lower():
            raise GenerationError(
                "Anthropic credit balance is too low. Top up at console.anthropic.com/settings/billing.",
                kind="billing",
            )
        raise GenerationError(f"Anthropic 400: {body[:160]}", kind="bad_request")
    except AuthenticationError:
        raise GenerationError("Anthropic API key invalid.", kind="auth")
    except RateLimitError:
        raise GenerationError("Anthropic rate limit hit. Try again shortly.", kind="rate_limit")
    except Exception as exc:
        log.exception("summary generation failed for %s", label)
        raise GenerationError(f"Generation failed: {exc}", kind="unknown")
