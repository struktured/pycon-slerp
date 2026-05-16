const TYPE_COLORS = {
  speaker: "#ffd43b",
  talk:    "#4584b6",
  topic:   "#b08bff",
  repo:    "#50fa7b",
  paper:   "#ff79c6",
  video:   "#ff8c42",
  event:   "#f1fa8c",
  article: "#6b7280",
  sponsor: "#06b6d4",
  place:   "#14b8a6",
  question:"#ec4899",
  discussion: "#f97316",
};

const TYPE_SIZE = {
  event: 60, speaker: 36, talk: 30, topic: 22, repo: 24,
  paper: 22, video: 22, article: 16, sponsor: 28,
  place: 26, question: 22, discussion: 20,
};

const state = {
  cy: null,
  hiddenTypes: new Set(),
  raw: { nodes: [], edges: [] },
  webllm: { engine: null, status: "idle", model: null },
  adminRequired: false,
  token: null,
};

// Pick up an admin token from `?t=...` (the share-link form) or from
// localStorage if the user has already unlocked once on this device.
(function initToken() {
  const p = new URLSearchParams(window.location.search);
  const t = p.get("t");
  if (t) {
    localStorage.setItem("pycon-slerp-token", t);
    state.token = t;
    history.replaceState(null, "", window.location.pathname);
  } else {
    state.token = localStorage.getItem("pycon-slerp-token") || null;
  }
})();

async function fetchJSON(url, opts) {
  opts = opts || {};
  if (state.token) {
    opts.headers = { ...(opts.headers || {}), "X-Admin-Token": state.token };
  }
  const r = await fetch(url, opts);
  if (r.status === 401) {
    const entered = prompt("This action needs the demo passcode:");
    if (entered) {
      localStorage.setItem("pycon-slerp-token", entered);
      state.token = entered;
      return fetchJSON(url, opts);
    }
    throw new Error("passcode required");
  }
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json();
}

async function loadGraph() {
  const data = await fetchJSON("/api/graph");
  state.raw = data;
  renderGraph();
  renderTypeFilters();
  await refreshStats();
}

function renderGraph() {
  const elements = [];
  const typesSeen = new Set();

  state.raw.nodes.forEach((n) => {
    if (state.hiddenTypes.has(n.type)) return;
    typesSeen.add(n.type);
    elements.push({
      data: { id: n.id, label: n.label, type: n.type, url: n.url },
    });
  });

  const visibleIds = new Set(elements.map((e) => e.data.id));
  state.raw.edges.forEach((e) => {
    if (!visibleIds.has(e.source) || !visibleIds.has(e.target)) return;
    elements.push({
      data: { id: e.id, source: e.source, target: e.target, type: e.type },
    });
  });

  if (state.cy) state.cy.destroy();

  state.cy = cytoscape({
    container: document.getElementById("graph"),
    elements,
    style: [
      {
        selector: "node",
        style: {
          "background-color": (ele) => TYPE_COLORS[ele.data("type")] || "#888",
          "label": "data(label)",
          "color": "#e6e8ee",
          "font-size": 10,
          "text-valign": "bottom",
          "text-halign": "center",
          "text-margin-y": 4,
          "text-outline-color": "#0e0f13",
          "text-outline-width": 2,
          "width": (ele) => TYPE_SIZE[ele.data("type")] || 20,
          "height": (ele) => TYPE_SIZE[ele.data("type")] || 20,
          "border-width": 1,
          "border-color": "#0e0f13",
          "text-wrap": "ellipsis",
          "text-max-width": 120,
        },
      },
      {
        selector: "node:selected",
        style: { "border-color": "#fff", "border-width": 3 },
      },
      {
        selector: "edge",
        style: {
          "width": 1,
          "line-color": "#3a3f4d",
          "curve-style": "bezier",
          "target-arrow-color": "#3a3f4d",
          "target-arrow-shape": "triangle",
          "arrow-scale": 0.7,
          "opacity": 0.55,
        },
      },
      {
        selector: "edge.highlight",
        style: {
          "line-color": "#ffd43b",
          "target-arrow-color": "#ffd43b",
          "opacity": 1,
          "width": 2,
          "z-index": 10,
        },
      },
      { selector: "node.dimmed", style: { opacity: 0.18 } },
      { selector: "edge.dimmed", style: { opacity: 0.08 } },
    ],
    layout: {
      name: "fcose",
      animate: true,
      randomize: true,
      nodeRepulsion: 8000,
      idealEdgeLength: 90,
      gravity: 0.25,
      numIter: 2500,
      tile: true,
      padding: 30,
    },
    minZoom: 0.15,
    maxZoom: 3,
    wheelSensitivity: 0.2,
  });

  state.cy.on("tap", "node", (evt) => showDetail(evt.target.id()));
  state.cy.on("tap", (evt) => {
    if (evt.target === state.cy) clearHighlight();
  });
  state.cy.on("mouseover", "node", (evt) => highlightNeighborhood(evt.target));
  state.cy.on("mouseout", "node", () => clearHighlight());
}

