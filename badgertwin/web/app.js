// BadgerTwin front end: plain JS, no build step. Every number comes from the API.
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const fmt = (n, d = 0) => (n === null || n === undefined || Number.isNaN(n)) ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const money = (n) => "$" + fmt(n);
const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "")) ? u : "#");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    throw new Error(Array.isArray(d) ? d.map((x) => `${(x.loc || []).slice(-1)[0]}: ${x.msg}`).join("; ") : d || res.statusText);
  }
  return data;
}

const S = { meta: null, net: null, hours: [], idx: 0, timer: null, state: null, incidentId: null, workOrder: null, plan: null, alert: null };

// ---------------------------------------------------------------- navigation
function show(screen) {
  $$(".screen").forEach((el) => el.classList.toggle("active", el.id === "screen-" + screen));
  $$(".tab").forEach((el) => el.classList.toggle("active", el.dataset.screen === screen));
  if (screen === "plan" && !S.plan) solvePlan();
  if (screen === "repairs") loadRepairs();
  if (screen === "sources") loadSources();
  if (screen === "incident") renderIncident();
}
$$("[data-screen]").forEach((b) => b.addEventListener("click", () => show(b.dataset.screen)));

// ---------------------------------------------------------------- map
let proj = null;
function makeProjection(points, w = 1000, h = 560, pad = 30) {
  const lats = points.map((p) => p.lat), lons = points.map((p) => p.lon);
  const lat0 = (Math.min(...lats) + Math.max(...lats)) / 2, k = Math.cos((lat0 * Math.PI) / 180);
  const minX = Math.min(...lons) * k, maxX = Math.max(...lons) * k, minY = Math.min(...lats), maxY = Math.max(...lats);
  const s = Math.min((w - 2 * pad) / (maxX - minX), (h - 2 * pad) / (maxY - minY));
  const ox = (w - (maxX - minX) * s) / 2, oy = (h - (maxY - minY) * s) / 2;
  return (lat, lon) => [ox + (lon * k - minX) * s, oy + (maxY - lat) * s];
}
const pipeWidth = (d) => Math.max(1.2, d / 6);

function drawNetwork(svg, opts = {}) {
  const { nodes, pipes, buildings, plants } = S.net;
  const at = Object.fromEntries(nodes.map((n) => [n.node_id, proj(n.lat, n.lon)]));
  const pipeLabel = opts.pipeLabel || (() => "Normal");
  const bLabel = opts.buildingLabel || (() => "Normal");
  let html = "";
  for (const p of pipes) {
    const [x1, y1] = at[p.from_node], [x2, y2] = at[p.to_node];
    html += `<line class="pipe ${pipeLabel(p)}" data-pipe="${esc(p.pipe_id)}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke-width="${pipeWidth(p.diameter_in)}"><title>${esc(p.pipe_id)} · ${esc(p.diameter_in)}-in · ${esc(p.install_year)}</title></line>`;
  }
  for (const b of buildings) {
    const [x, y] = proj(b.lat, b.lon);
    const r = 4 + Math.sqrt(b.design_cooling_tons) / 7;
    html += `<circle class="bldg ${bLabel(b)}" data-b="${esc(b.building_id)}" cx="${x}" cy="${y}" r="${r}"></circle>`;
  }
  for (const p of plants) {
    const [x, y] = proj(p.lat, p.lon);
    html += `<rect class="plant" x="${x - 8}" y="${y - 8}" width="16" height="16"><title>${esc(p.name)}</title></rect>
             <text class="plant-label" x="${x + 12}" y="${y + 4}">${esc(p.name.replace(/ Heating.*| Cogeneration.*/, ""))}</text>`;
  }
  html += opts.extra || "";
  svg.innerHTML = html;
}

