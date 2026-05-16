from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .entity_extractor import _id_for, normalize
from .graph_builder import ask_the_graph, bootstrap, run_ingest
from .inspirations import (
    INSPIRATIONS,
    KNOWN_SPONSORS,
    pinnable_entities,
    pinnable_relations,
)
from .serpapi_client import SerpApiClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap()
    yield


app = FastAPI(title="PyCon 2026 Knowledge Graph", lifespan=lifespan)


# -- Optional passcode for write/SerpApi-spending endpoints ------------------
# Set ADMIN_TOKEN in the deployment environment to gate /api/ingest,
# /api/ask, /api/inject, /api/inspirations/pin. Anonymous traffic can still
# browse the pre-built graph (/api/graph, /api/node, /api/stats, etc.).
def require_admin(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> None:
    expected = os.environ.get("ADMIN_TOKEN")
    if not expected:
        return  # no token configured → endpoint is open (dev mode)
    candidate = x_admin_token or request.query_params.get("t") or ""
    if not candidate or not hmac.compare_digest(candidate, expected):
        raise HTTPException(status_code=401, detail="admin token required")


class IngestRequest(BaseModel):
    extra_queries: list[str] = []
    use_claude: bool = False
    expand_speakers: bool = True
    max_speakers_to_expand: int = 8
    engines: list[str] | None = None


class AskRequest(BaseModel):
    question: str
    use_claude: bool = True


class InjectEntity(BaseModel):
    type: str
    label: str
    url: str | None = None
    metadata: dict = {}


class InjectRelation(BaseModel):
    source_label: str
    source_type: str
    target_label: str
    target_type: str
    edge_type: str


class InjectRequest(BaseModel):
    entities: list[InjectEntity] = []
    relations: list[InjectRelation] = []
    source_query: str | None = None
    source_engine: str | None = None


@app.get("/api/graph")
def api_graph() -> dict:
    return db.get_graph()


@app.get("/api/stats")
def api_stats() -> dict:
    return db.stats()


@app.get("/api/node/{node_id}")
def api_node(node_id: str) -> dict:
    detail = db.get_node_detail(node_id)
    if not detail:
        raise HTTPException(status_code=404, detail="node not found")
    return detail


@app.post("/api/ingest")
async def api_ingest(req: IngestRequest, _: None = Depends(require_admin)) -> dict:
    try:
        stats = await run_ingest(
            extra_queries=req.extra_queries,
            use_claude=req.use_claude,
            expand_speakers=req.expand_speakers,
            max_speakers_to_expand=req.max_speakers_to_expand,
            engines=req.engines,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "queries_run": stats.queries_run,
        "entities_added": stats.entities_added,
        "relations_added": stats.relations_added,
        "questions_added": stats.questions_added,
        "kg_cards_captured": stats.kg_cards_captured,
        "engines": stats.engines,
        "errors": stats.errors,
        "stats": db.stats(),
    }


@app.post("/api/ask")
async def api_ask(req: AskRequest, _: None = Depends(require_admin)) -> dict:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    try:
        result = await ask_the_graph(req.question, use_claude=req.use_claude)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "plan": result.plan,
        "summary": result.summary,
        "queries_run": result.stats.queries_run,
        "entities_added": result.stats.entities_added,
        "relations_added": result.stats.relations_added,
        "engines": result.stats.engines,
        "errors": result.stats.errors,
        "stats": db.stats(),
    }


