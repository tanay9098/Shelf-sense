/* ShelfSense subgraph renderer: deterministic layered SVG layout (no dependencies).
 * Renders exactly the nodes/edges returned by the investigation queries.
 */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";

  const TYPES = {
    SalesVisit:  { col: 0, color: "#0891b2", fill: "#ecfeff", shape: "ellipse" },
    Delivery:    { col: 0, color: "#c2410c", fill: "#fff7ed", shape: "chevron" },
    Retailer:    { col: 1, color: "#4f46e5", fill: "#eef2ff", shape: "rect" },
    Order:       { col: 1, color: "#9333ea", fill: "#faf5ff", shape: "doc" },
    Distributor: { col: 2, color: "#0f766e", fill: "#f0fdfa", shape: "diamond" },
    Warehouse:   { col: 3, color: "#334155", fill: "#f1f5f9", shape: "house" },
    Inventory:   { col: 4, color: "#b45309", fill: "#fffbeb", shape: "box" },
    Product:     { col: 5, color: "#047857", fill: "#ecfdf5", shape: "circle" },
    Promotion:   { col: 5, color: "#be185d", fill: "#fdf2f8", shape: "hex" },
  };
  const COL_W = 176, ROW_H = 58, PAD_X = 68, PAD_Y = 36, NODE_W = 124, NODE_H = 36;

  function el(name, attrs, parent) {
    const n = document.createElementNS(NS, name);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  function shape(g, type, w, h) {
    const t = TYPES[type] || { color: "#64748b", fill: "#f8fafc", shape: "rect" };
    const a = { class: "shape", fill: t.fill, stroke: t.color, "stroke-width": 1.6 };
    const hw = w / 2, hh = h / 2;
    switch (t.shape) {
      case "circle": return el("rect", { ...a, x: -hw, y: -hh, width: w, height: h, rx: hh }, g);
      case "ellipse": return el("ellipse", { ...a, cx: 0, cy: 0, rx: hw, ry: hh }, g);
      case "diamond": return el("polygon", { ...a, points: `${-hw},0 ${-hw + 12},${-hh} ${hw - 12},${-hh} ${hw},0 ${hw - 12},${hh} ${-hw + 12},${hh}` }, g);
      case "house": return el("polygon", { ...a, points: `${-hw},${-hh + 7} 0,${-hh - 4} ${hw},${-hh + 7} ${hw},${hh} ${-hw},${hh}` }, g);
      case "box": return el("rect", { ...a, x: -hw, y: -hh, width: w, height: h, rx: 2 }, g);
      case "chevron": return el("polygon", { ...a, points: `${-hw},${-hh} ${hw - 10},${-hh} ${hw},0 ${hw - 10},${hh} ${-hw},${hh} ${-hw + 8},0` }, g);
      case "doc": return el("polygon", { ...a, points: `${-hw},${-hh} ${hw - 9},${-hh} ${hw},${-hh + 9} ${hw},${hh} ${-hw},${hh}` }, g);
      case "hex": return el("polygon", { ...a, points: `${-hw + 10},${-hh} ${hw - 10},${-hh} ${hw},0 ${hw - 10},${hh} ${-hw + 10},${hh} ${-hw},0` }, g);
      default: return el("rect", { ...a, x: -hw, y: -hh, width: w, height: h, rx: 8 }, g);
    }
  }

  function shortName(n) {
    const p = n.properties || {};
    let s = p.name || p.status || (p.visited_at ? p.visited_at.slice(0, 10) : "") || "";
    if (n.label === "Inventory") s = `qty ${p.quantity} · res ${p.reserved_quantity}`;
    if (n.label === "Order") s = `${p.status} · ${p.quantity}u`;
    return s.length > 20 ? s.slice(0, 19) + "…" : s;
  }

  function layout(nodes, highlighted) {
    const cols = {};
    nodes.forEach((n) => {
      const c = (TYPES[n.label] || { col: 6 }).col;
      (cols[c] = cols[c] || []).push(n);
    });
    const pos = {};
    let maxRows = 1;
    Object.keys(cols).forEach((c) => {
      const list = cols[c].sort((a, b) =>
        (highlighted.has(b.id) - highlighted.has(a.id)) ||
        a.label.localeCompare(b.label) || a.id.localeCompare(b.id));
      maxRows = Math.max(maxRows, list.length);
      list.forEach((n, i) => { pos[n.id] = { x: PAD_X + Number(c) * COL_W, y: PAD_Y + i * ROW_H }; });
    });
    // vertically centre short columns
    Object.keys(cols).forEach((c) => {
      const off = ((maxRows - cols[c].length) * ROW_H) / 2;
      cols[c].forEach((n) => { pos[n.id].y += off; });
    });
    const width = PAD_X * 2 + 5 * COL_W;
    const height = PAD_Y * 2 + (maxRows - 1) * ROW_H;
    return { pos, width, height };
  }

  function render(container, graph, opts) {
    opts = opts || {};
    container.innerHTML = "";
    if (!graph || !graph.nodes || graph.nodes.length === 0) {
      container.innerHTML = '<div class="graph-empty">No connected records were returned for this investigation.</div>';
      return null;
    }
    const hl = new Set(graph.highlighted_nodes || []);
    const hlEdges = new Set(graph.highlighted_edges || []);
    const { pos, width, height } = layout(graph.nodes.slice(), hl);
    const svg = el("svg", { viewBox: `0 0 ${width} ${Math.max(height, 160)}`, role: "group",
      "aria-label": `Investigation subgraph with ${graph.nodes.length} records and ${graph.edges.length} relationships` }, container);

    const defs = el("defs", {}, svg);
    [["arrow", "#c3cad8"], ["arrow-hl", "#4f46e5"]].forEach(([id, color]) => {
      const m = el("marker", { id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, defs);
      el("path", { d: "M0,0 L10,5 L0,10 z", fill: color }, m);
    });

    const edgeLayer = el("g", {}, svg);
    const labelLayer = el("g", {}, svg);
    const nodeLayer = el("g", {}, svg);
    const ordered = graph.edges.slice().sort((a, b) => hlEdges.has(a.id) - hlEdges.has(b.id));
    ordered.forEach((e) => {
      const s = pos[e.source], t = pos[e.target];
      if (!s || !t) return;
      const isHl = hlEdges.has(e.id);
      let x1 = s.x, y1 = s.y, x2 = t.x, y2 = t.y;
      const dx = x2 - x1;
      if (Math.abs(dx) > 1) {
        const dir = Math.sign(dx);
        x1 += dir * NODE_W / 2; x2 -= dir * (NODE_W / 2 + 2);
      } else {
        const dir = Math.sign(y2 - y1) || 1;
        y1 += dir * NODE_H / 2; y2 -= dir * (NODE_H / 2 + 2);
        x1 += NODE_W / 2 - 10; x2 += NODE_W / 2 - 10;
      }
      const cx = Math.abs(dx) > 1 ? (x1 + x2) / 2 : x1 + 40;
      const d = `M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}`;
      const p = el("path", { d, class: "g-edge" + (isHl ? " hl" : ""), "marker-end": `url(#${isHl ? "arrow-hl" : "arrow"})` }, edgeLayer);
      const title = el("title", {}, p); title.textContent = `${e.source} —${e.type}→ ${e.target}`;
      if (isHl && Math.abs(x2 - x1) >= 80) {
        const lt = el("text", { x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 4, "text-anchor": "middle", class: "g-edge-label" }, labelLayer);
        lt.textContent = e.type;
      }
    });

    graph.nodes.forEach((n) => {
      const p = pos[n.id];
      const g = el("g", { class: "g-node" + (hl.size && !hl.has(n.id) ? " dim" : ""), transform: `translate(${p.x},${p.y})`,
        tabindex: 0, role: "button", "aria-label": `${n.label} ${n.id}${hl.has(n.id) ? ", on investigation path" : ""}`, "data-id": n.id }, nodeLayer);
      const sh = shape(g, n.label, NODE_W, NODE_H);
      if (hl.has(n.id)) { sh.setAttribute("stroke-width", 2.4); }
      const t1 = el("text", { x: 0, y: -2, "text-anchor": "middle", class: "g-id" }, g); t1.textContent = n.id;
      const t2 = el("text", { x: 0, y: 11, "text-anchor": "middle", class: "g-name" }, g); t2.textContent = shortName(n);
      const title = el("title", {}, g); title.textContent = `${n.label} ${n.id}`;
      const select = () => {
        svg.querySelectorAll(".g-node.selected").forEach((x) => x.classList.remove("selected"));
        g.classList.add("selected");
        if (opts.onSelect) opts.onSelect(n);
      };
      g.addEventListener("click", select);
      g.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(); } });
    });

    return {
      select(id) {
        const g = svg.querySelector(`.g-node[data-id="${CSS.escape(id)}"]`);
        if (g) { g.dispatchEvent(new Event("click")); g.focus({ preventScroll: true }); g.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" }); }
        return !!g;
      },
    };
  }

  function legend(container, labels) {
    container.innerHTML = "";
    Object.keys(TYPES).filter((t) => !labels || labels.has(t)).forEach((t) => {
      const item = document.createElement("span"); item.className = "legend-item";
      const svg = el("svg", { viewBox: "-10 -10 20 20", "aria-hidden": "true" }, item);
      shape(el("g", {}, svg), t, 18, 14);
      item.appendChild(document.createTextNode(t));
      container.appendChild(item);
    });
    const hl = document.createElement("span"); hl.className = "legend-item";
    hl.innerHTML = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M2 10h16" stroke="#4f46e5" stroke-width="3"/></svg>Investigation path';
    container.appendChild(hl);
  }

  window.ShelfGraph = { render, legend };
})();