// tooltip for the campus map
function wireTooltip() {
  const svg = $("#map"), tip = $("#tooltip");
  svg.addEventListener("mousemove", (e) => {
    const id = e.target.dataset.b, pid = e.target.dataset.pipe;
    if (!id && !pid) { tip.hidden = true; return; }
    let text = "";
    if (id) {
      const b = S.net.buildings.find((x) => x.building_id === id);
      const st = S.state?.buildings.find((x) => x.building_id === id) || {};
      text = `<b>${esc(b.name)}</b><br>${esc(b.use)} · needs ~${fmt(b.design_cooling_tons)} tons at peak (estimated)<br>Indoor ${fmt(st.indoor_f, 1)} °F · water ${fmt(st.flow_gpm)} gpm${b.affected_2026 ? "<br>Affected in 2026 (" + esc(b.status_2026) + ")" : ""}`;
    } else {
      const p = S.net.pipes.find((x) => x.pipe_id === pid);
      const st = S.state?.pipes.find((x) => x.pipe_id === pid) || {};
      text = `<b>${esc(p.pipe_id)}</b> · ${esc(p.diameter_in)}-in ${esc(p.material)}<br>Built ${esc(p.install_year)}, ${esc(p.depth_ft)} ft deep · ${esc(st.label || "")}<br><span class="muted">Click to ask about it</span>`;
    }
    const box = svg.parentElement.getBoundingClientRect();
    tip.innerHTML = text; tip.hidden = false;
    tip.style.left = Math.min(e.clientX - box.left + 12, box.width - 270) + "px";
    tip.style.top = (e.clientY - box.top + 12) + "px";
  });
  svg.addEventListener("mouseleave", () => (tip.hidden = true));
  svg.addEventListener("click", (e) => {
    const pid = e.target.dataset.pipe, id = e.target.dataset.b;
    if (!pid && !id) return;
    const name = pid || S.net.buildings.find((x) => x.building_id === id).name;
    $("#ask-input").value = pid ? `How old is ${pid} and what has failed near it?` : `Tell me about ${name}`;
    ask();
  });
}

// ---------------------------------------------------------------- make-up water chart
function drawMakeup(series, leak) {
  const svg = $("#makeup-chart"), W = 420, H = 180, L = 52, R = 8, T = 10, B = 24;
  const pts = series.filter((d) => d.gal_per_day !== null);
  if (!pts.length) { svg.innerHTML = ""; return; }
  const capped = pts.map((d) => Math.min(d.gal_per_day, 150000));
  const ymax = Math.max(leak.threshold_gal_per_day * 1.6, ...capped) * 1.05;
  const x = (i) => L + (i / Math.max(pts.length - 1, 1)) * (W - L - R);
  const y = (v) => T + (1 - v / ymax) * (H - T - B);
  const band = [leak.baseline_gal_per_day - 2 * (leak.threshold_gal_per_day - leak.baseline_gal_per_day) / 4, leak.baseline_gal_per_day + 2 * (leak.threshold_gal_per_day - leak.baseline_gal_per_day) / 4];
  const path = capped.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const ticks = [0, ymax / 2, ymax].map((v) => `<text class="map-label" x="${L - 6}" y="${y(v) + 4}" text-anchor="end" font-size="11">${fmt(v / 1000)}k</text>`).join("");
  const days = [0, Math.floor(pts.length / 2), pts.length - 1].map((i) => `<text class="map-label" x="${x(i)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle"}" font-size="11">${pts[i].timestamp.slice(5, 10)}</text>`).join("");
  const color = leak.alert ? "var(--act)" : "var(--ink)";
  const off = capped.some((v, i) => v < pts[i].gal_per_day) ? `<text class="map-label" x="${W - R}" y="${T + 10}" text-anchor="end" font-size="11">off the chart: ${fmt(Math.max(...pts.map((d) => d.gal_per_day)))}</text>` : "";
  svg.innerHTML = `<rect x="${L}" y="${y(band[1])}" width="${W - L - R}" height="${Math.max(1, y(band[0]) - y(band[1]))}" fill="var(--band)"></rect>
    <line x1="${L}" x2="${W - R}" y1="${y(leak.threshold_gal_per_day)}" y2="${y(leak.threshold_gal_per_day)}" stroke="var(--muted)" stroke-dasharray="4 4"></line>
    <path d="${path}" fill="none" stroke="${color}" stroke-width="2"></path>${ticks}${days}${off}`;
}

