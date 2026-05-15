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
};

const TYPE_SIZE = {
  event: 60, speaker: 36, talk: 30, topic: 22, repo: 24,
  paper: 22, video: 22, article: 16, sponsor: 28,
};

const state = {
  cy: null,
  hiddenTypes: new Set(),
  raw: { nodes: [], edges: [] },
};

async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
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
      data: {
        id: n.id,
        label: n.label,
        type: n.type,
        url: n.url,
      },
    });
  });

  const visibleIds = new Set(elements.map((e) => e.data.id));
  state.raw.edges.forEach((e) => {
    if (!visibleIds.has(e.source) || !visibleIds.has(e.target)) return;
    elements.push({
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        type: e.type,
      },
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
        style: {
          "border-color": "#fff",
          "border-width": 3,
        },
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
      {
        selector: "node.dimmed",
        style: { opacity: 0.18 },
      },
      {
        selector: "edge.dimmed",
        style: { opacity: 0.08 },
      },
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
  const types = Array.from(
    new Set(state.raw.nodes.map((n) => n.type))
  ).sort();
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
      `;
      srcs.appendChild(li);
    });

    card.hidden = false;
  } catch (e) {
    console.error(e);
  }
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

document.getElementById("ingest-btn").addEventListener("click", async () => {
  const btn = document.getElementById("ingest-btn");
  const log = document.getElementById("ingest-log");
  const useClaude = document.getElementById("use-claude").checked;
  const expand = document.getElementById("expand-speakers").checked;
  const extra = document.getElementById("extra-queries").value
    .split("\n").map((s) => s.trim()).filter(Boolean);

  btn.disabled = true;
  btn.textContent = "Ingesting…";
  log.textContent = "Running SerpApi crawl. This may take 30–90s.\n";

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
    if (res.errors && res.errors.length) {
      log.textContent += `\nErrors:\n${res.errors.join("\n")}`;
    }
    await loadGraph();
  } catch (e) {
    log.textContent += `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Run ingest";
  }
});

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
  } catch {}
}

loadGraph();