@app.get("/api/recent_hits")
def api_recent_hits(limit: int = 20) -> dict:
    """Return recently-cached SerpApi responses, normalized to a compact
    `{query, engine, hits: [{title, link, snippet}], related_questions, related_searches}`
    shape. Used by the in-browser LLM extractor so it can re-process search
    results without re-spending SerpApi credits.
    """
    out = []
    for row in db.recent_cached_searches(limit=limit):
        resp = row["response"]
        hits = SerpApiClient.primary_hits(resp, row["engine"])
        compact_hits = [
            {
                "title": h.get("title") or "",
                "link": h.get("link") or "",
                "snippet": h.get("snippet") or "",
            }
            for h in hits[:10]
        ]
        out.append({
            "query": row["query"],
            "engine": row["engine"],
            "fetched_at": row["fetched_at"],
            "hits": compact_hits,
            "related_questions": [
                {"question": q.get("question") or "", "snippet": q.get("snippet") or ""}
                for q in (resp.get("related_questions") or [])[:6]
            ],
            "related_searches": [
                r.get("query") or r.get("name") or ""
                for r in (resp.get("related_searches") or [])[:8]
            ],
        })
    return {"items": out}


@app.post("/api/inject")
def api_inject(req: InjectRequest, _: None = Depends(require_admin)) -> dict:
    """Accept entities + relations extracted client-side (e.g. by an
    in-browser WebLLM) and merge them into the graph.
    """
    db.init_db()
    added_entities = 0
    added_relations = 0
    valid_types = {"speaker", "talk", "topic", "repo", "paper", "video",
                   "sponsor", "event", "article", "place", "question", "discussion"}
    valid_edges = {"presents", "about", "authored", "works_on", "sponsors",
                   "features", "references", "near", "related"}
    with db.connect() as conn:
        for e in req.entities:
            if e.type not in valid_types or not e.label:
                continue
            node_id = _id_for(e.type, e.label)
            metadata = {**(e.metadata or {}), "source": "browser_llm"}
            db.upsert_node(conn, node_id, e.type, e.label, e.url, metadata)
            if req.source_query and e.url:
                db.add_source(
                    conn, node_id, e.url, e.label, (e.metadata or {}).get("snippet"),
                    f"[{req.source_engine or 'browser'}] {req.source_query}",
                )
            added_entities += 1
        for r in req.relations:
            if r.edge_type not in valid_edges:
                continue
            if r.source_type not in valid_types or r.target_type not in valid_types:
                continue
            src_id = _id_for(r.source_type, r.source_label)
            tgt_id = _id_for(r.target_type, r.target_label)
            try:
                db.upsert_edge(conn, src_id, tgt_id, r.edge_type)
                added_relations += 1
            except Exception:
                pass
    return {
        "entities_added": added_entities,
        "relations_added": added_relations,
        "stats": db.stats(),
    }


@app.get("/api/inspirations")
def api_inspirations() -> dict:
    return {
        "inspirations": INSPIRATIONS,
        "sponsors": KNOWN_SPONSORS,
    }


class PinRequest(BaseModel):
    tag: str


@app.post("/api/inspirations/pin")
def api_pin_inspiration(req: PinRequest, _: None = Depends(require_admin)) -> dict:
    """Pin an inspiration (talk + speakers) into the graph as real nodes."""
    item = next((i for i in INSPIRATIONS if i.get("tag") == req.tag), None)
    if not item:
        raise HTTPException(status_code=404, detail="unknown inspiration tag")
    ents = pinnable_entities(item)
    rels = pinnable_relations(item)
    added_e = 0
    added_r = 0
    with db.connect() as conn:
        for e in ents:
            node_id = _id_for(e["type"], e["label"])
            db.upsert_node(conn, node_id, e["type"], e["label"], e.get("url"), e.get("metadata") or {})
            added_e += 1
        for r in rels:
            src_id = _id_for(r["source_type"], r["source_label"])
            tgt_id = _id_for(r["target_type"], r["target_label"])
            try:
                db.upsert_edge(conn, src_id, tgt_id, r["edge_type"])
                added_r += 1
            except Exception:
                pass
    return {"entities_added": added_e, "relations_added": added_r, "stats": db.stats()}


@app.get("/api/health")
def api_health() -> dict:
    return {
        "ok": True,
        "serpapi_key_set": bool(os.environ.get("SERPAPI_API_KEY")),
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "admin_token_required": bool(os.environ.get("ADMIN_TOKEN")),
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