// ---------------------------------------------------------------- replay
function setIdx(i, fetchNow = true) {
  S.idx = Math.max(0, Math.min(S.hours.length - 1, i));
  $("#slider").value = S.idx;
  $("#replay-label").textContent = new Date(S.hours[S.idx].replace(" ", "T")).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", year: "numeric" });
  if (fetchNow) loadState();
}
let inflight = null, pending = false;
async function loadState() {
  if (inflight) { pending = true; return; }
  const t = S.hours[S.idx];
  inflight = api("/api/state?t=" + encodeURIComponent(t));
  try { S.state = await inflight; renderCampus(); } catch (e) { console.error(e); }
  inflight = null;
  if (pending) { pending = false; loadState(); }
}
function renderCampus() {
  const st = S.state, leak = st.leak;
  const pl = Object.fromEntries(st.pipes.map((p) => [p.pipe_id, p.label]));
  const bl = Object.fromEntries(st.buildings.map((b) => [b.building_id, b.label]));
  drawNetwork($("#map"), { pipeLabel: (p) => pl[p.pipe_id], buildingLabel: (b) => bl[b.building_id] });
  $("#outdoor").textContent = st.outdoor_f !== null ? ` · outside ${fmt(st.outdoor_f)} °F (real weather)` : "";
  const card = $("#status-card");
  card.className = "card status " + leak.kind;
  $("#status-kind").textContent = { normal: "All normal", leak: "Leak alert", burst: "Pipe break", isolated: "Reduced cooling" }[leak.kind];
  $("#status-headline").textContent = leak.headline;
  $("#status-evidence").innerHTML = leak.evidence.slice(0, 4).map((e) => `<li>${esc(e)}</li>`).join("");
  const open = st.open_incidents[0];
  const btn = $("#open-incident");
  btn.disabled = !leak.alert && !open;
  btn.textContent = open ? `View incident ${open.id}` : "Open incident";
  $("#open-hint").textContent = leak.alert ? "" : open ? "" : "Enabled when there is an alert.";
  drawMakeup(st.makeup, leak);
}
function play() {
  if (S.timer) { clearInterval(S.timer); S.timer = null; $("#play").textContent = "▶ Play"; return; }
  $("#play").textContent = "❚❚ Pause";
  S.timer = setInterval(() => {
    const step = Number($("#speed").value);
    if (S.idx >= S.hours.length - 1) return play();
    setIdx(S.idx + step);
  }, 350);
}

// ---------------------------------------------------------------- Q&A
async function ask(e) {
  if (e) e.preventDefault();
  const q = $("#ask-input").value.trim();
  if (!q) return;
  $("#ask-answer").textContent = "Looking it up…";
  try {
    const r = await api("/api/ask", { question: q, t: S.hours[S.idx] });
    const cites = r.citations.map((c) => c.url ? `<a href="${esc(safeUrl(c.url))}" target="_blank" rel="noopener">${esc(c.title)}</a>` : esc(c.title));
    $("#ask-answer").innerHTML = esc(r.answer) + (cites.length ? `<span class="cite">Sources: ${cites.join(" · ")}</span>` : "");
  } catch (err) { $("#ask-answer").textContent = err.message; }
}