function highlightNeighborhood(node) {
  state.cy.elements().addClass("dimmed");
  const nh = node.closedNeighborhood();
  nh.removeClass("dimmed");
  node.connectedEdges().addClass("highlight");
}

function clearHighlight() {
  state.cy.elements().removeClass("dimmed");
  state.cy.edges().removeClass("highlight");
}

function renderTypeFilters() {
  const container = document.getElementById("type-filters");
  const types = Array.from(new Set(state.raw.nodes.map((n) => n.type))).sort();
  container.innerHTML = "";
  types.forEach((t) => {
    const chip = document.createElement("span");
    chip.className = "chip" + (state.hiddenTypes.has(t) ? " off" : "");
    chip.innerHTML = `<span class="dot" style="background:${TYPE_COLORS[t] || "#888"}"></span>${t}`;
    chip.onclick = () => {
      if (state.hiddenTypes.has(t)) state.hiddenTypes.delete(t);
      else state.hiddenTypes.add(t);
      renderGraph();
      renderTypeFilters();
    };
    container.appendChild(chip);
  });
}

async function showDetail(nodeId) {
  const card = document.getElementById("detail-card");
  try {
    const d = await fetchJSON(`/api/node/${nodeId}`);
    document.getElementById("detail-title").textContent = d.label;
    document.getElementById("detail-type").textContent = d.type.toUpperCase();
    const urlEl = document.getElementById("detail-url");
    if (d.url) {
      urlEl.href = d.url;
      urlEl.textContent = d.url;
      urlEl.style.display = "inline";
    } else {
      urlEl.style.display = "none";
    }

    renderKgCard(d);
    renderMetaPills(d);

    const nbBox = document.getElementById("detail-neighbors");
    nbBox.innerHTML = "";
    d.neighbors.slice(0, 30).forEach((nb) => {
      const el = document.createElement("span");
      el.className = "neighbor";
      el.style.borderColor = TYPE_COLORS[nb.node.type] || "#444";
      el.textContent = `${nb.node.label} (${nb.edge_type})`;
      el.onclick = () => {
        state.cy.$(`#${CSS.escape(nb.node.id)}`).select();
        showDetail(nb.node.id);
      };
      nbBox.appendChild(el);
    });

    const srcs = document.getElementById("detail-sources");
    srcs.innerHTML = "";
    d.sources.slice(0, 15).forEach((s) => {
      const li = document.createElement("li");
      li.innerHTML = `
        <div class="src-title"><a href="${s.url}" target="_blank" rel="noreferrer">${escapeHtml(s.title || s.url)}</a></div>
        <div class="src-snippet">${escapeHtml((s.snippet || "").slice(0, 240))}</div>
        <div class="src-query">${escapeHtml(s.query || "")}</div>
      `;
      srcs.appendChild(li);
    });

    card.hidden = false;
  } catch (e) {
    console.error(e);
  }
}

