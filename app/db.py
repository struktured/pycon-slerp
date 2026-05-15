import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "graph.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    label TEXT NOT NULL,
    url TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_label ON nodes(label);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    metadata TEXT NOT NULL DEFAULT '{}',
    UNIQUE(source_id, target_id, type),
    FOREIGN KEY(source_id) REFERENCES nodes(id),
    FOREIGN KEY(target_id) REFERENCES nodes(id)
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);

CREATE TABLE IF NOT EXISTS search_cache (
    query_hash TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    engine TEXT NOT NULL,
    response TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    snippet TEXT,
    query TEXT NOT NULL,
    UNIQUE(node_id, url),
    FOREIGN KEY(node_id) REFERENCES nodes(id)
);
CREATE INDEX IF NOT EXISTS idx_sources_node ON sources(node_id);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_node(conn: sqlite3.Connection, node_id: str, node_type: str, label: str,
                url: str | None = None, metadata: dict | None = None) -> None:
    conn.execute(
        """INSERT INTO nodes (id, type, label, url, metadata)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             label = excluded.label,
             url = COALESCE(excluded.url, nodes.url),
             metadata = json_patch(nodes.metadata, excluded.metadata)""",
        (node_id, node_type, label, url, json.dumps(metadata or {})),
    )


def upsert_edge(conn: sqlite3.Connection, source_id: str, target_id: str,
                edge_type: str, weight: float = 1.0, metadata: dict | None = None) -> None:
    conn.execute(
        """INSERT INTO edges (source_id, target_id, type, weight, metadata)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(source_id, target_id, type) DO UPDATE SET
             weight = edges.weight + excluded.weight""",
        (source_id, target_id, edge_type, weight, json.dumps(metadata or {})),
    )


def add_source(conn: sqlite3.Connection, node_id: str, url: str,
               title: str | None, snippet: str | None, query: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO sources (node_id, url, title, snippet, query)
           VALUES (?, ?, ?, ?, ?)""",
        (node_id, url, title, snippet, query),
    )


def get_graph() -> dict:
    with connect() as conn:
        nodes = [
            {
                "id": r["id"],
                "type": r["type"],
                "label": r["label"],
                "url": r["url"],
                "metadata": json.loads(r["metadata"]),
            }
            for r in conn.execute("SELECT * FROM nodes")
        ]
        edges = [
            {
                "id": str(r["id"]),
                "source": r["source_id"],
                "target": r["target_id"],
                "type": r["type"],
                "weight": r["weight"],
            }
            for r in conn.execute("SELECT * FROM edges")
        ]
    return {"nodes": nodes, "edges": edges}


def get_node_detail(node_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not row:
            return None
        sources = [
            {"url": r["url"], "title": r["title"], "snippet": r["snippet"], "query": r["query"]}
            for r in conn.execute("SELECT * FROM sources WHERE node_id = ?", (node_id,))
        ]
        neighbors = [
            {
                "node": {
                    "id": r["id"], "type": r["type"], "label": r["label"], "url": r["url"],
                },
                "edge_type": r["edge_type"],
                "direction": r["direction"],
            }
            for r in conn.execute(
                """SELECT n.id, n.type, n.label, n.url, e.type AS edge_type, 'out' AS direction
                   FROM edges e JOIN nodes n ON n.id = e.target_id WHERE e.source_id = ?
                   UNION
                   SELECT n.id, n.type, n.label, n.url, e.type AS edge_type, 'in' AS direction
                   FROM edges e JOIN nodes n ON n.id = e.source_id WHERE e.target_id = ?""",
                (node_id, node_id),
            )
        ]
        return {
            "id": row["id"],
            "type": row["type"],
            "label": row["label"],
            "url": row["url"],
            "metadata": json.loads(row["metadata"]),
            "sources": sources,
            "neighbors": neighbors,
        }


def get_cached_search(query_hash: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT response FROM search_cache WHERE query_hash = ?", (query_hash,)
        ).fetchone()
        return json.loads(row["response"]) if row else None


def cache_search(query_hash: str, query: str, engine: str, response: dict) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO search_cache (query_hash, query, engine, response)
               VALUES (?, ?, ?, ?)""",
            (query_hash, query, engine, json.dumps(response)),
        )


def stats() -> dict:
    with connect() as conn:
        node_count = conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
        edge_count = conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
        by_type = {
            r["type"]: r["c"]
            for r in conn.execute("SELECT type, COUNT(*) AS c FROM nodes GROUP BY type")
        }
    return {"nodes": node_count, "edges": edge_count, "by_type": by_type}