// ---------------------------------------------------------------- incident
async function openIncident() {
  const open = S.state.open_incidents[0];
  try {
    if (open) { S.incidentId = open.id; }
    else { const r = await api("/api/incidents", { t: S.hours[S.idx] }); S.incidentId = r.incident.id; }
    show("incident");
  } catch (e) { alert(e.message); }
}
async function renderIncident() {
  if (!S.incidentId) {
    const open = S.state?.open_incidents?.[0];
    if (open) S.incidentId = open.id;
  }
  $("#incident-empty").hidden = !!S.incidentId;
  $("#incident-body").hidden = !S.incidentId;
  if (!S.incidentId) return;
  const r = await api("/api/incidents/" + S.incidentId);
  const inc = r.incident, wo = r.work_orders[r.work_orders.length - 1];
  S.workOrder = wo;
  $("#inc-title").textContent = `Incident ${inc.id}`;
  $("#inc-status").textContent = inc.status;
  $("#inc-headline").textContent = inc.headline;
  $("#inc-suspects tbody").innerHTML = inc.top3.map((s, i) => `<tr><td><b>${i + 1}. ${esc(s.pipe_id)}</b></td><td>${esc(s.from_node)} → ${esc(s.to_node)}</td><td>${esc(s.reason)}</td></tr>`).join("");
  $("#inc-diagnosis").textContent = inc.diagnosis;
  $("#inc-evidence").innerHTML = inc.evidence.map((e) => `<li>${esc(e)}</li>`).join("");
  if (!wo) return;
  $("#wo-status").textContent = wo.status + (wo.approved_by ? ` by ${wo.approved_by}` : "");
  $("#wo-type").value = wo.type; $("#wo-priority").value = wo.priority; $("#wo-crew").value = wo.crew;
  $("#wo-parts").value = wo.parts; $("#wo-valves").value = (wo.valves_to_close || []).join(", ");
  $("#wo-steps").value = (wo.steps || []).join("\n"); $("#wo-safety").value = wo.safety; $("#wo-note").textContent = wo.note;
  const done = wo.status === "approved";
  $$("#incident-body input, #incident-body textarea").forEach((el) => (el.disabled = done));
  $("#approve-wo").disabled = done;
}
async function approveWO() {
  const wo = S.workOrder;
  const edits = { type: $("#wo-type").value, priority: $("#wo-priority").value, crew: $("#wo-crew").value, parts: $("#wo-parts").value,
    valves_to_close: $("#wo-valves").value.split(",").map((s) => s.trim()).filter(Boolean), steps: $("#wo-steps").value.split("\n").filter(Boolean), safety: $("#wo-safety").value };
  const changed = Object.fromEntries(Object.entries(edits).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(wo[k])));
  try {
    await api(`/api/work-orders/${wo.id}/approve`, { approver: $("#wo-approver").value, edits: Object.keys(changed).length ? changed : null });
    $("#wo-msg").textContent = "Approved and logged. Nothing has been dispatched automatically.";
    renderIncident();
  } catch (e) { $("#wo-msg").textContent = e.message; }
}

