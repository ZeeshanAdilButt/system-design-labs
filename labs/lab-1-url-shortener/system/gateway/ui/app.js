"use strict";

const REPLICAS = ["api-1", "api-2", "api-3"];
const STALE_MS = 6000; // a replica not heard from for this long is shown as down

const $ = (sel) => document.querySelector(sel);
const STARTED = Date.now();
const lastSeen = {}; // replica -> time of its last answer
let backlogHistory = [];
let links = [];
let health = { store: null, cache: null };
let online = false;

async function call(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    ...options,
  });
  let body = null;
  try { body = await res.json(); } catch { /* not JSON */ }
  return { ok: res.ok, status: res.status, body };
}

function errorText(res) {
  const detail = res.body && res.body.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]) return detail[0].msg.replace(/^Value error, /, "");
  return `Something went wrong (${res.status})`;
}

/* ---------- making a link ---------- */

$("#form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  const error = $("#form-error");
  error.textContent = "";
  button.disabled = true;
  try {
    const payload = { url: $("#url").value.trim() };
    const alias = $("#alias").value.trim();
    if (alias) payload.alias = alias;
    const res = await call("/api/links", { method: "POST", body: JSON.stringify(payload) });
    if (!res.ok) { error.textContent = errorText(res); return; }
    showResult(res.body);
    $("#url").value = "";
    $("#alias").value = "";
    await refreshLinks();
    $("#target").value = res.body.code;
  } catch {
    error.textContent = "Could not reach the service.";
  } finally {
    button.disabled = false;
  }
});

function shortUrl(code) { return `${location.origin}/${code}`; }

function showResult(link) {
  $("#result").hidden = false;
  const a = $("#result-link");
  a.href = shortUrl(link.code);
  a.textContent = shortUrl(link.code);
  $("#copy").textContent = "Copy";
}

$("#copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("#result-link").textContent);
    $("#copy").textContent = "Copied";
  } catch {
    $("#copy").textContent = "Press Ctrl+C";
  }
});

/* ---------- visiting a link ---------- */

const trace = [];
const TAG_TEXT = { hit: "HIT", miss: "MISS", bypass: "NO CACHE" };

async function visit(code) {
  const started = performance.now();
  let res;
  try {
    res = await fetch(`/${code}`, { headers: { Accept: "application/json" } });
  } catch {
    addTrace({ code, error: "no answer" });
    return null;
  }
  const roundTrip = performance.now() - started;
  let body = null;
  try { body = await res.json(); } catch { /* ignore */ }
  const entry = {
    code,
    status: res.status,
    cache: (res.headers.get("X-Cache") || "").toLowerCase(),
    replica: res.headers.get("X-Served-By") || (body && body.served_by) || "?",
    ms: roundTrip,
    error: res.ok ? null : (body && body.error) || `error ${res.status}`,
  };
  if (entry.replica !== "?") lastSeen[entry.replica] = Date.now();
  addTrace(entry);
  return entry;
}

function addTrace(entry) {
  trace.unshift(entry);
  trace.length = Math.min(trace.length, 4);
  const box = $("#trace");
  box.classList.remove("muted");
  box.innerHTML = trace.map((t) => {
    if (t.error && !t.replica) return `<div class="tr"><span class="tag tag-err">ERR</span><span>/${t.code}: ${t.error}</span></div>`;
    const tag = t.error ? `<span class="tag tag-err">${t.status}</span>`
      : `<span class="tag tag-${t.cache}">${TAG_TEXT[t.cache] || t.cache.toUpperCase()}</span>`;
    const note = t.error ? t.error : t.cache === "hit" ? "from the cache" : t.cache === "miss" ? "from the database" : "Redis is down, so from the database";
    return `<div class="tr">${tag}<span>/${t.code} by <b>${t.replica}</b>, ${t.ms.toFixed(1)} ms, ${note}</span></div>`;
  }).join("");
  light(trace[0]);
}

let lightTimer = 0;
function light(entry) {
  clearLit();
  if (!entry || !entry.replica || entry.replica === "?") return;
  const id = entry.replica;
  const path = (edge, cls) => { const el = document.getElementById(edge); if (el) el.classList.add(cls); };
  path("e-browser-gateway", "lit");
  path(`e-gateway-${id}`, "lit");
  const kind = entry.error ? "miss" : entry.cache === "hit" ? "hit" : "miss";
  if (entry.cache !== "bypass") path(`e-${id}-redis`, `lit-${kind}`);
  if (kind === "miss" || entry.cache === "bypass") path(`e-${id}-postgres`, "lit-miss");
  const node = document.getElementById(`n-${id}`);
  if (node) node.classList.add("flash");
  clearTimeout(lightTimer);
  lightTimer = setTimeout(clearLit, 1200);
}

function clearLit() {
  document.querySelectorAll(".edges path").forEach((p) => p.classList.remove("lit", "lit-hit", "lit-miss"));
  document.querySelectorAll(".node.flash").forEach((n) => n.classList.remove("flash"));
}

/* ---------- sending traffic ---------- */

document.querySelectorAll("[data-burst]").forEach((button) => {
  button.addEventListener("click", async () => {
    const code = $("#target").value;
    if (!code) return;
    const total = Number(button.dataset.burst);
    const buttons = document.querySelectorAll("[data-burst]");
    buttons.forEach((b) => (b.disabled = true));
    let sent = 0;
    const lanes = Math.min(total, 12);
    await Promise.all(Array.from({ length: lanes }, async () => {
      while (sent < total) { sent += 1; await visit(code); }
    }));
    buttons.forEach((b) => (b.disabled = false));
    refreshStats();
    setTimeout(refreshLinks, 1500);
  });
});

