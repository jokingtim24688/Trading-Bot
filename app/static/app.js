const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const state = { settings: null, symbol: null, mode: "paper", tab: "dash", chart: null, series: null, lastBid: null, digits: 2, equityShown: false };

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.error || data.detail || res.statusText), { status: res.status });
  return data;
}
function toast(msg, err = false) {
  const t = $("#toast"); t.textContent = msg; t.classList.toggle("err", err); t.classList.add("show");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 4200);
}
const fmt = (n, d = 2) => n == null || isNaN(n) ? "—" : Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

/* ---------- tabs ---------- */
function showTab(name) {
  state.tab = name;
  $$(".rail-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach(t => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "dash" && state.chart) state.chart.timeScale().scrollToRealTime();
  if (name === "chat") { loadHistory(); loadFacts(); }
  if (name === "agent") { pollAgentLog(); loadJournal(); }
  if (name === "train") pollTrainLog();
}
$$(".rail-btn").forEach(b => b.onclick = () => showTab(b.dataset.tab));
document.addEventListener("click", e => { const g = e.target.closest("[data-goto]"); if (g) showTab(g.dataset.goto); });

/* ---------- status strip ---------- */
function countUp(el, to, digits = 2) {
  const t0 = performance.now(), dur = 900;
  const step = now => { const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(to * e, digits); if (p < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
async function pollStatus() {
  try {
    const s = await api("/api/status");
    if (!state.settings) { state.settings = s.settings; initFromSettings(); }
    state.settings = { ...state.settings, ...s.settings };
    const r = s.resources || {};
    if (r.ram_total_gb) { $("#ram-bar").style.width = `${(r.ram_used_gb / r.ram_total_gb) * 100}%`; $("#ram-txt").textContent = `${r.ram_used_gb}/${r.ram_total_gb} GB · app ${r.app_ram_mb} MB`; }
    if (r.vram_total_gb) { $("#vram-bar").style.width = `${(r.vram_used_gb / r.vram_total_gb) * 100}%`; $("#vram-txt").textContent = `${r.vram_used_gb}/${r.vram_total_gb} GB`; }
    else $("#vram-txt").textContent = "n/a";
    const a = s.jobs.agent, pill = $("#agent-pill");
    pill.textContent = a.running ? `agent running · ${a.args.includes("--live") ? (a.args.includes("--allow-real") ? "REAL" : "demo") : "paper"}` : "agent idle";
    pill.className = "pill" + (a.running ? " live" : "");
    $("#agent-state").textContent = a.running ? "running" : (a.exit_code != null ? `stopped (exit ${a.exit_code})` : "not started");
    $("#step-fetch").classList.toggle("done", s.data_ready);
    $("#step-train").classList.toggle("done", s.model_ready);
    const tr = s.jobs.train, fe = s.jobs.fetch;
    $("#train-state").textContent = tr.running ? "training…" : fe.running ? "downloading…" : "";
    $("#btn-train").disabled = tr.running; $("#btn-fetch").disabled = fe.running;
  } catch (e) { /* server restarting */ }
}
async function pollAccount() {
  try {
    const a = await api("/api/account");
    const badge = $("#acct-mode");
    badge.textContent = a.demo ? "demo" : "real"; badge.className = "badge " + (a.demo ? "demo" : "real");
    if (!state.equityShown) { countUp($("#equity"), a.equity); state.equityShown = true; }
    else $("#equity").textContent = fmt(a.equity);
    const f = $("#floating"); f.textContent = (a.profit >= 0 ? "+" : "") + fmt(a.profit); f.style.color = a.profit > 0 ? "var(--up)" : a.profit < 0 ? "var(--down)" : "";
    $("#free-margin").textContent = fmt(a.margin_free);
    if (!a.algo_trading) $("#agent-pill").classList.add("warn");
  } catch (e) {
    $("#acct-mode").textContent = "MT5 offline"; $("#acct-mode").className = "badge";
    $("#equity").textContent = "—";
  }
}

/* ---------- chart ---------- */
function initChart() {
  if (!window.LightweightCharts) { $("#chart-msg").textContent = "Chart library didn't load. Check the internet connection."; $("#chart-msg").classList.remove("hidden"); return; }
  const el = $("#chart");
  state.chart = LightweightCharts.createChart(el, {
    layout: { background: { color: "transparent" }, textColor: "#8c9098", fontFamily: "IBM Plex Mono, monospace", fontSize: 11 },
    grid: { vertLines: { color: "rgba(255,255,255,.035)" }, horzLines: { color: "rgba(255,255,255,.035)" } },
    rightPriceScale: { borderColor: "#262c34" }, timeScale: { borderColor: "#262c34", timeVisible: true, secondsVisible: false, rightOffset: 6 },
    crosshair: { mode: 0 }, autoSize: true, localization: { locale: "en-US" },
  });
  state.series = state.chart.addCandlestickSeries({ upColor: "#3fb68b", downColor: "#e0574f", borderVisible: false, wickUpColor: "#3fb68b", wickDownColor: "#e0574f" });
}
async function loadBars() {
  if (!state.series || !state.symbol) return;
  try {
    const d = await api(`/api/bars?symbol=${encodeURIComponent(state.symbol)}&count=300`);
    state.digits = d.digits; state.lastBid = d.bid;
    state.series.applyOptions({ priceFormat: { type: "price", precision: d.digits, minMove: d.point } });
    state.series.setData(d.bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
    $("#q-sym").textContent = d.symbol; $("#q-bid").textContent = fmt(d.bid, d.digits);
    $("#q-spr").textContent = Math.round((d.ask - d.bid) / d.point);
    $("#chart-msg").classList.add("hidden");
    if (!$("#sz-entry").value) $("#sz-entry").placeholder = fmt(d.bid, d.digits).replace(/,/g, "");
  } catch (e) {
    const m = $("#chart-msg"); m.textContent = e.message; m.classList.remove("hidden");
  }
}
function renderChips() {
  const box = $("#symbols"); box.innerHTML = "";
  (state.settings.symbols_watch || []).forEach(sym => {
    const b = document.createElement("button"); b.className = "chip" + (sym === state.symbol ? " active" : ""); b.textContent = sym;
    b.onclick = () => { state.symbol = sym; renderChips(); state.series && state.series.setData([]); loadBars(); sizeTrade(); };
    box.appendChild(b);
  });
}

/* ---------- sizing ---------- */
let szTimer;
function sizeTrade() {
  clearTimeout(szTimer);
  szTimer = setTimeout(async () => {
    const entry = parseFloat($("#sz-entry").value || $("#sz-entry").placeholder), stop = parseFloat($("#sz-stop").value), risk = $("#sz-risk").value;
    $("#sz-risk-txt").textContent = `${risk}%`;
    if (!entry || !stop || entry === stop) { $("#sz-lots").textContent = "—"; $("#sz-detail").textContent = "enter a stop price"; return; }
    try {
      const r = await api(`/api/size?symbol=${encodeURIComponent(state.symbol)}&entry=${entry}&stop=${stop}&risk=${risk}`);
      $("#sz-lots").textContent = r.lots ? r.lots : "0";
      $("#sz-detail").textContent = r.lots ? `risks ${fmt(r.risk_money)} of ${fmt(r.equity)}` : `min lot would risk more than ${risk}%, so skip or widen risk`;
    } catch (e) { $("#sz-detail").textContent = e.message; }
  }, 250);
}
["#sz-entry", "#sz-stop", "#sz-risk"].forEach(s => $(s).addEventListener("input", sizeTrade));

/* ---------- positions ---------- */
async function loadPositions() {
  try {
    const ps = await api("/api/positions"), box = $("#positions");
    $("#pos-count").textContent = ps.length ? `${ps.length} open` : "";
    if (!ps.length) { box.innerHTML = `<p class="empty">Nothing open. Positions from the agent, Hermes or manual trades in MT5 show up here.</p>`; return; }
    box.innerHTML = ps.map(p => `<div class="pos ${p.side}">
      <span><strong>${p.symbol}</strong> <span class="muted">${p.side} ${p.volume}</span></span>
      <button class="btn xs" data-close="${p.ticket}">Close</button>
      <span class="num small muted">SL ${p.sl || "none"}  TP ${p.tp || "none"}</span>
      <span class="num small"><span class="pl ${p.profit >= 0 ? "up" : "down"}">${p.profit >= 0 ? "+" : ""}${fmt(p.profit)}</span> <span class="muted">from ${p.open}</span></span></div>`).join("");
  } catch (e) { /* offline handled by account badge */ }
}
$("#positions").addEventListener("click", async e => {
  const t = e.target.closest("[data-close]"); if (!t) return;
  t.disabled = true;
  try { const r = await api(`/api/positions/${t.dataset.close}/close`, { method: "POST" }); toast(r.retcode === 10009 ? "Position closed" : `Close result: ${r.comment}`); }
  catch (err) { toast(err.message, true); }
  loadPositions();
});

/* ---------- kill switch (hold 1.2s) ---------- */
(() => {
  const k = $("#kill"); let h;
  const cancel = () => { clearTimeout(h); k.classList.remove("holding"); };
  k.addEventListener("pointerdown", () => {
    k.classList.add("holding");
    h = setTimeout(async () => {
      k.querySelector(".kill-label").textContent = "Flattening…";
      try { const r = await api("/api/kill", { method: "POST" }); toast(`Agent stopped · ${r.closed.length} position(s) closed`); }
      catch (e) { toast(e.message, true); }
      k.querySelector(".kill-label").textContent = "Hold to flatten agent"; cancel(); loadPositions();
    }, 1200);
  });
  ["pointerup", "pointerleave"].forEach(ev => k.addEventListener(ev, cancel));
})();

/* ---------- agent ---------- */
$$(".seg-btn").forEach(b => b.onclick = () => { if (b.disabled) return; state.mode = b.dataset.mode; $$(".seg-btn").forEach(x => x.classList.toggle("active", x === b)); });
function bindSlider(id, key, suffix, digits) {
  const el = $(id), txt = $(`${id}-txt`);
  el.value = state.settings[key]; txt.textContent = `${Number(el.value).toFixed(digits)}${suffix}`;
  el.oninput = () => txt.textContent = `${Number(el.value).toFixed(digits)}${suffix}`;
  el.onchange = () => api("/api/settings", { method: "POST", body: { [key]: parseFloat(el.value) } });
}
$("#agent-start").onclick = async () => {
  const msg = $("#agent-msg"); msg.className = "note";
  if (state.mode === "real" && !confirm("Start the agent on a REAL-money account? It will place real orders.")) return;
  try { await api("/api/agent/start", { method: "POST", body: { mode: state.mode } }); msg.textContent = `Started in ${state.mode} mode. It acts when the next M1 candle closes.`; pollStatus(); pollAgentLog(); }
  catch (e) { msg.textContent = e.message; msg.className = "note err"; }
};
$("#agent-stop").onclick = async () => { await api("/api/agent/stop", { method: "POST" }); $("#agent-msg").textContent = "Stopped. Any open position keeps its server-side stop loss and take profit."; pollStatus(); };
async function pollAgentLog() {
  try { const r = await api("/api/jobs/agent/log?lines=300"); if (r.log) { const c = $("#agent-log"); const stick = c.scrollTop + c.clientHeight >= c.scrollHeight - 20; c.textContent = r.log; if (stick) c.scrollTop = c.scrollHeight; } } catch (e) {}
}
async function loadJournal() {
  try {
    const rows = await api("/api/journal?limit=200");
    $("#journal tbody").innerHTML = rows.reverse().map(r => `<tr><td>${(r.time_utc || "").replace("T", " ").slice(0, 19)}</td><td>${r.mode}</td>
      <td class="ev-${r.event}">${r.event}</td><td>${r.side || ""}</td><td>${r.lots || ""}</td><td>${r.price ? Number(r.price).toFixed(state.digits) : ""}</td>
      <td>${r.sl ? Number(r.sl).toFixed(state.digits) : ""}</td><td>${r.tp ? Number(r.tp).toFixed(state.digits) : ""}</td><td>${r.prob || ""}</td><td>${r.note || ""}</td></tr>`).join("")
      || `<tr><td colspan="10" class="muted">No entries yet. Start the agent in Paper mode and signals will be logged as candles close.</td></tr>`;
  } catch (e) {}
}

/* ---------- train ---------- */
let lastTrainJob = "train";
$("#btn-fetch").onclick = async () => { try { await api("/api/fetch", { method: "POST" }); lastTrainJob = "fetch"; pollTrainLog(); pollStatus(); } catch (e) { toast(e.message, true); } };
$("#btn-train").onclick = async () => { try { await api("/api/train", { method: "POST" }); lastTrainJob = "train"; pollTrainLog(); pollStatus(); } catch (e) { toast(e.message, true); } };
async function pollTrainLog() {
  try { const r = await api(`/api/jobs/${lastTrainJob}/log?lines=400`); if (r.log) { const c = $("#train-log"); c.textContent = r.log; c.scrollTop = c.scrollHeight; } } catch (e) {}
}

/* ---------- Hermes chat ---------- */
function addMsg(role, text, tools) {
  const d = document.createElement("div"); d.className = `msg ${role}`; d.textContent = text;
  if (tools && tools.length) { const t = document.createElement("div"); t.className = "tools"; t.textContent = "used: " + tools.map(x => x.tool).join(", "); d.appendChild(t); }
  $("#thread").appendChild(d); $("#thread").scrollTop = $("#thread").scrollHeight; return d;
}
async function loadHistory() {
  try {
    const h = await api("/api/chat/history?n=60"); $("#thread").innerHTML = "";
    h.forEach(m => addMsg(m.role, m.content));
    $("#suggest").classList.toggle("hidden", h.length > 0);
    $("#chat-intro").classList.toggle("hidden", h.length > 0);
  } catch (e) {}
}
async function send(text) {
  text = text.trim(); if (!text) return;
  $("#suggest").classList.add("hidden"); $("#chat-intro").classList.add("hidden"); addMsg("user", text);
  const pending = addMsg("assistant pending", "Thinking");
  try { const r = await api("/api/chat", { method: "POST", body: { text } }); pending.remove(); addMsg("assistant", r.reply, r.tools); loadFacts(); }
  catch (e) { pending.remove(); addMsg("assistant", `Couldn't reach the assistant: ${e.message}`); }
}
$("#chat-form").onsubmit = e => { e.preventDefault(); const i = $("#chat-input"); const t = i.value; i.value = ""; i.style.height = ""; send(t); };
$("#chat-input").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chat-form").requestSubmit(); } });
$("#chat-input").addEventListener("input", e => { e.target.style.height = "auto"; e.target.style.height = e.target.scrollHeight + "px"; });
$$("#suggest button").forEach(b => b.onclick = () => send(b.textContent));
async function brainStatus() {
  try {
    const s = await api("/api/assistant/status"), el = $("#brain-state");
    const useAgent = s.backend_setting === "hermes_agent" || (s.backend_setting === "auto" && s.hermes_agent);
    if (useAgent && s.hermes_agent) { el.textContent = "Hermes Agent · connected"; el.className = "pill live"; }
    else if (!useAgent && s.ollama) { el.textContent = `${s.model} on RTX 4060`; el.className = "pill live"; }
    else { el.textContent = useAgent ? "Hermes Agent not running" : "Ollama not running"; el.className = "pill warn"; }
  } catch (e) {}
}
async function loadFacts() {
  try {
    const f = await api("/api/memory");
    $("#fact-count").textContent = f.length ? `${f.length} saved` : "";
    $("#facts").innerHTML = f.map(x => `<li><span>${x.text.replace(/</g, "&lt;")}</span><button title="Forget" data-forget="${x.id}">×</button></li>`).join("")
      || `<li class="muted">Nothing yet. Try "Remember my broker is on GMT+3" or "Remember I only trade the London–New York overlap".</li>`;
  } catch (e) {}
}
$("#facts").addEventListener("click", async e => { const b = e.target.closest("[data-forget]"); if (!b) return; await api(`/api/memory/${b.dataset.forget}`, { method: "DELETE" }); loadFacts(); });
$("#fact-form").onsubmit = async e => { e.preventDefault(); const i = $("#fact-input"); if (!i.value.trim()) return; await api("/api/memory", { method: "POST", body: { text: i.value } }); i.value = ""; loadFacts(); };

/* ---------- settings ---------- */
function fillSettings() {
  const f = $("#settings-form"), s = state.settings;
  for (const el of f.elements) {
    if (!el.name || !(el.name in s)) continue;
    if (el.type === "checkbox") el.checked = !!s[el.name];
    else el.value = Array.isArray(s[el.name]) ? s[el.name].join(", ") : s[el.name];
  }
}
$("#settings-form").onsubmit = async e => {
  e.preventDefault();
  const body = {};
  for (const el of e.target.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") body[el.name] = el.checked;
    else if (el.name === "symbols_watch") body[el.name] = el.value.split(",").map(x => x.trim()).filter(Boolean);
    else if (el.type === "number") body[el.name] = parseFloat(el.value);
    else body[el.name] = el.value.trim();
  }
  try { state.settings = await api("/api/settings", { method: "POST", body }); $("#settings-msg").textContent = "Saved to data/settings.json"; initFromSettings(true); brainStatus(); }
  catch (err) { $("#settings-msg").textContent = err.message; }
};
$("#unlock-real").onchange = e => { const b = $('.seg-btn[data-mode="real"]'); b.disabled = !e.target.checked; b.querySelector("small").textContent = e.target.checked ? "real money" : "locked"; };

function initFromSettings(keepSymbol = false) {
  const s = state.settings;
  if (!keepSymbol || !(s.symbols_watch || []).includes(state.symbol)) state.symbol = s.symbols_watch?.[0] || s.symbol;
  renderChips(); fillSettings();
  bindSlider("#thr", "threshold", "", 2); bindSlider("#risk", "risk_pct", "%", 1);
  $$(".sym-txt").forEach(x => x.textContent = s.symbol); $("#days-txt").textContent = s.days_history;
  loadBars();
}

/* ---------- boot ---------- */
initChart();
pollStatus().then(() => { pollAccount(); loadPositions(); brainStatus(); });
setInterval(pollStatus, 2000);
setInterval(pollAccount, 2000);
setInterval(() => state.tab === "dash" && (loadBars(), loadPositions()), 3000);
setInterval(() => state.tab === "agent" && (pollAgentLog(), loadJournal()), 2000);
setInterval(() => state.tab === "train" && pollTrainLog(), 1500);
setInterval(brainStatus, 15000);