// ---------------------------------------------------------------- emergency plan
let planTimer = null;
function planInputs() {
  return {
    start: $("#p-start").value,
    forecast_max_f: $("#p-use-forecast").checked ? null : Number($("#p-temp").value),
    extra_outage_tons: Number($("#p-outage").value),
    budget_usd_per_day: $("#p-budget").value ? Number($("#p-budget").value) : null,
    solver: $("#p-solver").value,
    incident_id: S.incidentId,
  };
}
function schedulePlan() { clearTimeout(planTimer); planTimer = setTimeout(solvePlan, 250); }
async function solvePlan() {
  $("#p-temp-label").textContent = $("#p-use-forecast").checked ? "real forecast" : $("#p-temp").value + " °F";
  $("#p-temp").disabled = $("#p-use-forecast").checked;
  $("#p-outage-label").textContent = fmt($("#p-outage").value) + " tons";
  $("#p-solve-info").textContent = "Solving…";
  try { S.plan = await api("/api/plan", planInputs()); S.savedPlan = null; renderPlan(); }
  catch (e) { $("#p-solve-info").textContent = e.message; }
}
function renderPlan() {
  const p = S.plan;
  $("#p-solve-info").textContent = `Solved by ${p.solver} in ${fmt(p.solve_ms)} ms. Plant water that can reach east campus: ${fmt(p.plant_capacity_tons)} tons.`;
  $("#k-cost").textContent = money(p.cost_usd_per_day);
  $("#k-diesel").textContent = fmt(p.diesel_gal_per_day) + " gal";
  $("#k-co2").textContent = fmt(p.co2_t_per_day, 1) + " t";
  $("#k-units").textContent = `${p.rented_units} (${fmt(p.rented_tons)} t)`;
  $("#k-open").textContent = `${p.kept_open} / ${p.kept_open + p.closed}`;
  const [lo, hi] = p.uw_actual_usd_per_day, max = Math.max(hi * 1.15, p.cost_usd_per_day * 1.1);
  $("#compare").innerHTML = `Compared with UW's estimated cost in 2026 (${money(lo)}–${money(hi)} per day, from a model of rental prices):
    <div class="bar"><div class="uw" style="left:${(lo / max) * 100}%;width:${((hi - lo) / max) * 100}%"></div><span style="left:${(p.cost_usd_per_day / max) * 100}%"></span></div>
    <span class="small">Black mark = this plan, grey band = UW 2026 estimate. Simplified model: real costs include more than rentals.</span>`;
  $("#plan-summary").textContent = p.summary;
  const status = Object.fromEntries(p.buildings.map((b) => [b.building_id, b]));
  let extra = "";
  for (const s of p.placements) {
    const [x, y] = proj(s.lat, s.lon);
    extra += `<circle class="site" cx="${x}" cy="${y}" r="${10 + 3 * s.units}"><title>${esc(s.site_id)}: ${esc(s.units)} × ${esc(s.unit_tons)} tons near ${esc(s.near)} · ${money(s.usd_per_day)}/day</title></circle>
      <text class="map-label" x="${x + 14 + 3 * s.units}" y="${y - 6}">${s.units}×${s.unit_tons}t</text>`;
  }
  drawNetwork($("#plan-map"), {
    pipeLabel: (pp) => (pp.pipe_id === "CW-M01" ? "Closed" : "Normal"),
    buildingLabel: (b) => { const r = status[b.building_id]; if (!r) return "Normal"; return r.status === "closed" ? "Act" : r.served_pct < 100 ? "Watch" : "Normal"; },
    extra,
  });
  $("#plan-table tbody").innerHTML = p.buildings
    .slice().sort((a, b) => (a.status === b.status ? b.weight - a.weight : a.status === "closed" ? -1 : 1))
    .map((b) => `<tr><td>${esc(b.name)}</td><td>${esc(b.use)}</td><td class="num">${fmt(b.need_tons)} t</td><td class="num">${fmt(b.plant_tons)} t</td><td class="num">${fmt(b.rental_tons)} t</td><td class="num">${b.served_pct}%</td>
      <td><span class="tag ${b.status === "closed" ? "Act" : b.served_pct < 100 ? "Watch" : "Normal"}">${b.status}</span>${b.peak_indoor_f ? `<br><span class="muted small">peak ${fmt(b.peak_indoor_f, 1)} °F / limit ${fmt(b.max_indoor_f)} °F</span>` : ""}</td><td class="small">${esc(b.why)}</td></tr>`).join("");
}
async function approvePlan() {
  try {
    if (!S.savedPlan) S.savedPlan = await api("/api/plan", { ...planInputs(), save: true });
    const r = await api(`/api/plans/${S.savedPlan.id}/approve`, { approvers: { "FP&M director": $("#ap-director").value, "VC for Finance": $("#ap-finance").value } });
    if (r.missing.length) { $("#plan-msg").textContent = "Still needs: " + r.missing.join(", "); return; }
    $("#plan-msg").textContent = `Plan ${r.plan.id} approved by ${Object.values(r.plan.approvals).map((a) => a.name).join(" and ")}. Nothing has been rented automatically.`;
    S.alert = r.alert; renderAlert();
  } catch (e) { $("#plan-msg").textContent = e.message; }
}
function renderAlert() {
  const a = S.alert; if (!a) return;
  $("#alert-card").hidden = false;
  $("#alert-status").textContent = a.status + (a.approved_by ? ` by ${a.approved_by}` : "");
  $("#alert-subject").value = a.subject; $("#alert-body").value = a.body;
}
async function approveAlert() {
  try { S.alert = await api(`/api/alerts/${S.alert.id}/approve`, { approver: $("#alert-approver").value, body: $("#alert-body").value }); renderAlert(); }
  catch (e) { alert(e.message); }
}