function renderKgCard(d) {
  const box = document.getElementById("detail-kg");
  const kg = d.metadata && d.metadata.kg;
  if (!kg) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  const facts = (kg.facts || []).map(
    (f) => `<div class="kg-fact"><span>${escapeHtml(f.label)}</span><b>${escapeHtml(f.value)}</b></div>`
  ).join("");
  box.innerHTML = `
    <div class="kg-head">
      ${kg.image ? `<img src="${kg.image}" alt="" />` : ""}
      <div>
        <div class="kg-title">${escapeHtml(kg.title || d.label)}</div>
        <div class="kg-type">${escapeHtml(kg.type || "")}</div>
      </div>
    </div>
    ${kg.description ? `<p class="kg-desc">${escapeHtml(kg.description)}</p>` : ""}
    ${facts ? `<div class="kg-facts">${facts}</div>` : ""}
    ${kg.website ? `<a class="kg-link" href="${kg.website}" target="_blank" rel="noreferrer">${escapeHtml(kg.website)}</a>` : ""}
    <div class="kg-source">via Google Knowledge Graph (SerpApi)</div>
  `;
  box.hidden = false;
}

function renderMetaPills(d) {
  const box = document.getElementById("detail-meta");
  const meta = d.metadata || {};
  const pills = [];
  if (meta.views) pills.push(["views", formatCount(meta.views)]);
  if (meta.cited_by) pills.push(["cited", formatCount(meta.cited_by)]);
  if (meta.rating) pills.push(["★", `${meta.rating}${meta.reviews ? ` (${formatCount(meta.reviews)})` : ""}`]);
  if (meta.channel) pills.push(["channel", meta.channel]);
  if (meta.address) pills.push(["📍", meta.address]);
  if (meta.year) pills.push(["yr", meta.year]);
  if (meta.platform) pills.push(["src", meta.platform]);
  if (meta.published) pills.push(["pub", meta.published]);
  box.innerHTML = pills.map(([k, v]) =>
    `<span class="meta-pill"><span>${escapeHtml(k)}</span>${escapeHtml(String(v))}</span>`
  ).join("");
}

function formatCount(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return String(n);
  if (x >= 1e6) return (x / 1e6).toFixed(1) + "M";
  if (x >= 1e3) return (x / 1e3).toFixed(1) + "K";
  return String(x);
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// -- Ingest -------------------------------------------------------------------

document.getElementById("ingest-btn").addEventListener("click", async () => {
  const btn = document.getElementById("ingest-btn");
  const log = document.getElementById("ingest-log");
  const useClaude = document.getElementById("use-claude").checked;
  const expand = document.getElementById("expand-speakers").checked;
  const useBrowserLLM = document.getElementById("use-browser-llm").checked;
  const extra = document.getElementById("extra-queries").value
    .split("\n").map((s) => s.trim()).filter(Boolean);

  btn.disabled = true;
  btn.textContent = "Ingesting…";
  log.textContent = "Running multi-engine SerpApi crawl (Google · News · Scholar · YouTube · Local). 30–90s.\n";

  try {
    const res = await fetchJSON("/api/ingest", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        extra_queries: extra,
        use_claude: useClaude,
        expand_speakers: expand,
      }),
    });
    log.textContent += `Done. Queries: ${res.queries_run}, entities: ${res.entities_added}, relations: ${res.relations_added}\n`;
    if (res.engines) {
      log.textContent += `Engines: ${Object.entries(res.engines).map(([k, v]) => `${k}=${v}`).join(", ")}\n`;
    }
    if (res.kg_cards_captured) {
      log.textContent += `Knowledge Graph cards captured: ${res.kg_cards_captured}\n`;
    }
    if (res.errors && res.errors.length) {
      log.textContent += `\nErrors:\n${res.errors.slice(0, 5).join("\n")}`;
    }
    await loadGraph();

    if (useBrowserLLM) {
      log.textContent += `\nKicking off in-browser LLM extraction…\n`;
      await runBrowserLLMExtraction((msg) => {
        log.textContent += msg + "\n";
        log.scrollTop = log.scrollHeight;
      });
      await loadGraph();
    }
  } catch (e) {
    log.textContent += `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Run ingest";
  }
});

// -- Ask the graph ------------------------------------------------------------

document.getElementById("ask-btn").addEventListener("click", async () => {
  const btn = document.getElementById("ask-btn");
  const log = document.getElementById("ask-log");
  const planEl = document.getElementById("ask-plan");
  const q = document.getElementById("ask-input").value.trim();
  if (!q) return;
  btn.disabled = true;
  btn.textContent = "Thinking…";
  log.textContent = "Claude is writing a SerpApi search plan…\n";
  planEl.hidden = true;
  planEl.innerHTML = "";
  try {
    const res = await fetchJSON("/api/ask", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question: q, use_claude: true }),
    });
    planEl.innerHTML = "<b>Plan:</b>" + (res.plan || []).map((p) =>
      `<div class="plan-step"><span class="engine">${escapeHtml(p.engine || "google")}</span> ${escapeHtml(p.query || "")}</div>`
    ).join("");
    planEl.hidden = false;
    log.textContent += res.summary + "\n";
    if (res.engines) {
      log.textContent += `Engines: ${Object.entries(res.engines).map(([k, v]) => `${k}=${v}`).join(", ")}\n`;
    }
    await loadGraph();

    if (document.getElementById("use-browser-llm").checked) {
      log.textContent += "Re-extracting fresh results with in-browser LLM…\n";
      await runBrowserLLMExtraction((m) => { log.textContent += m + "\n"; });
      await loadGraph();
    }
  } catch (e) {
    log.textContent += `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Ask";
  }
});

