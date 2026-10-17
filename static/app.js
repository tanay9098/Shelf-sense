/* ShelfSense dashboard. Vanilla JS, no build step. */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const state = { result: null, request: null, allowlist: null, graphApi: null, scenarioId: null };

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtNum = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-IN"));
  const fmtTime = (s) => {
    if (!s) return "—";
    const d = new Date(s);
    return isNaN(d) ? s : d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
  };
  const STATUS_LABEL = { supported: "Supported by records", hypothesis: "Hypothesis", record_gap: "Record gap",
    undetermined: "Undetermined", not_applicable: "No stockout" };

  class ApiError extends Error {
    constructor(code, message, status, details) { super(message); this.code = code; this.status = status; this.details = details; }
  }

  async function api(path, options) {
    let res;
    try {
      res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
    } catch (e) {
      throw new ApiError("NETWORK", "Cannot reach the ShelfSense API. Is the server running?", 0);
    }
    let body = null;
    try { body = await res.json(); } catch (e) { /* non-JSON */ }
    if (!res.ok) {
      const err = (body && body.error) || {};
      throw new ApiError(err.code || "HTTP_" + res.status, err.message || (body && body.database && body.database.message) || `Request failed (${res.status}).`, res.status, err.details);
    }
    return body;
  }

  /* ---------------- health */
  async function checkHealth() {
    const pill = $("#db-status");
    try {
      const res = await fetch("/api/health");
      const body = await res.json();
      const ok = body.database && body.database.connected;
      pill.className = "status-pill " + (ok ? "ok" : "down");
      const counts = ok && body.database.counts ? ` · ${fmtNum(body.database.counts.total_nodes)} nodes` : "";
      pill.querySelector(".label").textContent = ok ? `FalkorDB connected${counts}` : "FalkorDB unavailable";
      pill.title = ok ? `Graph '${body.database.graph}' · demo clock ${body.demo_clock}` : (body.database.message || "");
      return ok;
    } catch (e) {
      pill.className = "status-pill down";
      pill.querySelector(".label").textContent = "API unreachable";
      return false;
    }
  }

  /* ---------------- bootstrap data */
  async function loadReferenceData() {
    try {
      const [sc, rs, ps, al] = await Promise.all([api("/api/demo/scenarios"), api("/api/retailers"), api("/api/products"), api("/api/demo/mutations")]);
      state.allowlist = al.allowed;
      renderScenarios(sc.scenarios);
      fillSelect($("#retailer"), rs.retailers.map((r) => [r.id, `${r.id} · ${r.name} (${r.location})`]));
      fillSelect($("#product"), ps.products.map((p) => [p.id, `${p.id} · ${p.name}`]));
    } catch (e) {
      $("#scenarios").innerHTML = `<p class="form-error">Could not load demo data: ${esc(e.message)}</p>`;
    }
  }

  function fillSelect(sel, items) {
    sel.querySelectorAll("option:not(:first-child)").forEach((o) => o.remove());
    items.forEach(([v, label]) => { const o = document.createElement("option"); o.value = v; o.textContent = label; sel.appendChild(o); });
  }

  function renderScenarios(list) {
    const wrap = $("#scenarios");
    wrap.innerHTML = "";
    list.forEach((s) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "scenario"; b.dataset.id = s.id;
      b.innerHTML = `<span class="scenario-top"><span class="scenario-key">${esc(s.id)}</span><span class="scenario-title">${esc(s.title)}</span></span>
        <span class="scenario-ids">${esc(s.retailer_id)} × ${esc(s.product_id)}</span>
        <span class="scenario-teaser">${esc(s.teaser)}</span>`;
      b.addEventListener("click", () => {
        $("#question").value = s.question;
        $("#retailer").value = ""; $("#product").value = "";
        state.scenarioId = s.id;
        hideComparison();
        runInvestigation({ scenario_id: s.id });
      });
      wrap.appendChild(b);
    });
  }

  function markScenario(id) {
    document.querySelectorAll(".scenario").forEach((b) => b.classList.toggle("active", b.dataset.id === id));
  }

  /* ---------------- investigation */
  function setView(view) {
    $("#empty-state").hidden = view !== "empty";
    $("#loading").hidden = view !== "loading";
    $("#error-state").hidden = view !== "error";
    $("#result").hidden = view !== "result";
    $("#results").setAttribute("aria-busy", view === "loading" ? "true" : "false");
  }

  async function runInvestigation(payload, opts) {
    opts = opts || {};
    const btn = $("#investigate-btn");
    btn.disabled = true; btn.querySelector("span").textContent = "Investigating…";
    if (!opts.silent) setView("loading");
    try {
      const result = await api("/api/investigate", { method: "POST", body: JSON.stringify(payload) });
      state.request = { retailer_id: result.retailer.id, product_id: result.product.id, question: result.question || undefined };
      state.result = result;
      markScenario(result.scenario_id);
      renderResult(result);
      setView("result");
      return result;
    } catch (e) {
      const el = $("#error-state");
      let extra = "";
      if (e.details && e.details.candidates) extra = `<p>Candidates: ${e.details.candidates.map(esc).join(", ")}. Choose one in the selectors.</p>`;
      if (e.details && e.details.issues) extra = `<ul>${e.details.issues.map((i) => `<li>${esc(i.field)}: ${esc(i.message)}</li>`).join("")}</ul>`;
      el.innerHTML = `<strong>${esc(e.code === "DATABASE_UNAVAILABLE" ? "FalkorDB is unavailable" : "Investigation could not run")}</strong><p>${esc(e.message)}</p>${extra}`;
      setView("error");
      if (e.code === "DATABASE_UNAVAILABLE") checkHealth();
      throw e;
    } finally {
      btn.disabled = false; btn.querySelector("span").textContent = "Investigate";
    }
  }

  function renderResult(r) {
    const pc = r.probable_cause;
    $("#result-meta").textContent = `${r.investigation_id} · demo clock ${r.demo_clock} · ${r.resolved_by} · ${r.data_mode} data`;
    $("#cause-label").textContent = pc.label;
    $("#entity-line").innerHTML = `<strong>${esc(r.retailer.name)}</strong> (${esc(r.retailer.id)}, ${esc(r.retailer.location)}) · <strong>${esc(r.product.name)}</strong> (${esc(r.product.id)})`;
    $("#cause-pills").innerHTML = `<span class="pill pill-status" title="${esc(pc.status_meaning)}">${esc(STATUS_LABEL[pc.status] || pc.status)}</span>
      <span class="pill pill-${esc(pc.confidence)}" title="${esc(pc.confidence_basis)}">Confidence: ${esc(pc.confidence)}</span>`;
    $("#summary").textContent = r.summary;
    $("#summary-source").textContent = r.summary_source === "llm"
      ? "Summary written by the LLM from the evidence payload and validated against returned record IDs."
      : "Deterministic evidence-based summary." + (r.summary_note ? ` (${r.summary_note})` : "");
    $("#confidence-basis").innerHTML = `<strong>Why ${esc(pc.confidence)} confidence:</strong> ${esc(pc.confidence_basis)} <span class="muted">Qualitative rule, not a probability.</span>`;

    renderStock(r.stock_summary);
    renderActions(r.recommended_actions);
    renderFacts(r);
    renderGaps(r);
    renderHypothesis(r.hypothesis_tests);
    renderEvidence(r.evidence);
    renderGraph(r);
    renderMutations(r);
    renderTrace(r.query_trace);
  }

  function renderStock(s) {
    const el = $("#stock-summary");
    let html = "";
    if (s.retailer) {
      html += `<div class="stock-retailer"><span class="stock-big ${s.retailer.available === 0 ? "zero" : ""}">${fmtNum(s.retailer.available)}</span>
        <span>available at retailer <span class="muted small">(${fmtNum(s.retailer.quantity)} physical · record <span class="mono">${esc(s.retailer.record_id)}</span> · captured ${esc(fmtTime(s.retailer.captured_at))})</span></span></div>`;
    } else {
      html += `<div class="stock-retailer"><span class="stock-big">?</span><span>No retailer stock record returned</span></div>`;
    }
    if (s.route.length) {
      html += `<div class="table-scroll"><table class="stock-table"><thead><tr><th>Route warehouse</th><th class="num">Physical</th><th class="num">Reserved</th><th class="num">Available</th></tr></thead><tbody>`;
      s.route.forEach((w) => {
        if (w.record_id === null) {
          html += `<tr><td><strong>${esc(w.warehouse_id)}</strong> ${esc(w.warehouse)}<div class="muted small">via ${esc(w.distributor_id)} · priority ${esc(w.priority)}</div></td><td colspan="3" class="muted">No inventory record returned</td></tr>`;
          return;
        }
        const q = w.quantity || 0, a = w.available || 0, res = w.reserved || 0;
        const pa = q ? (a / q) * 100 : 0, pr = q ? (Math.min(res, q) / q) * 100 : 0;
        html += `<tr><td><strong>${esc(w.warehouse_id)}</strong> ${esc(w.warehouse)}<div class="muted small">via ${esc(w.distributor_id)} · priority ${esc(w.priority)} · <span class="mono">${esc(w.record_id)}</span></div>
          <div class="bar" title="green = available, amber = reserved"><span class="avail" style="width:${pa}%"></span><span class="res" style="width:${pr}%"></span></div></td>
          <td class="num">${fmtNum(q)}</td><td class="num">${fmtNum(res)}</td><td class="num"><strong>${fmtNum(a)}</strong></td></tr>`;
      });
      html += `</tbody></table></div><p class="muted small" style="margin-top:6px">Available = physical − reserved (computed in the Cypher query).</p>`;
    } else {
      html += `<p class="empty-note">No supply route (SERVED_BY → SOURCES_FROM) was returned.</p>`;
    }
    if (s.off_route.length) {
      html += `<p class="offroute"><strong>Off-route stock:</strong> ${s.off_route.map((o) => `${esc(o.warehouse_id)} ${esc(o.warehouse)} (${fmtNum(o.available)} avail.)`).join(", ")} — not connected to this retailer by any recorded route.</p>`;
    }
    el.innerHTML = html;
  }

  function renderActions(actions) {
    $("#actions").innerHTML = actions.length ? actions.map((a) => `<li><div class="action-text"><span class="prio prio-${esc(a.priority)}">${esc(a.priority)}</span>${esc(a.action)}</div>
      <div class="action-meta">Owner: ${esc(a.owner)} · ${esc(a.rationale)}</div></li>`).join("") : `<li class="empty-note">No actions suggested.</li>`;
  }

  function chips(ids) {
    return ids && ids.length ? `<div class="chips">${ids.map((id) => `<button type="button" class="chip" data-node="${esc(id)}" title="Show ${esc(id)} in graph">${esc(id)}</button>`).join("")}</div>` : "";
  }

  function renderFacts(r) {
    $("#facts").innerHTML = r.observed_facts.map((f) => `<li><span class="fact-id">${esc(f.id)}</span>${esc(f.statement)}${chips(f.record_ids)}</li>`).join("")
      || `<li class="empty-note">No facts returned.</li>`;
    $("#inferences").innerHTML = r.inferences.map((i) => `<li><span class="fact-id">${esc(i.id)}</span>${esc(i.statement)}
      ${i.based_on.length ? `<div class="chips">${i.based_on.map((b) => `<span class="chip chip-ref" title="Based on ${esc(b)}">${esc(b)}</span>`).join("")}</div>` : ""}</li>`).join("")
      || `<li class="empty-note">No inferences drawn.</li>`;
  }

  function renderGaps(r) {
    $("#missing").innerHTML = r.missing_information.map((m) => `<li><strong>${esc(m.item)}</strong><div class="why">${esc(m.why_it_matters)}</div><div class="check">Next check: ${esc(m.suggested_check)}</div></li>`).join("")
      || `<li class="empty-note" style="background:none;border:0">No missing records detected for this investigation.</li>`;
    $("#contradictions").innerHTML = r.contradictions.length
      ? `<h4 class="card-title" style="margin-top:14px">Contradictory records</h4><ul class="gap-list contra">${r.contradictions.map((c) => `<li>${esc(c.statement)}${chips(c.record_ids)}</li>`).join("")}</ul>` : "";
  }

  function renderHypothesis(h) {
    const list = (arr) => arr && arr.length ? `<ul>${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="empty-note">—</p>`;
    $("#hypothesis").innerHTML = `<div class="hyp"><h4>Would strengthen this conclusion</h4>${list(h.would_strengthen)}<h4>Would weaken it</h4>${list(h.would_weaken)}</div>`;
  }

  const HIDDEN_PROPS = new Set(["id"]);
  function propList(props) {
    return `<dl class="ev-props">${Object.entries(props).filter(([k, v]) => !HIDDEN_PROPS.has(k) && v !== null && v !== "").map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;
  }

  function renderEvidence(cards) {
    $("#evidence").innerHTML = cards.map((c) => `<article class="ev-card ${c.in_path ? "in-path" : ""}">
      <div class="ev-head"><button type="button" class="chip ev-id" data-node="${esc(c.record_id)}">${esc(c.record_id)}</button><span class="ev-type">${esc(c.entity_type)}</span></div>
      <p class="ev-why">${esc(c.relevance)}</p>${propList(c.properties)}
      <span class="ev-class">● Observed record${c.in_path ? " · on investigation path" : ""}</span></article>`).join("")
      || `<p class="empty-note">No evidence records.</p>`;
  }

  function renderGraph(r) {
    const g = r.graph;
    $("#graph-meta").textContent = `${g.nodes.length} records · ${g.edges.length} relationships returned by ${r.query_trace.length} queries`;
    $("#graph-path").innerHTML = r.graph_path.map((s) => `<li><span class="nid">${esc(s.from)}</span><span class="rel">—${esc(s.relationship)}→</span><span class="nid">${esc(s.to)}</span></li>`).join("")
      || `<li class="muted" style="background:none;border:0">No highlighted path.</li>`;
    const detail = $("#node-detail");
    detail.innerHTML = `<p class="muted small">Select a node (click or Tab + Enter) to see the record.</p>`;
    try {
      state.graphApi = window.ShelfGraph.render($("#graph"), g, {
        onSelect(n) {
          detail.innerHTML = `<h4>${esc(n.id)}</h4><p class="ev-type">${esc(n.label)}${g.highlighted_nodes.includes(n.id) ? " · on path" : ""}</p>${propList(n.properties)}`;
        },
      });
      window.ShelfGraph.legend($("#graph-legend"), new Set(g.nodes.map((n) => n.label)));
    } catch (e) {
      $("#graph").innerHTML = `<div class="graph-empty">The graph could not be drawn (${esc(e.message)}). The evidence below is unaffected.</div>`;
    }
  }

  function renderTrace(trace) {
    const total = trace.reduce((s, t) => s + t.duration_ms, 0);
    $("#trace-meta").textContent = `${trace.length} parameterised queries · ${total.toFixed(1)} ms in FalkorDB`;
    $("#trace").innerHTML = trace.map((t) => `<div class="trace-item"><div class="trace-head"><span class="mono">${esc(t.tool)}</span>
      <span class="muted small">${esc(t.purpose)}</span><span class="muted small">${t.rows_returned} rows · ${t.duration_ms} ms</span></div>
      <pre>${esc(t.cypher)}\n\nparams: ${esc(JSON.stringify(t.params))}</pre></div>`).join("");
  }

  /* ---------------- mutation panel */
  function renderMutations(r) {
    const wrap = $("#mutations");
    const al = state.allowlist || {};
    const records = r.evidence.filter((c) => (c.entity_type === "Delivery" && al.Delivery) || (c.entity_type === "Inventory" && al.Inventory));
    if (!records.length) {
      wrap.innerHTML = `<p class="empty-note">This investigation returned no editable Delivery or Inventory records.</p>`;
      return;
    }
    wrap.innerHTML = "";
    records.forEach((c) => {
      const row = document.createElement("div"); row.className = "mut-row";
      const p = c.properties;
      if (c.entity_type === "Delivery") {
        const opts = al.Delivery.status.values.map((v) => `<option value="${esc(v)}" ${v === p.status ? "selected" : ""}>${esc(v)}</option>`).join("");
        row.innerHTML = `<div class="mut-rec"><span class="mono">${esc(c.record_id)}</span> <span class="ev-type">Delivery</span><div class="mut-current">Current status: <strong>${esc(p.status)}</strong> · expected ${esc(fmtTime(p.expected_at))}</div></div>
          <div><label class="field-label" for="m-${esc(c.record_id)}">New status</label><select id="m-${esc(c.record_id)}">${opts}</select></div>
          <button type="button" class="btn btn-primary btn-sm">Apply &amp; re-run</button>`;
        row.querySelector("button").addEventListener("click", () => {
          const v = row.querySelector("select").value;
          if (v === p.status) return showMutationMsg(`${c.record_id} is already '${v}'. Choose a different status.`, false);
          applyMutation({ entity_type: "Delivery", record_id: c.record_id, field: "status", value: v },
            `Change delivery <strong>${esc(c.record_id)}</strong> status from <strong>${esc(p.status)}</strong> to <strong>${esc(v)}</strong>?` +
            (v === "delivered" ? " The linked order becomes 'delivered'. Retailer inventory is <em>not</em> changed automatically." : ""));
        });
      } else {
        row.innerHTML = `<div class="mut-rec"><span class="mono">${esc(c.record_id)}</span> <span class="ev-type">Inventory · ${esc(p.location_type)}</span><div class="mut-current">Physical ${fmtNum(p.quantity)} · reserved ${fmtNum(p.reserved_quantity)} · available ${fmtNum(p.available_quantity)}</div></div>
          <div class="mut-fields"><div><label for="mq-${esc(c.record_id)}">Physical qty</label><input type="number" min="0" max="100000" step="1" id="mq-${esc(c.record_id)}" value="${esc(p.quantity)}"></div>
          <div><label for="mr-${esc(c.record_id)}">Reserved</label><input type="number" min="0" max="100000" step="1" id="mr-${esc(c.record_id)}" value="${esc(p.reserved_quantity)}"></div></div>
          <button type="button" class="btn btn-primary btn-sm">Apply &amp; re-run</button>`;
        row.querySelector("button").addEventListener("click", () => {
          const q = row.querySelector(`#mq-${CSS.escape(c.record_id)}`).value.trim();
          const rs = row.querySelector(`#mr-${CSS.escape(c.record_id)}`).value.trim();
          const qn = Number(q), rn = Number(rs);
          if (!/^\d+$/.test(q) || !/^\d+$/.test(rs)) return showMutationMsg("Quantities must be whole numbers ≥ 0.", false);
          if (rn > qn) return showMutationMsg("Reserved cannot exceed physical quantity.", false);
          const field = qn !== Number(p.quantity) ? "quantity" : (rn !== Number(p.reserved_quantity) ? "reserved_quantity" : null);
          if (!field) return showMutationMsg("No change entered.", false);
          if (qn !== Number(p.quantity) && rn !== Number(p.reserved_quantity)) return showMutationMsg("Change one field at a time so the before/after comparison stays clear.", false);
          const value = field === "quantity" ? qn : rn;
          applyMutation({ entity_type: "Inventory", record_id: c.record_id, field, value },
            `Set <strong>${esc(c.record_id)}</strong> ${esc(field.replace("_", " "))} from <strong>${fmtNum(p[field])}</strong> to <strong>${fmtNum(value)}</strong>? Available quantity will be recomputed.`);
        });
      }
      wrap.appendChild(row);
    });
  }

  function confirmDialog(html, okLabel) {
    const dlg = $("#confirm-dialog");
    $("#confirm-text").innerHTML = html;
    $("#confirm-ok").textContent = okLabel || "Apply";
    if (typeof dlg.showModal !== "function") return Promise.resolve(window.confirm($("#confirm-text").textContent));
    return new Promise((resolve) => {
      dlg.addEventListener("close", () => resolve(dlg.returnValue === "ok"), { once: true });
      dlg.showModal();
    });
  }

  function showMutationMsg(text, ok) {
    const m = $("#mutation-msg");
    m.hidden = false; m.className = "mutation-msg " + (ok ? "ok" : "err"); m.textContent = text;
  }

  async function applyMutation(payload, confirmHtml) {
    if (!(await confirmDialog(confirmHtml, "Apply change"))) return;
    const before = state.result;
    let mutation;
    try {
      mutation = await api("/api/demo/mutate", { method: "POST", body: JSON.stringify({ ...payload, confirm: true }) });
    } catch (e) {
      return showMutationMsg(`Change rejected: ${e.message}`, false);
    }
    try {
      const after = await runInvestigation({ ...state.request }, { silent: true });
      renderComparison(before, after, mutation);
      showMutationMsg(`Saved ${mutation.record_id}.${mutation.field} in FalkorDB and re-ran ${after.query_trace.length} graph queries.`, true);
    } catch (e) {
      showMutationMsg(`Record saved, but the re-run failed: ${e.message}`, false);
    }
  }

  function renderComparison(before, after, mutation) {
    const col = (r, cls) => `<div class="cmp-col ${cls}"><h4>${cls === "after" ? "After" : "Before"} · ${esc(r.investigation_id)}</h4>
      <div class="cmp-cause">${esc(r.probable_cause.label)}</div>
      <div class="pills"><span class="pill pill-status">${esc(STATUS_LABEL[r.probable_cause.status])}</span><span class="pill pill-${esc(r.probable_cause.confidence)}">Confidence: ${esc(r.probable_cause.confidence)}</span></div>
      <p style="margin-top:8px">${esc(r.summary)}</p>
      <p class="muted small" style="margin-top:6px">Retailer available: ${fmtNum(r.stock_summary.retailer && r.stock_summary.retailer.available)} · ${r.missing_information.length} gaps · ${r.contradictions.length} contradictions</p></div>`;
    const b = mutation.before.delivery || mutation.before;
    const a = mutation.after.delivery || mutation.after;
    const changed = Object.keys(a).filter((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]));
    $("#comparison-body").innerHTML = `<div class="cmp-grid">${col(before, "before")}<div class="cmp-arrow" aria-hidden="true">→</div>${col(after, "after")}</div>
      <p class="cmp-change"><strong>Record change in FalkorDB:</strong> ${esc(mutation.entity_type)} <span class="mono">${esc(mutation.record_id)}</span> —
      ${changed.map((k) => `<span class="mono">${esc(k)}</span>: ${esc(b[k] ?? "∅")} → <strong>${esc(a[k] ?? "∅")}</strong>`).join("; ")}.
      ${mutation.side_effects.length ? `Side effects: ${mutation.side_effects.map(esc).join("; ")}.` : ""}</p>
      <p class="muted small">The after-state was produced by re-running every graph query; no conclusion was cached.</p>`;
    $("#comparison").hidden = false;
    $("#comparison").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function hideComparison() { $("#comparison").hidden = true; $("#mutation-msg").hidden = true; }

  /* ---------------- events */
  $("#investigate-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = $("#question").value.trim();
    const rid = $("#retailer").value, pid = $("#product").value;
    const errEl = $("#form-error");
    errEl.hidden = true;
    if (!q && !(rid && pid)) {
      errEl.textContent = "Enter a question, or choose both a retailer and a product.";
      errEl.hidden = false;
      return;
    }
    const payload = {};
    if (q) payload.question = q;
    if (rid) payload.retailer_id = rid;
    if (pid) payload.product_id = pid;
    state.scenarioId = null;
    hideComparison();
    runInvestigation(payload).catch(() => {});
  });

  $("#question").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) $("#investigate-form").requestSubmit();
  });

  document.addEventListener("click", (ev) => {
    const chip = ev.target.closest("[data-node]");
    if (!chip || !state.graphApi) return;
    if (state.graphApi.select(chip.dataset.node)) $("#graph").scrollIntoView({ behavior: "smooth", block: "center" });
  });

  $("#dismiss-comparison").addEventListener("click", hideComparison);

  $("#reset-btn").addEventListener("click", async () => {
    if (!(await confirmDialog("Restore the deterministic seed dataset? All record changes made in this demo will be discarded.", "Reset data"))) return;
    try {
      const res = await api("/api/demo/reset", { method: "POST" });
      hideComparison();
      checkHealth();
      if (state.request) await runInvestigation({ ...state.request }, { silent: true });
      showMutationMsg(`Seed data restored (${fmtNum(res.counts.total_nodes)} nodes, ${fmtNum(res.counts.total_relationships)} relationships). Investigation re-run.`, true);
    } catch (e) {
      showMutationMsg(`Reset failed: ${e.message}`, false);
    }
  });

  /* ---------------- init */
  setView("empty");
  checkHealth().then(() => loadReferenceData());
  setInterval(checkHealth, 20000);
})();