// ---------------------------------------------------------------- repairs + sources
let repairTimer = null;
async function loadRepairs() {
  const b = Number($("#r-budget").value) * 1e6;
  $("#r-budget-label").textContent = "$" + $("#r-budget").value + "M";
  const r = await api("/api/repairs?budget_usd=" + b);
  $("#r-table tbody").innerHTML = r.ranking.slice(0, 25).map((x) => `<tr><td><b>${esc(x.pipe_id)}</b> <span class="muted small">${esc(x.role)}</span></td><td class="num">${esc(x.diameter_in)}-in</td><td class="num">${esc(x.install_year)}</td>
    <td><span class="tag ${esc(x.risk_label)}">${esc(x.risk_label)}</span> <span class="muted small">${Math.round(x.risk * 100)}% in 10 yrs</span></td><td class="num">${money(x.expected_loss_usd)}</td><td class="num">${money(x.replacement_cost_usd)}</td><td>${x.selected ? "✓" : ""}</td></tr>`).join("");
  $("#r-request").textContent = r.request;
}
async function loadSources() {
  const [s, a] = await Promise.all([api("/api/sources"), api("/api/audit")]);
  $("#src-list").innerHTML = s.sources.map((x) => `<li><a href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener">${esc(x.title || x.url)}</a> <span class="muted">${esc(x.publisher)} · ${esc(x.date)}</span><br><span class="muted small">${esc(x.what_it_supports)}</span></li>`).join("");
  $("#audit-table tbody").innerHTML = a.audit.map((x) => `<tr><td class="small">${esc(x.at)}</td><td>${esc(x.actor)}</td><td>${esc(x.action)}</td><td>${esc(x.object_id)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Nothing yet.</td></tr>`;
}

// ---------------------------------------------------------------- boot
async function boot() {
  [S.meta, S.net] = await Promise.all([api("/api/meta"), api("/api/network")]);
  $("#sim-label").textContent = S.meta.label;
  proj = makeProjection([...S.net.nodes, ...S.net.sites]);
  const start = new Date(S.meta.replay_start.replace(" ", "T")), end = new Date(S.meta.replay_end.replace(" ", "T"));
  for (let t = new Date(start.getTime() + 24 * 3600e3); t <= end; t = new Date(t.getTime() + 3600e3)) {
    const p = (n) => String(n).padStart(2, "0");
    S.hours.push(`${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())} ${p(t.getHours())}:00`);
  }
  $("#slider").max = S.hours.length - 1;
  $("#slider").addEventListener("input", (e) => setIdx(Number(e.target.value)));
  $("#play").addEventListener("click", play);
  $$("[data-jump]").forEach((b) => b.addEventListener("click", () => setIdx(S.hours.indexOf(b.dataset.jump))));
  $("#open-incident").addEventListener("click", openIncident);
  $("#ask-form").addEventListener("submit", ask);
  $("#approve-wo").addEventListener("click", approveWO);
  $("#to-plan").addEventListener("click", () => show("plan"));
  ["#p-start", "#p-use-forecast", "#p-temp", "#p-outage", "#p-budget", "#p-solver"].forEach((s) => $(s).addEventListener("input", schedulePlan));
  $("#approve-plan").addEventListener("click", approvePlan);
  $("#approve-alert").addEventListener("click", approveAlert);
  $("#r-budget").addEventListener("input", () => { clearTimeout(repairTimer); repairTimer = setTimeout(loadRepairs, 200); });
  $("#reset").addEventListener("click", async () => { if (confirm("Clear all incidents, plans, alerts and the audit log?")) { await api("/api/reset", {}); S.incidentId = null; S.alert = null; $("#alert-card").hidden = true; loadSources(); loadState(); } });
  wireTooltip();
  // Deep links for demos: /?t=2026-06-09%2008:00&screen=plan
  const q = new URLSearchParams(location.search);
  const i = S.hours.indexOf(q.get("t") || "2026-06-05 12:00");
  setIdx(i >= 0 ? i : 0);
  if (q.get("screen")) show(q.get("screen"));
}
boot().catch((e) => { document.body.insertAdjacentHTML("afterbegin", `<p style="padding:20px;color:var(--act)">Could not load: ${esc(e.message)}</p>`); });