// -- In-browser LLM (WebLLM) --------------------------------------------------

const WEBLLM_MODEL = "Llama-3.2-1B-Instruct-q4f16_1-MLC";

async function ensureWebLLM(progressCb) {
  if (state.webllm.engine) return state.webllm.engine;
  state.webllm.status = "loading";
  setWebLLMBadge("loading model…");
  const mod = await import("https://esm.run/@mlc-ai/web-llm");
  const engine = await mod.CreateMLCEngine(WEBLLM_MODEL, {
    initProgressCallback: (p) => {
      const pct = Math.round((p.progress || 0) * 100);
      setWebLLMBadge(`${p.text || "loading"} ${pct}%`);
      if (progressCb) progressCb(`webllm: ${p.text || ""} ${pct}%`);
    },
  });
  state.webllm.engine = engine;
  state.webllm.status = "ready";
  state.webllm.model = WEBLLM_MODEL;
  setWebLLMBadge(`${WEBLLM_MODEL.split("-")[0]} ready`);
  return engine;
}

function setWebLLMBadge(text) {
  const b = document.getElementById("webllm-badge");
  if (b) {
    b.textContent = text;
    b.hidden = !text;
  }
}

async function runBrowserLLMExtraction(log) {
  if (!hasWebGPU()) {
    log("WebGPU not available — skipping browser LLM. Try Chrome/Edge or Safari TP.");
    return;
  }
  try {
    const engine = await ensureWebLLM();
    const data = await fetchJSON("/api/recent_hits?limit=10");
    let totalEnts = 0, totalRels = 0;
    for (const item of data.items || []) {
      if (!item.hits || !item.hits.length) continue;
      log(`extracting from [${item.engine}] ${item.query.slice(0, 60)}…`);
      const extracted = await extractWithWebLLM(engine, item);
      if (!extracted) continue;
      const inj = await fetchJSON("/api/inject", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          entities: extracted.entities || [],
          relations: extracted.relations || [],
          source_query: item.query,
          source_engine: item.engine,
        }),
      });
      totalEnts += inj.entities_added || 0;
      totalRels += inj.relations_added || 0;
    }
    log(`browser LLM done. entities: ${totalEnts}, relations: ${totalRels}`);
  } catch (e) {
    log(`browser LLM error: ${e.message}`);
  }
}

function hasWebGPU() {
  return typeof navigator !== "undefined" && "gpu" in navigator;
}

async function extractWithWebLLM(engine, item) {
  const compact = item.hits.slice(0, 6).map((h) => ({
    title: (h.title || "").slice(0, 140),
    link: h.link || "",
    snippet: (h.snippet || "").slice(0, 200),
  }));
  const system = `You extract entities from web search results for a PyCon 2026
knowledge graph. Return strict JSON only, no commentary, no markdown fences.`;
  const user = `Search query: ${item.query}
Engine: ${item.engine}

Results:
${JSON.stringify(compact, null, 1)}

Return this JSON shape:
{
  "entities": [{"type":"speaker|talk|topic|repo|paper|video|sponsor|event|article|place|question|discussion","label":"...","url":"..."}],
  "relations": [{"source_label":"...","source_type":"...","target_label":"...","target_type":"...","edge_type":"presents|about|authored|sponsors|features|references|near|related"}]
}

Rules: full names for speakers; short noun phrases for topics; only include entities clearly named in the results.`;

  try {
    const reply = await engine.chat.completions.create({
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
      temperature: 0,
      max_tokens: 700,
      response_format: { type: "json_object" },
    });
    const text = reply.choices[0].message.content;
    return JSON.parse(text);
  } catch (e) {
    console.warn("webllm extract failed", e);
    return null;
  }
}

