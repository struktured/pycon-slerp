<div align="center">

# PyCon 2026 Knowledge Graph

**A live, cross-source intelligence graph of PyCon US 2026 — fused from Google, News, Scholar, YouTube, Local, and Reddit via SerpApi.**

<sub>Built for the SerpApi raffle · Long Beach · May 13–19, 2026</sub>

[Quick Start](#quick-start) · [Features](#features) · [How It Works](#how-it-works) · [Powered by PyCon talks](#powered-by-pycon-talks) · [API](#api)

<br />

![PyCon 2026 Knowledge Graph](docs/screenshot.png)

</div>

---

## What is this?

`pycon-slerp` runs **six SerpApi engines in parallel** — Google, Google News, Google Scholar, YouTube, Google Local (Long Beach venue intel), plus a Reddit pass — and joins their entities into a single force-directed graph. Speakers, talks, papers, repos, sponsors, places, videos, Reddit threads, and "People Also Ask" questions all live in the same canvas, with every node carrying its provenance.

Three extraction backends ship out of the box:

- **Heuristic** — URL pattern matching, always on, zero deps.
- **Server-side Claude** — structured extraction via Anthropic SDK (`claude-haiku-4-5`).
- **In-browser WebLLM** — Llama-3.2-1B running on WebGPU. **No API key required.** Inspired by the PyScript / in-browser-Python work from the Anaconda team.

The graph also ships with **10 confirmed PyCon 2026 sponsors pre-seeded** so it never starts empty, plus an **"Ask the graph"** box that turns a natural-language question into a multi-engine SerpApi search plan and watches the graph grow live.

## Features

| Feature | What it does |
| --- | --- |
| **Multi-engine fusion** | One graph, six engines. Same speaker can show up via Google, YouTube channel, and Scholar paper authorship — joined on identity. |
| **Ask the graph** | Natural-language question → Claude writes a SerpApi search plan → executed in parallel → graph updates live. |
| **In-browser LLM** | WebLLM (Llama-3.2-1B, WebGPU) extracts entities client-side. No API key. Model caches locally after first download. |
| **Knowledge Graph cards** | Whenever SerpApi returns a `knowledge_graph` block, the node's detail panel shows the Google KG card — image, facts, source. |
| **People-Also-Ask edges** | PAA + Related Searches become `question` nodes and topic-to-topic edges for free. |
| **Long Beach venue intel** | `google_local` queries pull cafés, restaurants, hotels with ratings/coords near the convention center. |
| **Citation-aware Scholar** | Speakers get linked to their papers with citation counts. |
| **Speaker expansion** | Top-degree speakers automatically get follow-up searches across Google + Scholar. |
| **Pre-seeded lineup** | 10 confirmed sponsors + the PyCon 2026 event anchor are inserted at boot. |
| **Parallel ingest** | All seed queries fired concurrently via `anyio` task groups (structured concurrency). |
| **Live provenance** | Click any node to see exactly which search results contributed to it. |

## Quick Start

```bash
git clone git@github.com:struktured/pycon-slerp.git
cd pycon-slerp

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

export SERPAPI_API_KEY=...      # required
export ANTHROPIC_API_KEY=...    # optional — enables server-side Claude

# Dev (uvicorn):
.venv/bin/uvicorn app.main:app --port 8765

# Or production (Granian, the Rust-powered ASGI server):
.venv/bin/granian --interface asgi app.main:app --port 8765
```

Open <http://127.0.0.1:8765>. Three flows to try:

1. **Ask the graph.** Type a question. Watch Claude write the plan, then the nodes appear.
2. **Run ingest.** Crawls all six engines. Tick "In-browser LLM" to extract with WebLLM — your laptop's GPU does the work.
3. **Pin a talk.** In the "Powered by PyCon talks" card, click a talk to insert the speaker(s) into the graph.

## How It Works

```
                     ┌──────────────────┐
                     │     SerpApi      │ 6 engines fired in parallel
                     │                  │  google · google_news · scholar
                     │                  │  youtube · google_local · reddit
                     └────────┬─────────┘
                              ▼
                     ┌──────────────────┐
                     │   anyio TaskGroup│ structured concurrency
                     └────────┬─────────┘
                              ▼
                     ┌──────────────────┐
                     │   search cache   │ SQLite — re-runs are free
                     └────────┬─────────┘
                              ▼
       ┌─────────────────┬────┴──────┬──────────────────┐
       ▼                 ▼           ▼                  ▼
   heuristic        server Claude   WebLLM        related/PAA
   (URL patterns)   (haiku 4.5)    (browser,      (free Google
                                    WebGPU)        co-occurrence)
       └─────────────────┴────┬──────┴──────────────────┘
                              ▼
                     ┌──────────────────┐
                     │   nodes/edges    │ SQLite, with provenance
                     └────────┬─────────┘
                              ▼
                     ┌──────────────────┐
                     │ FastAPI / Granian│ /api/graph, /api/ask, /api/inject
                     └────────┬─────────┘
                              ▼
                     ┌──────────────────┐
                     │   cytoscape.js   │ force-directed (fcose)
                     └──────────────────┘
```

### Node Types

| Type | Color | Source |
| --- | --- | --- |
| `speaker` | yellow | name heuristics, Scholar authors, YouTube channels, Claude, WebLLM |
| `talk` | blue | pycon.org pages + Claude |
| `topic` | purple | keyword list + Claude |
| `repo` | green | `github.com/<user>/<repo>` |
| `paper` | pink | Scholar + `arxiv.org/abs/...` with citation counts |
| `video` | orange | YouTube engine (channel + views) |
| `sponsor` | cyan | pre-seeded list + Claude on sponsor pages |
| `event` | pale yellow | PyCon 2026 anchor + sub-events |
| `place` | teal | `google_local` venue intel |
| `question` | magenta | People Also Ask |
| `discussion` | orange-red | Reddit threads |
| `article` | grey | fallback |

## Powered by PyCon talks

This project draws directly on six talks attended at PyCon US 2026. Each one shows up in the sidebar — clicking pins the talk + speaker(s) into the graph as real nodes.

| Talk | Speaker(s) | Used for |
| --- | --- | --- |
| [Distributing AI with Python in the Browser — Edge Inference Without Infra](https://us.pycon.org/2026/schedule/presentation/126/) | Fabio Pliger (Anaconda) | In-browser LLM extraction via WebLLM + WebGPU — no API key required |
| PEP 750: t-strings — Safer and Smarter String Processing | Vinicus Gubiana Ferreria | PEP 750-style structured query templating in `app/query_template.py` — safe SerpApi search-query interpolation |
| AI-Assisted Contributions and Maintainer Load | Palao Melichorre (Django) | Multi-backend extraction (heuristic / Claude / WebLLM) — judge the code, not the coder |
| Beyond the Hype: How Developers Actually Use AI Tools (panel) | Carol Willing · Catherine Nelson · Jelle Zijlstra (OpenAI) · Jodie Burchell (JetBrains) · Lais Carvalho (Pydantic) · Maike Scherer (American Airlines) | Ask-the-graph mirrors the panel's agentic loop: plan → execute → evaluate → iterate, with search results as the verifier |
| Building Enterprise Python Libraries in a Modern Way | Dan Furman · David Hoover (Capital One) | Layered library abstraction — engine wrappers → entity extractors → graph builder |
| Why SWE Best Practices Fail in Data Engineering | Constance Martineau (Astronomer) | Provenance-first design — every node carries its source query and snippet, because in data work the data is the variable |

_Edit `app/inspirations.py` to add or correct attributions._

### Pre-seeded lineup

The graph boots with 32 anchor nodes: the PyCon 2026 event, 13 confirmed sponsors, 12 speakers from attended talks, and the 6 talks themselves — so live crawls attach sources to existing nodes rather than create duplicates.

**Sponsors:** Temporal · GitHub · Pydantic · Streamlit · kraken.tech · Jane Street · Hudson River Trading · OpenAI · Capital One · Point72 · Anaconda · JetBrains · Astronomer

**Speakers seeded:** Fabio Pliger · Vinicus Gubiana Ferreria · Palao Melichorre · Carol Willing · Catherine Nelson · Jelle Zijlstra · Jodie Burchell · Lais Carvalho · Maike Scherer · Dan Furman · David Hoover · Constance Martineau

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/graph` | Full graph as `{ nodes, edges }` |
| `GET` | `/api/node/{id}` | Node detail with sources + neighbors + KG card |
| `GET` | `/api/stats` | Node/edge counts, breakdown by type |
| `POST` | `/api/ingest` | Trigger the full multi-engine crawl |
| `POST` | `/api/ask` | Natural-language question → plan → live graph update |
| `GET` | `/api/inspirations` | The "Powered by PyCon talks" list + pre-seeded sponsors |
| `POST` | `/api/inspirations/pin` | Pin a talk + speakers into the graph |
| `GET` | `/api/recent_hits` | Recent cached SerpApi responses (compact) — used by the in-browser LLM |
| `POST` | `/api/inject` | Accept entities + relations extracted client-side (WebLLM) |
| `GET` | `/api/health` | Reports API-key presence |

`POST /api/ask` body:

```json
{
  "question": "Which AI/ML talks are at PyCon 2026?",
  "use_claude": true
}
```

Response:

```json
{
  "plan": [
    {"engine": "google", "query": "PyCon 2026 AI ML talks"},
    {"engine": "google_news", "query": "PyCon 2026 machine learning"},
    {"engine": "youtube", "query": "PyCon AI agents 2025"}
  ],
  "summary": "Ran 3 searches across 3 engines; added 47 entities and 81 edges.",
  "stats": {"nodes": 312, "edges": 540, "by_type": { }}
}
```

## Architecture

```
app/
├── db.py                SQLite schema + helpers
├── serpapi_client.py    Async SerpApi wrapper, multi-engine, with disk cache
├── entity_extractor.py  Heuristic + Claude + PAA/related extraction
├── query_template.py    PEP 750-style safe query templating (credits: Vinicus' t-strings talk)
├── inspirations.py      Pre-seeded sponsors/speakers/talks + "Powered by PyCon talks"
├── graph_builder.py     Parallel ingest (anyio) + Ask-the-graph orchestration
└── main.py              FastAPI app — Granian-compatible

static/
├── index.html           Graph UI
├── graph.js             Cytoscape + WebLLM client + KG card render
└── styles.css           Dark theme

scripts/
└── screenshot.py        Headless Playwright screenshot

data/                    SQLite + SerpApi response cache (gitignored)
```

## Tech Stack

| Layer | Choice |
| --- | --- |
| Backend | Python 3.13 · FastAPI · httpx · `anyio` · SQLite |
| Runtime | `uvicorn` (dev) / `granian` (production, Rust-powered) |
| Frontend | Vanilla JS · cytoscape.js · fcose layout |
| Search | SerpApi (Google · News · Scholar · YouTube · Local) |
| LLM — server | Anthropic Claude Haiku 4.5 (optional) |
| LLM — client | `@mlc-ai/web-llm` (Llama-3.2-1B, WebGPU, no API key) |

## Deploying to Fly.io

The repo ships with a `Dockerfile` and `fly.toml` tuned for a live demo where:

- **Your SerpApi key never leaves the server** — set as a Fly secret, used only inside the VM.
- **No Anthropic key needed on the server** — visitors run an in-browser WebLLM (Llama-3.2-1B on WebGPU) for entity extraction. Free on their hardware.
- **Live endpoints are passcode-gated.** `/api/ingest`, `/api/ask`, `/api/inject`, `/api/inspirations/pin` require `ADMIN_TOKEN`. Anonymous traffic can still browse the pre-built graph.
- **Persistent volume** keeps the SQLite cache between deploys, so re-runs are free.

```bash
# one-time setup
fly launch --no-deploy --copy-config              # accept defaults; edit app name in fly.toml
fly volume create pycon_data --region lax --size 1
fly secrets set SERPAPI_API_KEY=<your-key>
fly secrets set ADMIN_TOKEN=$(openssl rand -hex 16)

# ship it
fly deploy

# hand out the demo link (URL token unlocks Ask + Ingest for the recipient):
echo "https://$(fly status --json | jq -r .Hostname)/?t=$(fly ssh console -C 'printenv ADMIN_TOKEN')"
```

The token is stored in `localStorage` after the first visit, so the recipient just bookmarks the plain URL after that. Anyone arriving without the token sees a 🔒 badge and can browse but not spend your quota.

To pre-warm the graph before going public, run one ingest locally with your key, then deploy — the SQLite cache plus the seeded sponsors/speakers means the live site looks alive from request zero.

## Reproducing the Screenshot

```bash
.venv/bin/pip install playwright
.venv/bin/playwright install chromium
.venv/bin/python scripts/screenshot.py
```

## Credits

- [SerpApi](https://serpapi.com) — the search backbone (six engines fused into one graph)
- [Anthropic Claude](https://www.anthropic.com/) — server-side entity extraction
- [MLC WebLLM](https://webllm.mlc.ai/) — in-browser LLM, inspired by PyScript work from the Anaconda team
- [Granian](https://github.com/emmett-framework/granian) — Rust-powered ASGI server, agent-friendly
- [anyio](https://anyio.readthedocs.io/) — structured concurrency for parallel ingest
- [cytoscape.js](https://js.cytoscape.org/) + [fcose](https://github.com/iVis-at-Bilkent/cytoscape.js-fcose) — graph rendering
- [FastAPI](https://fastapi.tiangolo.com/) — the web framework

<sub>Submission to the SerpApi raffle at PyCon US 2026.</sub>