$("#reset").addEventListener("click", async () => {
  await call("/api/stats", { method: "DELETE" });
  refreshStats();
});

/* ---------- links list ---------- */

async function refreshLinks() {
  const res = await call("/api/links?limit=8").catch(() => null);
  if (!res || !res.ok) return;
  links = res.body;
  const select = $("#target");
  const previous = select.value;
  select.innerHTML = links.map((l) => `<option value="${l.code}">/${l.code}</option>`).join("");
  if (links.some((l) => l.code === previous)) select.value = previous;
  $("#links-empty").hidden = links.length > 0;
  $("#links").innerHTML = links.map((l) => `
    <div class="link">
      <div style="min-width:0">
        <div class="link-code">/${l.code}</div>
        <div class="link-url" title="${escapeHtml(l.url)}">${escapeHtml(l.url)}</div>
      </div>
      <div class="link-clicks">${l.clicks.toLocaleString()}<small>clicks</small></div>
      <button class="ghost" data-visit="${l.code}">Visit</button>
    </div>`).join("");
}

$("#links").addEventListener("click", async (event) => {
  const code = event.target.dataset && event.target.dataset.visit;
  if (!code) return;
  $("#target").value = code;
  await visit(code);
  refreshStats();
  setTimeout(refreshLinks, 1500);
});

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------- live status ---------- */

let gatewayError = 0; // the HTTP status when the gateway answered but no replica did

async function pollHealth() {
  try {
    const res = await fetch("/api/health", { headers: { Accept: "application/json" } });
    online = true; // something answered, so the gateway is up
    let body = null;
    try { body = await res.json(); } catch { /* an error page from the gateway, not JSON */ }
    if (body && body.replica) {
      gatewayError = 0;
      health = { store: body.store, cache: body.cache };
      lastSeen[body.replica] = Date.now();
    } else {
      gatewayError = res.status; // keep what we knew about Redis and Postgres
    }
  } catch {
    online = false;
    health = { store: null, cache: null };
  }
  renderStatus();
}

async function refreshStats() {
  const res = await call("/api/stats").catch(() => null);
  if (!res || !res.ok) return;
  const s = res.body;
  $("#st-redirects").textContent = s.redirects.toLocaleString();
  $("#st-ratio").textContent = s.hit_ratio === null ? "n/a" : `${Math.round(s.hit_ratio * 100)}%`;
  const backlog = s.click_backlog;
  $("#st-backlog").textContent = backlog === null ? "?" : backlog.toLocaleString();

  backlogHistory.push(backlog);
  backlogHistory = backlogHistory.slice(-4);
  const growing = backlogHistory.length >= 3 && backlogHistory.every((v, i, a) => i === 0 || (v !== null && v >= a[i - 1])) && backlog > 20;
  setNode("worker", backlog === null ? "down" : growing ? "warn" : "up");
  $("#s-worker").textContent = growing ? "falling behind" : "counts clicks";

  const total = Object.values(s.by_replica).reduce((a, b) => a + b, 0);
  $("#share").innerHTML = REPLICAS.map((name) => {
    const n = s.by_replica[name] || 0;
    const pct = total ? (n / total) * 100 : 0;
    return `<div class="bar"><span>${name}</span><div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div><span class="bar-n">${n.toLocaleString()}</span></div>`;
  }).join("");
}

function setNode(id, state) {
  const node = document.getElementById(`n-${id}`);
  if (!node) return;
  node.classList.remove("up", "warn", "down");
  node.classList.add(state);
}

function renderStatus() {
  const now = Date.now();
  let alive = 0;
  for (const name of REPLICAS) {
    const fresh = lastSeen[name] && now - lastSeen[name] < STALE_MS;
    if (fresh) alive += 1;
    const gaveUp = lastSeen[name] || now - STARTED > 8000; // never answered since the page opened
    setNode(name, !online ? "down" : fresh ? "up" : gaveUp ? "down" : "warn");
    $(`#s-${name}`).textContent = !online ? "unreachable" : fresh ? "up" : gaveUp ? "not answering" : "waiting";
  }
  setNode("gateway", online ? "up" : "down");
  setNode("redis", !online ? "down" : health.cache === false ? "down" : "up");
  setNode("postgres", !online ? "down" : health.store === false ? "down" : "up");
  if (!online) setNode("worker", "down");

  const pill = $("#pill");
  pill.className = "pill";
  let text;
  if (!online) { pill.classList.add("pill-bad"); text = "gateway unreachable"; }
  else if (gatewayError) { pill.classList.add("pill-bad"); text = `gateway answered ${gatewayError}: no replica could serve it`; }
  else if (health.store === false) { pill.classList.add("pill-bad"); text = "database down: cached links still redirect"; }
  else if (health.cache === false) { pill.classList.add("pill-warn"); text = "Redis down: links still work, served from the database"; }
  else if (now - STARTED < 4000 && alive < REPLICAS.length) { text = "checking the replicas"; }
  else if (alive < REPLICAS.length) { pill.classList.add("pill-warn"); text = `${alive} of ${REPLICAS.length} replicas answering`; }
  else { pill.classList.add("pill-ok"); text = "all systems up"; }
  $("#pill-text").textContent = text;
}

pollHealth();
refreshLinks();
refreshStats();
setInterval(pollHealth, 1000);
setInterval(refreshStats, 1500);
setInterval(refreshLinks, 4000);