// Toggle handler — preload the model lazily so users can warm it up
document.getElementById("use-browser-llm").addEventListener("change", (e) => {
  const badge = document.getElementById("webllm-badge");
  if (e.target.checked) {
    if (!hasWebGPU()) {
      badge.textContent = "WebGPU unavailable — try Chrome/Edge";
      badge.hidden = false;
      return;
    }
    badge.textContent = "click ingest to load model";
    badge.hidden = false;
  } else {
    badge.hidden = true;
  }
});

// -- Search filter ------------------------------------------------------------

document.getElementById("search").addEventListener("input", (e) => {
  const q = e.target.value.toLowerCase().trim();
  if (!state.cy) return;
  if (!q) {
    state.cy.elements().removeClass("dimmed");
    return;
  }
  state.cy.nodes().forEach((n) => {
    const match = (n.data("label") || "").toLowerCase().includes(q);
    n.toggleClass("dimmed", !match);
  });
  state.cy.edges().addClass("dimmed");
});

async function refreshStats() {
  try {
    const s = await fetchJSON("/api/stats");
    document.getElementById("stat-nodes").textContent = s.nodes;
    document.getElementById("stat-edges").textContent = s.edges;
    const engineTypes = Object.keys(s.by_type || {}).length;
    document.getElementById("stat-engines").textContent = engineTypes;
  } catch {}
}

async function refreshLock() {
  try {
    const h = await fetchJSON("/api/health");
    state.adminRequired = !!h.admin_token_required;
    const badge = document.getElementById("lock-badge");
    if (!badge) return;
    if (!state.adminRequired) {
      badge.hidden = true;
      return;
    }
    badge.hidden = false;
    if (state.token) {
      badge.textContent = "🔓 demo unlocked";
      badge.className = "lock-badge unlocked";
    } else {
      badge.textContent = "🔒 ingest + ask need passcode";
      badge.className = "lock-badge locked";
    }
  } catch {}
}

// -- Inspirations (Powered by PyCon talks) -----------------------------------

async function loadInspirations() {
  const list = document.getElementById("inspired-list");
  if (!list) return;
  try {
    const data = await fetchJSON("/api/inspirations");
    list.innerHTML = "";
    for (const item of data.inspirations || []) {
      const el = document.createElement("div");
      el.className = "inspired-item";
      const speakers = (item.speakers || []).filter((s) => s && s !== "—").join(", ");
      el.innerHTML = `
        <div class="inspired-talk">${escapeHtml(item.talk || "")}</div>
        <div class="inspired-by">${escapeHtml(speakers || "—")}${item.affiliation && item.affiliation !== "—" ? " · " + escapeHtml(item.affiliation) : ""}</div>
        <div class="inspired-use">${escapeHtml(item.used_for || "")}</div>
      `;
      el.title = "Click to pin this talk into the graph";
      el.onclick = async () => {
        try {
          await fetchJSON("/api/inspirations/pin", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ tag: item.tag }),
          });
          await loadGraph();
        } catch (e) {
          console.error(e);
        }
      };
      list.appendChild(el);
    }
    if (data.sponsors && data.sponsors.length) {
      const footer = document.createElement("div");
      footer.className = "inspired-by";
      footer.style.marginTop = "10px";
      footer.style.fontSize = "11px";
      footer.textContent =
        `${data.sponsors.length} confirmed sponsors pre-seeded: ` +
        data.sponsors.map((s) => s.label).join(", ");
      list.appendChild(footer);
    }
  } catch (e) {
    console.error(e);
  }
}

loadGraph();
loadInspirations();
refreshLock();
