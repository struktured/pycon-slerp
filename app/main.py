from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .graph_builder import run_ingest

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="PyCon 2026 Knowledge Graph", lifespan=lifespan)


class IngestRequest(BaseModel):
    extra_queries: list[str] = []
    use_claude: bool = False
    expand_speakers: bool = True
    max_speakers_to_expand: int = 8


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
async def api_ingest(req: IngestRequest) -> dict:
    try:
        stats = await run_ingest(
            extra_queries=req.extra_queries,
            use_claude=req.use_claude,
            expand_speakers=req.expand_speakers,
            max_speakers_to_expand=req.max_speakers_to_expand,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "queries_run": stats.queries_run,
        "entities_added": stats.entities_added,
        "relations_added": stats.relations_added,
        "errors": stats.errors,
        "stats": db.stats(),
    }


@app.get("/api/health")
def api_health() -> dict:
    return {
        "ok": True,
        "serpapi_key_set": bool(os.environ.get("SERPAPI_API_KEY")),
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
