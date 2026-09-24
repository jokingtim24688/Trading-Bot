const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const state = { settings: null, symbol: null, mode: "paper", tab: "dash", chart: null, series: null, lastBid: null, digits: 2, equityShown: false };

async function api(path, opts = {}) {
  if (opts.method && opts.method !== "GET") posCache.at = 0;       // a close/order/edit: the next positions read is fresh
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.error || data.detail || res.statusText), { status: res.status });
  return data;
}
/* ---------- notifications: one custom stack at the top right. Several show at once, each new one below the others;
   each fades after 1.2 s (Sounds page), hovering keeps it, a click closes it. When the app isn't in front they also pop
   up at the top right of the screen (a small always-on-top window from app/main.py). ---------- */
const NOTE_ICON = {
  info: '<path d="M12 8h.01M11 12h1v5h1"/><circle cx="12" cy="12" r="9"/>',
  ok: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.6 2.6L16 9.7"/>',
  err: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/>',
  tp: '<path d="M4 17l5-5 4 3 7-8"/><path d="M15 7h5v5"/>',
  sl: '<path d="M4 7l5 5 4-3 7 8"/><path d="M15 17h5v-5"/>',
};
const noteSecs = () => { try { const v = parseFloat(localStorage.getItem("noteSecs")); return v > 0 ? v : 1.2; } catch (e) { return 1.2; } };
const appAway = () => document.hidden || !document.hasFocus();
function notify({ title = "", body = "", html = "", kind = "info", amount = null, onClick = null, screen = true } = {}) {
  const box = $("#notes"); if (!box) return;
  const secs = noteSecs(), el = document.createElement("div");
  el.className = `note ${kind}`; el.setAttribute("role", kind === "err" ? "alert" : "status");
  el.innerHTML = `<svg class="note-ic" viewBox="0 0 24 24" aria-hidden="true">${NOTE_ICON[kind] || NOTE_ICON.info}</svg>
    <div class="note-body">${title ? `<b>${esc(title)}</b>` : ""}${html || body ? `<span>${html || esc(body)}</span>` : ""}</div>
    ${amount != null ? `<em class="num ${cls(amount)}">${signed(amount)}</em>` : ""}<i class="note-life" style="animation-duration:${secs}s"></i>`;
  box.append(el);                                // the newest sits below the others
  while (box.querySelectorAll(".note:not(.out)").length > 6) removeNote(box.querySelector(".note:not(.out)"), true);
  let left = secs * 1000, t0 = performance.now(), timer = setTimeout(() => removeNote(el), left);
  el.addEventListener("mouseenter", () => { clearTimeout(timer); left -= performance.now() - t0; el.classList.add("hold"); });
  el.addEventListener("mouseleave", () => { t0 = performance.now(); el.classList.remove("hold"); timer = setTimeout(() => removeNote(el), Math.max(500, left)); });
  el.addEventListener("click", () => { clearTimeout(timer); onClick?.(); removeNote(el); });
  if (screen && appAway() && pref("screenNotes", true))   // not in front: the pop-up at the top right of the screen too
    window.pywebview?.api?.notify?.({ title, body: body || el.querySelector(".note-body span")?.textContent || "", kind, amount: amount == null ? null : signed(amount), secs })?.catch?.(() => {});
}
function removeNote(el, instant = false) {       // fade out, then the ones below glide up into its place
  if (!el || el._gone) return; el._gone = true;
  const box = el.parentNode; if (!box) return;
  let done = false;
  const finish = () => {
    if (done) return; done = true;
    const sibs = [...box.children].filter(x => x !== el), before = new Map(sibs.map(x => [x, x.getBoundingClientRect().top]));
    el.remove();
    if (!motionOK()) return;
    sibs.forEach(x => { const dy = before.get(x) - x.getBoundingClientRect().top; if (dy) x.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration: 280, easing: "cubic-bezier(.22,1,.36,1)" }); });
  };
  if (instant || !motionOK()) return finish();
  el.classList.add("out"); el.addEventListener("animationend", finish, { once: true }); setTimeout(finish, 450);
}
function toast(msg, err = false) { notify({ body: msg, kind: err ? "err" : "info" }); }
/* one positions request shared by the Market and Manual tabs (and the alerts): in flight once, reused for 0.8 s */
const posCache = { req: null, at: 0, data: null };
function getPositions() {
  if (posCache.req) return posCache.req;
  if (posCache.data && performance.now() - posCache.at < 800) return Promise.resolve(posCache.data);
  posCache.req = api("/api/positions").then(d => { posCache.data = d; posCache.at = performance.now(); return d; }).finally(() => { posCache.req = null; });
  return posCache.req;
}
const fmt = (n, d = 2) => n == null || isNaN(n) ? "—" : Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

/* ---------- motion helpers: cheap, skipped when hidden or when motion is reduced ---------- */
const motionOK = () => !document.documentElement.classList.contains("reduce-motion") && !matchMedia("(prefers-reduced-motion: reduce)").matches;
const shown = el => !!el && el.offsetParent !== null && !document.hidden;
// only touch the DOM when the markup really changed (polls repeat every few seconds)
function setHTML(el, html) { if (el._html === html) return false; el._html = html; el.innerHTML = html; return true; }
function flash(el, dir) {                      // brief green/red wash when a number moves
  if (!dir || !el?.animate || !motionOK() || !shown(el)) return;
  const now = performance.now(); if (now - (el._flashAt || 0) < 700) return; el._flashAt = now;
  el.animate([{ backgroundColor: dir > 0 ? "rgba(63,182,139,.32)" : "rgba(224,87,79,.32)" }, { backgroundColor: "rgba(0,0,0,0)" }],
    { duration: 900, easing: "cubic-bezier(.22,1,.36,1)" });
}
function tweenNum(el, from, to, format, dur = 480) {   // numbers glide to their new value
  cancelAnimationFrame(el._tw);
  if (from == null || !isFinite(from) || from === to || !motionOK() || !shown(el)) { el.textContent = format(to); return; }
  const t0 = performance.now();
  const step = now => { const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
    el.textContent = format(from + (to - from) * e); if (p < 1) el._tw = requestAnimationFrame(step); };
  el._tw = requestAnimationFrame(step);
}
function setNum(el, v, format, { flashIt = true } = {}) {
  const prev = el._v; el._v = v;
  if (v == null || isNaN(v)) { cancelAnimationFrame(el._tw); el.textContent = format(v); return; }
  if (prev === v && el._set) return;
  el._set = true; tweenNum(el, prev, v, format);
  if (flashIt && prev != null && prev !== v) flash(el, v > prev ? 1 : -1);
}

/* ---------- tabs ---------- */
function moveRailInd() {                        // slide the highlight to the active section (transform only)
  const rail = $(".rail"), ind = $(".rail-ind"), b = $(".rail-btn.active"); if (!ind || !b) return;
  ind.style.transform = `translate(${b.offsetLeft}px, ${b.offsetTop}px)`;
  ind.style.width = b.offsetWidth + "px"; ind.style.height = b.offsetHeight + "px";
  if (!rail.classList.contains("ind-ready")) requestAnimationFrame(() => rail.classList.add("ind-ready"));
}
$$(".tab").forEach(t => $$(".panel", t).forEach((p, i) => p.style.setProperty("--i", i)));   // stagger order per tab
function showTab(name) {
  // leaving the Hermes tab puts the local model to sleep (frees RAM/VRAM; the next message reloads it)
  if (state.tab === "chat" && name !== "chat") api("/api/assistant/sleep", { method: "POST" }).catch(() => {});
  if (name !== "agent") closeLog();
  if (name === "settings" && state.settings && !$("#savebar").classList.contains("is-dirty")) { fillSettings(); updateDirty(); }
  state.tab = name;
  $$(".rail-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach(t => t.classList.toggle("active", t.id === `tab-${name}`));
  moveRailInd();
  if (name === "dash" && state.chart && state.chartAuto && !state.autoT) realignChart(true);
  if (name === "chat") { loadHistory(); loadFacts(); }
  if (name === "manual") openManual();
  if (name === "review") openReview();
  if (name === "keys") renderKeys();
  if (name === "sounds") openSounds();
  if (name === "agent") { pollAgentLog(); loadJournal(); renderBotTable(); loadPlan(); loadProgress(); loadCalendar(); }
  if (name === "train") pollTrainLog();
  if (name === "quiz") { loadQuiz(); loadReport(false); }
}
$$(".rail-btn").forEach(b => b.onclick = () => showTab(b.dataset.tab));
document.addEventListener("click", e => { const g = e.target.closest("[data-goto]"); if (g) { if (g.tagName === "A") e.preventDefault(); showTab(g.dataset.goto); } });

/* ---------- status strip ---------- */
function countUp(el, to, digits = 2) {
  if (!motionOK()) { el.textContent = fmt(to, digits); return; }
  const t0 = performance.now(), dur = 900;
  const step = now => { const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(to * e, digits); if (p < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
async function pollStatus() {
  try {
    const s = await api("/api/status"); state.status = s;
    if (!state.settings) { state.settings = s.settings; initFromSettings(); }
    state.settings = { ...state.settings, ...s.settings };
    const r = s.resources || {};
    if (r.ram_total_gb) { $("#ram-bar").style.width = `${(r.ram_used_gb / r.ram_total_gb) * 100}%`; $("#ram-txt").textContent = `${r.ram_used_gb}/${r.ram_total_gb} GB · app ${r.app_ram_mb} MB`; }
    if (r.vram_total_gb) { $("#vram-bar").style.width = `${(r.vram_used_gb / r.vram_total_gb) * 100}%`; $("#vram-txt").textContent = `${r.vram_used_gb}/${r.vram_total_gb} GB`; }
    else $("#vram-txt").textContent = "n/a";
    const a = s.jobs.agent, pill = $("#agent-pill");
    const runMode = a.args.includes("--live") ? (a.args.includes("--allow-real") ? "REAL" : "demo") : "paper";
    const inTrades = (state.bot.data?.open || []).filter(t => t.mode === runMode.toLowerCase()).length;
    setHTML(pill, a.running ? `<span class="live-dot"></span>Agent · ${runMode} · ${inTrades ? `in ${inTrades} trade${inTrades > 1 ? "s" : ""}` : "watching"}` : "Agent idle");
    pill.classList.toggle("live", a.running);
    $("#agent-state").textContent = a.running ? "running" : (a.exit_code != null ? `stopped (exit ${a.exit_code})` : "not started");
    $("#step-fetch").classList.toggle("done", s.data_ready);
    $("#step-train").classList.toggle("done", s.model_ready);
    const md = s.model || {};
    $("#thr-hint").textContent = !s.model_ready ? "Train a model first." :
      md.suggested_threshold != null ? `Training suggests ${md.suggested_threshold}. Break-even win rate with these exits: ${md.breakeven_win_pct}%.`
      : md.breakeven_win_pct != null ? `No profitable threshold in testing. Keep it on Paper. Break-even win rate: ${md.breakeven_win_pct}%.` : "";
    const tr = s.jobs.train, fe = s.jobs.fetch;
    $("#train-state").textContent = tr.running ? "training…" : fe.running ? "downloading…" : "";
    $("#btn-train").disabled = tr.running; $("#btn-fetch").disabled = fe.running;
  } catch (e) { /* server restarting */ }
}
async function pollAccount() {
  try {
    const a = await api("/api/account"); state.acct = a; state.acctOk = true;
    const chip = $("#acct-mode");
    chip.className = "acct-chip " + (a.demo ? "demo" : "real");
    $("#acct-kind").textContent = a.demo ? "DEMO" : "REAL";
    $("#acct-server").textContent = `${a.server} · #${a.login}`;
    if (state.tab === "manual") realBanner();
    chip.title = `${a.name || ""} · ${a.server} · leverage 1:${a.leverage} · margin level ${a.margin_level ? Math.round(a.margin_level) + "%" : "–"} · ping ${a.ping_ms} ms`;
    const eq = $("#equity");
    if (!state.equityShown) { countUp(eq, a.equity); Object.assign(eq, { _v: a.equity, _set: true }); state.equityShown = true; }
    else setNum(eq, a.equity, v => fmt(v));
    const f = $("#floating"); setNum(f, a.profit, v => (v >= 0 ? "+" : "") + fmt(v)); f.style.color = a.profit > 0 ? "var(--up)" : a.profit < 0 ? "var(--down)" : "";
    setNum($("#free-margin"), a.margin_free, v => fmt(v), { flashIt: false });
    if (!a.algo_trading) $("#agent-pill").classList.add("warn");
  } catch (e) {
    if (state.acctOk) { state.acctOk = false; feedLost(); }
    $("#acct-mode").className = "acct-chip offline"; $("#acct-kind").textContent = "MT5 offline"; $("#acct-server").textContent = "";
    $("#equity").textContent = "—";
  }
}

/* ---------- sessions clock (broker server time = New York time + 7 h, the hours agent/pro.py uses) ---------- */
const SESSIONS = [["London", 10 * 60, 18 * 60 + 30], ["New York", 16 * 60 + 30, 23 * 60], ["Asia", 60, 9 * 60]];
function serverClock() {
  const ny = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
  const sv = new Date(ny.getTime() + 7 * 3600e3);
  return { day: sv.getDay(), min: sv.getHours() * 60 + sv.getMinutes() };
}
const hm = m => m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`;
function renderSessions() {
  const { day, min } = serverClock(), weekend = day === 6 || day === 0;
  setHTML($("#sessions"), SESSIONS.map(([name, a, b]) => {
    let cls = "", txt;
    if (weekend) txt = "closed (weekend)";
    else if (min >= a && min < b) { cls = "on"; txt = `open · ${hm(b - min)} left`; }
    else if (min < a) { cls = a - min <= 60 ? "soon" : ""; txt = `opens in ${hm(a - min)}`; }
    else txt = day === 5 ? "closed till Monday" : `opens in ${hm(24 * 60 - min + a)}`;
    return `<span class="sess ${cls}"><i></i>${name} <small>${txt}</small></span>`;
  }).join(""));
}
renderSessions(); setInterval(() => !document.hidden && renderSessions(), 20000);

/* PC resources live behind a small button */
$("#sys-btn").onclick = e => { e.stopPropagation(); const p = $("#sys-pop"), open = p.hidden; p.hidden = !open; $("#sys-btn").setAttribute("aria-expanded", String(open)); };
document.addEventListener("click", e => { if (!e.target.closest(".sys-wrap")) { $("#sys-pop").hidden = true; $("#sys-btn").setAttribute("aria-expanded", "false"); } });
document.addEventListener("keydown", e => { if (e.key === "Escape" && !keys.capturing) { $("#sys-pop").hidden = true; $("#sys-btn").setAttribute("aria-expanded", "false"); closeLog(); closeSetup(); } });

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
  state.chart.timeScale().subscribeVisibleLogicalRangeChange(r => onChartRange(r));
  wireChartAuto();
}

/* ---------- chart auto-align: price axis auto-scaled, default candle width, newest candle at the right edge ----------
   After you zoom, scroll or drag an axis the chart straightens itself AUTO_MS later (the Auto button drains a small bar
   while it waits). Click Auto to turn that off; double-click the chart to realign right away. */
const AUTO_MS = 10000, BAR_SPACING = 6, RIGHT_OFFSET = 6;
state.chartAuto = (() => { try { return localStorage.getItem("chartAuto") !== "off"; } catch (e) { return true; } })();
state.autoT = null;
function setAutoBtn() {
  const b = $("#chart-auto"); b.classList.toggle("on", state.chartAuto); b.setAttribute("aria-pressed", String(state.chartAuto));
  b.title = state.chartAuto ? "Auto-align is on: after you zoom or drag, the chart straightens itself 10 seconds later. Click to turn it off. Double-click the chart to realign right away."
    : "Auto-align is off, so the chart stays where you put it. Click to turn it on and realign. Double-click the chart to realign once.";
}
function countdown(on) {
  const c = $("#chart-auto .count"); if (!c?.animate) return;
  c._a?.cancel(); c._a = null;
  if (on && motionOK()) c._a = c.animate([{ transform: "scaleX(1)" }, { transform: "scaleX(0)" }], { duration: AUTO_MS, easing: "linear", fill: "forwards" });
}
function chartTouched() {
  if (!state.chartAuto) return;
  const now = performance.now(); if (now - (state.touchAt || 0) < 150) return; state.touchAt = now;
  clearTimeout(state.autoT); countdown(true);
  state.autoT = setTimeout(() => realignChart(), AUTO_MS);
}
function realignChart(instant = false) {
  clearTimeout(state.autoT); state.autoT = null; countdown(false);
  const ch = state.chart; if (!ch || !state.series) return;
  // deep in history: bring the live window back first (this also unloads the history that was loaded)
  if (!state.replay?.view && state.win.bars.length && !state.win.live) { loadLatestWindow().then(() => realignChart(true)).catch(() => {}); return; }
  ch.priceScale("right").applyOptions({ autoScale: true });
  const ts = ch.timeScale(), n = state.series.data ? state.series.data().length : 0, w = ts.width();
  cancelAnimationFrame(state.autoRaf);
  if (!n || !w) { ts.applyOptions({ barSpacing: BAR_SPACING }); ts.scrollToRealTime(); return; }
  const to = n - 1 + RIGHT_OFFSET, target = { from: to - w / BAR_SPACING, to }, cur = ts.getVisibleLogicalRange();
  if (instant || !cur || !motionOK() || !shown($("#chart"))) { ts.setVisibleLogicalRange(target); return; }
  const b = $("#chart-auto"); b.classList.add("snap"); setTimeout(() => b.classList.remove("snap"), 450);
  const t0 = performance.now(), dur = 420, f0 = cur.from, e0 = cur.to;
  const step = now => { const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
    ts.setVisibleLogicalRange({ from: f0 + (target.from - f0) * e, to: e0 + (target.to - e0) * e });
    if (p < 1) state.autoRaf = requestAnimationFrame(step); };
  state.autoRaf = requestAnimationFrame(step);
}
function wireChartAuto() {
  const el = $("#chart"), b = $("#chart-auto");
  setAutoBtn();
  b.onclick = () => {
    state.chartAuto = !state.chartAuto; try { localStorage.setItem("chartAuto", state.chartAuto ? "on" : "off"); } catch (e) {}
    setAutoBtn(); if (state.chartAuto) realignChart(); else { clearTimeout(state.autoT); state.autoT = null; countdown(false); }
  };
  el.addEventListener("wheel", chartTouched, { passive: true });
  let start = null;
  el.addEventListener("pointerdown", e => { start = [e.clientX, e.clientY]; });
  el.addEventListener("pointermove", e => { if (!e.buttons) return; scheduleSessions(); if (start && Math.hypot(e.clientX - start[0], e.clientY - start[1]) > 3) chartTouched(); });
  addEventListener("pointerup", () => { start = null; });
  el.addEventListener("dblclick", () => realignChart());
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { moveRailInd(); scheduleSessions(); if (state.chartAuto && !state.autoT && state.tab === "dash") realignChart(true); }, 200); });
}
/* ---------- replay: bot on downloaded history ---------- */
state.replay = { view: false, running: false };
const speedFromSlider = v => +v >= 100 ? 0 : Math.round(Math.pow(20000, v / 100));   // 0..99 -> 1..~18k candles/s (log), 100 = max
const sliderFromSpeed = s => !s ? 100 : Math.min(99, Math.round(Math.log(Math.max(1, s)) / Math.log(20000) * 100));
const speedText = s => !s ? "Max (as fast as the PC can)" : `${s.toLocaleString()} candles/s`;
function setReplayView(on) {
  state.replay.view = on;
  $("#replay-toggle").classList.toggle("active", on);
  $("#replay-bar").classList.toggle("hidden", !on);
  if (on) $("#chart-msg").classList.add("hidden");
  state.series && state.series.setData([]);
  state.realignNext = true; state.lastBidShown = null; state.win = newWin(); clearPriorDay(); scheduleSessions();
  loadBars();
}
$("#replay-toggle").onclick = () => setReplayView(!state.replay.view);
$("#rp-speed").addEventListener("input", e => { $("#rp-speed-txt").textContent = speedText(speedFromSlider(e.target.value)); });
$("#rp-speed").addEventListener("change", e => setReplaySpeed(speedFromSlider(e.target.value)));
$("#rp-start").onclick = async () => {
  const [from, days] = $("#rp-days").value.split("|");
  try { await api("/api/replay/start", { method: "POST", body: { from, days: Number(days), speed: speedFromSlider($("#rp-speed").value), fresh: true } }); toast("Replay started. Scoring the history first, a few seconds."); }
  catch (e) { toast(e.message, true); }
};
$("#rp-pause").onclick = async () => { const c = await api("/api/replay/state"); await api("/api/replay/control", { method: "POST", body: { paused: !c.control?.paused } }); };
const setReplaySpeed = sp => {
  $("#rp-speed").value = sliderFromSpeed(sp); $("#rp-speed-txt").textContent = speedText(sp);
  document.querySelectorAll("#rp-presets button").forEach(b => b.classList.toggle("active", +b.dataset.speed === sp));
  return api("/api/replay/control", { method: "POST", body: { speed: sp } });
};
document.querySelectorAll("#rp-presets button").forEach(b => b.onclick = () => setReplaySpeed(+b.dataset.speed));
$("#rp-stop").onclick = () => api("/api/replay/control", { method: "POST", body: { stop: true } });
const eta = sec => sec < 90 ? `${Math.round(sec)}s` : sec < 5400 ? `${Math.round(sec / 60)} min` : `${(sec / 3600).toFixed(1)} h`;
async function loadReplay() {
  let r;
  try { r = await api("/api/replay/state"); } catch (e) { return; }
  state.replay.running = r.job_running; state.replay.last = r;
  $("#rp-pause").textContent = r.control?.paused ? "Resume" : "Pause";
  if (document.activeElement !== $("#rp-speed")) { $("#rp-speed").value = sliderFromSpeed(r.control?.speed ?? 20); $("#rp-speed-txt").textContent = speedText(r.control?.speed ?? 20);
    document.querySelectorAll("#rp-presets button").forEach(b => b.classList.toggle("active", +b.dataset.speed === (r.control?.speed ?? 20))); }
  $("#rp-prog").style.width = r.total ? `${(100 * r.index / r.total).toFixed(1)}%` : "0";
  const st = r.stats || {};
  $("#rp-status").textContent = !r.total ? (r.job_running ? "Scoring the history with the model..." : "Replays your downloaded M1 history through the bot with all its rules. Trades are recorded as \"replay\" and feed its learning.")
    : `${(r.bar_time_utc || "").slice(0, 16)} · ${r.index.toLocaleString()} / ${r.total.toLocaleString()} candles · ${r.open}/${r.max_open} open · ${st.closed || 0} closed · win ${st.win_pct ?? "–"}% · net ${signed(st.net_pnl || 0)} · score ${pts(st.score || 0)}${!r.done && r.rate ? ` · ${r.rate.toLocaleString()}/s · ${eta((r.total - r.index) / r.rate)} left` : ""}${r.done ? " · finished" : r.control?.paused ? " · paused" : ""}${r.skips?.length ? ` · signals skipped: ${r.skips.slice(0, 2).map(([k, n]) => `${k} ${n.toLocaleString()}`).join(", ")}` : ""}`;
  if (state.series && r.bars?.length) queueReplayBars(r);
}

// Smooth replay chart: new candles from each poll go into a queue and are drawn a few per animation frame, so the
// chart glides at the replay's pace instead of jumping a whole snapshot every poll.
const rpAnim = { queue: [], shown: 0, first: 0, carry: 0, lastFrame: 0, symbol: "" };
function queueReplayBars(r) {
  const bars = r.bars, newest = rpAnim.queue.length ? rpAnim.queue[rpAnim.queue.length - 1].time : rpAnim.shown;
  const fresh = bars.filter(b => b.time > newest);
  rpAnim.symbol = r.symbol;
  // first poll, a restart, or candles were missed between polls: redraw the window and carry on from there
  if (!rpAnim.shown || bars[bars.length - 1].time < rpAnim.shown || bars[0].time > newest
      || rpAnim.queue.length + fresh.length > 6000) {
    state.series.setData(bars);
    rpAnim.queue = []; rpAnim.first = bars[0].time; rpAnim.shown = bars[bars.length - 1].time;
    showReplayPrice(bars[bars.length - 1]);
    if (state.realignNext || state.chartAuto && !state.autoT) { state.realignNext = false; realignChart(true); }
  } else rpAnim.queue.push(...fresh);
  drawBotOverlay();
  if (!rpAnim.lastFrame) requestAnimationFrame(replayFrame);
}
function showReplayPrice(bar) {
  state.barRange = [rpAnim.first, bar.time];
  $("#q-sym").textContent = `${rpAnim.symbol} · replay`; $("#q-bid").textContent = fmt(bar.close, state.digits);
}
function replayFrame(now) {
  const dt = rpAnim.lastFrame ? Math.min(0.1, (now - rpAnim.lastFrame) / 1000) : 0.016;
  rpAnim.lastFrame = now;
  if (!state.replay.view) { rpAnim.lastFrame = 0; rpAnim.queue = []; rpAnim.shown = 0; return; }
  // drain the queue over ~0.45 s (about one poll), so the pace follows whatever speed the replay is really running at
  rpAnim.carry += rpAnim.queue.length * dt / 0.45;
  let n = Math.floor(rpAnim.carry);
  if (n > 0 && state.series) {
    rpAnim.carry -= n;
    let bar;
    while (n-- > 0 && rpAnim.queue.length) { bar = rpAnim.queue.shift(); state.series.update(bar); }
    if (bar) { rpAnim.shown = bar.time; showReplayPrice(bar); }
  }
  requestAnimationFrame(replayFrame);
}
/* ---------- lazy chart history ----------
   Only the candles around what you're looking at are loaded. Scroll far enough left and the next HIST.CHUNK older
   candles load; the window never holds more than HIST.MAX, so the far side is unloaded (the newest candles when you go
   back in time, the oldest when you come forward again). While the newest candle is in the window, each 3 s poll only
   fetches the last 3 candles instead of reloading everything. */
const HIST = { FIRST: 300, CHUNK: 500, MAX: 1800, MARGIN: 60 };
const newWin = () => ({ symbol: null, bars: [], live: true, begin: false, busy: false });
state.win = newWin();
const pickBar = b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close });
function showQuote(d) {
  state.digits = d.digits; state.lastBid = d.bid;
  const qb = $("#q-bid"), prevBid = state.lastBidShown;
  $("#q-sym").textContent = d.symbol; qb.textContent = fmt(d.bid, d.digits);
  if (prevBid != null && d.bid !== prevBid) flash(qb, d.bid > prevBid ? 1 : -1);
  state.lastBidShown = d.bid;
  $("#q-spr").textContent = Math.round((d.ask - d.bid) / d.point);
  $("#chart-msg").classList.add("hidden");
  if (!$("#sz-entry").value) $("#sz-entry").placeholder = fmt(d.bid, d.digits).replace(/,/g, "");
  if (d.bars.length) state.latestTime = Math.max(state.latestTime || 0, d.bars[d.bars.length - 1].time);
}
function applyWindow(shift = 0) {                // hand the window to the chart and keep the view where it was
  const W = state.win, ts = state.chart.timeScale(), r = shift ? ts.getVisibleLogicalRange() : null;
  state.series.setData(W.bars);
  if (r) ts.setVisibleLogicalRange({ from: r.from + shift, to: r.to + shift });
  state.barRange = W.bars.length ? [W.bars[0].time, W.bars[W.bars.length - 1].time] : null;
  drawBotOverlay();
}
async function loadLatestWindow() {
  const sym = state.symbol, d = await api(`/api/bars?symbol=${encodeURIComponent(sym)}&count=${HIST.FIRST}`);
  if (sym !== state.symbol || state.replay?.view) return;
  const W = state.win = Object.assign(newWin(), { symbol: sym, bars: d.bars.map(pickBar), busy: true });
  state.series.applyOptions({ priceFormat: { type: "price", precision: d.digits, minMove: d.point } });
  showQuote(d); applyWindow(); updatePriorDay();
  requestAnimationFrame(() => requestAnimationFrame(() => { W.busy = false; }));   // ignore the scroll events of the swap itself
}
async function loadBars() {
  if (state.replay?.view) return loadReplay();
  if (!state.series || !state.symbol) return;
  const W = state.win;
  try {
    if (W.symbol !== state.symbol || !W.bars.length) {
      await loadLatestWindow();
      if (state.realignNext) { state.realignNext = false; realignChart(true); }
      return;
    }
    const d = await api(`/api/bars?symbol=${encodeURIComponent(state.symbol)}&count=3`);
    if (W !== state.win) return;
    showQuote(d);
    if (!W.live || !d.bars.length) return;                       // looking at history: only the quote refreshes
    if (d.bars[0].time > W.bars[W.bars.length - 1].time + 60) return loadLatestWindow();   // candles were missed (app asleep)
    for (const b of d.bars.map(pickBar)) {
      const n = W.bars.length, tail = W.bars[n - 1];
      if (b.time === tail.time) W.bars[n - 1] = b; else if (b.time > tail.time) W.bars.push(b); else continue;
      state.series.update(b);
    }
    if (W.bars.length > HIST.MAX + 120) trimOldest();            // a long live session: drop candles far off to the left
    state.barRange = [W.bars[0].time, W.bars[W.bars.length - 1].time];
    drawBotOverlay(); updatePriorDay();
  } catch (e) {
    const m = $("#chart-msg"); m.textContent = e.message; m.classList.remove("hidden");
  }
}
function trimOldest() {
  const W = state.win, r = state.chart.timeScale().getVisibleLogicalRange();
  const cut = Math.min(W.bars.length - HIST.MAX, Math.floor(r?.from ?? 0) - HIST.MARGIN * 2);
  if (cut > 0) { W.bars.splice(0, cut); W.begin = false; applyWindow(-cut); }
}
async function loadOlder() {
  const W = state.win; if (W.busy || W.begin || !W.bars.length || state.replay?.view) return;
  W.busy = true;
  try {
    const first = W.bars[0].time, d = await api(`/api/bars?symbol=${encodeURIComponent(W.symbol)}&count=${HIST.CHUNK}&before=${first}`);
    if (W !== state.win) return;
    const older = d.bars.filter(b => b.time < first).map(pickBar);
    if (older.length < HIST.CHUNK) W.begin = true;                // reached the start of what the broker keeps
    if (!older.length) return;
    W.bars = older.concat(W.bars);
    const r = state.chart.timeScale().getVisibleLogicalRange();
    const keepTo = Math.ceil((r ? r.to : W.bars.length) + older.length) + HIST.MARGIN * 2;
    const cut = Math.min(W.bars.length - HIST.MAX, W.bars.length - 1 - keepTo);
    if (cut > 0) { W.bars.length -= cut; W.live = false; }        // unload the newest candles, now far off to the right
    applyWindow(older.length);
  } catch (e) { W.begin = true; }
  finally { W.busy = false; }
}
async function loadNewer() {
  const W = state.win; if (W.busy || W.live || !W.bars.length || state.replay?.view) return;
  W.busy = true;
  try {
    const last = W.bars[W.bars.length - 1].time;
    const d = await api(`/api/bars?symbol=${encodeURIComponent(W.symbol)}&count=${HIST.CHUNK + 1}&before=${last + (HIST.CHUNK + 1) * 60}`);
    if (W !== state.win) return;
    const newer = d.bars.filter(b => b.time > last).map(pickBar);
    if (!newer.length) { W.live = true; return; }
    W.bars = W.bars.concat(newer);
    if (newer[newer.length - 1].time >= (state.latestTime || Infinity)) W.live = true;   // caught up with the present
    const r = state.chart.timeScale().getVisibleLogicalRange();
    const cut = Math.min(W.bars.length - HIST.MAX, Math.floor(r ? r.from : 0) - HIST.MARGIN * 2);
    if (cut > 0) { W.bars.splice(0, cut); W.begin = false; }      // unload the oldest candles, now far off to the left
    applyWindow(cut > 0 ? -cut : 0);
  } catch (e) {}
  finally { W.busy = false; }
}
/* ---------- session bands + prior-day levels, in broker server time like agent/pro.py ----------
   Asia range = the 01:00–09:00 candles; London opens 10:00, New York 16:30; the prior day is the last full server day
   before today. Drawn in a layer over the chart from the chart's own coordinates, redrawn once per frame at most and
   only when the view or the data changes. Settings > Display can switch it off. */
const PRO = { asia: [1 * 3600, 9 * 3600], london: 10 * 3600, ny: 16.5 * 3600 };
state.showSessions = (() => { try { return localStorage.getItem("sessions") !== "off"; } catch (e) { return true; } })();
state.pd = { key: "", lines: [] };
let sessRaf = 0;
function scheduleSessions() { if (!sessRaf) sessRaf = requestAnimationFrame(() => { sessRaf = 0; drawSessions(); }); }
function barIndexAt(bars, t) {                   // first candle at or after time t
  let lo = 0, hi = bars.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (bars[m].time < t) lo = m + 1; else hi = m; }
  return lo;
}
function drawSessions() {
  const layer = $("#chart-layer"); if (!layer || !state.chart) return;
  const ts = state.chart.timeScale(), bars = state.win.bars, r = ts.getVisibleLogicalRange();
  if (!state.showSessions || state.replay?.view || bars.length < 2 || !r) { setHTML(layer, ""); return; }
  const w = ts.width(), h = $("#chart").clientHeight - ts.height();
  if (layer._w !== w || layer._h !== h) { layer.style.width = w + "px"; layer.style.height = h + "px"; layer._w = w; layer._h = h; }
  const i0 = Math.max(0, Math.floor(r.from)), i1 = Math.min(bars.length - 1, Math.ceil(r.to));
  const t0 = bars[i0].time, t1 = bars[i1].time + Math.max(0, r.to - i1) * 60;
  if (i1 <= i0 || t1 - t0 > 3 * 86400) { setHTML(layer, ""); return; }        // zoomed far out: bands would only clutter
  const xa = ts.logicalToCoordinate(i0), xb = ts.logicalToCoordinate(i1); if (xa == null || xb == null) return;
  const per = (xb - xa) / (i1 - i0), xOf = L => xa + (L - i0) * per;
  const xOfTime = t => { const k = barIndexAt(bars, t), n = bars.length;
    return k >= n ? xOf(n - 1 + (t - bars[n - 1].time) / 60) : k === 0 && bars[0].time > t + 60 ? null : xOf(k); };
  const Y = p => state.series.priceToCoordinate(p);
  let html = "";
  for (let day = t0 - (t0 % 86400); day <= t1; day += 86400) {
    const a = barIndexAt(bars, day + PRO.asia[0]), b = barIndexAt(bars, day + PRO.asia[1]) - 1;
    if (a < bars.length && b >= a && bars[a].time < day + PRO.asia[1]) {
      let hi = -Infinity, lo = Infinity;
      for (let k = a; k <= b; k++) { if (bars[k].high > hi) hi = bars[k].high; if (bars[k].low < lo) lo = bars[k].low; }
      const x0 = xOf(a) - per / 2, x1 = xOf(b) + per / 2, y0 = Y(hi), y1 = Y(lo);
      if (x1 > 0 && x0 < w && y0 != null && y1 != null)
        html += `<div class="sess-box" style="transform:translate(${x0.toFixed(1)}px,${y0.toFixed(1)}px);width:${(x1 - x0).toFixed(1)}px;height:${Math.max(2, y1 - y0).toFixed(1)}px"><span>Asia range</span></div>`;
    }
    for (const [t, label] of [[day + PRO.london, "London open"], [day + PRO.ny, "New York open"]]) {
      if (t < bars[0].time) continue;
      const x = xOfTime(t);
      if (x != null && x > 0 && x < w - 2) html += `<div class="sess-line" style="transform:translateX(${x.toFixed(1)}px)"><span>${label}</span></div>`;
    }
  }
  setHTML(layer, html);
}
function clearPriorDay() { state.pd.lines.forEach(l => state.series.removePriceLine(l)); state.pd = { key: "", lines: [] }; }
async function updatePriorDay() {                // once per symbol per server day
  const W = state.win; if (!W.bars.length || state.replay?.view || !state.showSessions) return;
  const ref = Math.max(state.latestTime || 0, W.bars[W.bars.length - 1].time), day = ref - (ref % 86400), key = `${W.symbol}|${day}`;
  if (state.pd.key === key) return;
  clearPriorDay(); state.pd.key = key;
  let d; try { d = await api(`/api/bars?symbol=${encodeURIComponent(W.symbol)}&count=1440&before=${day}`); } catch (e) { return; }
  if (state.pd.key !== key || !d.bars.length) return;
  const lastT = d.bars[d.bars.length - 1].time, prevDay = lastT - (lastT % 86400);   // the last day that traded (Friday on Mondays)
  const prev = d.bars.filter(b => b.time >= prevDay); if (!prev.length) return;
  const mk = (price, title) => state.series.createPriceLine({ price, color: "rgba(230,227,218,.5)", lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title });
  state.pd.lines = [mk(Math.max(...prev.map(b => b.high)), "prior-day high"), mk(Math.min(...prev.map(b => b.low)), "prior-day low")];
}
function setShowSessions(on) {
  state.showSessions = on; try { localStorage.setItem("sessions", on ? "on" : "off"); } catch (e) {}
  if (on) { state.pd.key = ""; updatePriorDay(); } else clearPriorDay();
  scheduleSessions();
}
function onChartRange(r) {                       // called while scrolling; loads are single-flight
  scheduleSessions();
  const W = state.win; if (!r || state.replay?.view || !W.bars.length) return;
  if (r.from < HIST.MARGIN) loadOlder();
  else if (!W.live && r.to > W.bars.length - HIST.MARGIN) loadNewer();
}
function renderChips() {
  const box = $("#symbols"); box.innerHTML = "";
  (state.settings.symbols_watch || []).forEach(sym => {
    const b = document.createElement("button"); b.className = "chip" + (sym === state.symbol ? " active" : ""); b.textContent = sym;
    b.onclick = () => selectSymbol(sym);
    box.appendChild(b);
  });
}

function selectSymbol(sym) {
  if (sym === state.symbol) return;
  state.symbol = sym; renderChips(); state.series && state.series.setData([]);
  state.realignNext = true; state.lastBidShown = null; state.win = newWin(); loadBars(); sizeTrade();
}

/* ---------- the bot's own trades: card, chart overlay, history, alerts ---------- */
state.bot = { known: null, data: null, filter: "", lines: [] };
let audioCtx;
document.addEventListener("pointerdown", () => audioCtx && audioCtx.state === "suspended" && audioCtx.resume());
const px = (v, sym) => v == null ? "—" : Number(v).toFixed(sym === state.symbol ? state.digits : (v < 20 ? 5 : 2));
const signed = v => v == null ? "—" : `${v >= 0 ? "+" : ""}${fmt(v)}`;
const cls = v => v > 0 ? "up" : v < 0 ? "down" : "";
const pts = v => v == null ? "" : `${v >= 0 ? "+" : ""}${Number(v).toFixed(2)}`;   // 1 point = $1

async function pollBot() {
  let d;
  try { d = await api("/api/bot/trades?limit=200"); } catch (e) { return; }
  state.bot.data = d;
  const now = new Map(d.recent.map(t => [t.id, t.status]));
  if (state.bot.known) {
    for (const t of d.recent) {
      const before = state.bot.known.get(t.id);
      if (before === undefined && t.status === "open") {
        notify({ kind: "info", title: `Bot ${t.side === "buy" ? "bought" : "sold"} ${t.lots} ${t.symbol} (${t.mode})`, body: `at ${px(t.entry, t.symbol)}, stop ${px(t.sl, t.symbol)}, target ${px(t.tp, t.symbol)}`, onClick: () => showTab("dash") });
        playEvent("botOpen");
        $("#bot-card").classList.remove("live"); void $("#bot-card").offsetWidth; $("#bot-card").classList.add("live");
        tradeMoment();
      } else if (before === "open" && t.status === "closed") {
        if (!(alertsState.ok && (t.mode === "demo" || t.mode === "real")))
          notify({ kind: t.pnl >= 0 ? "tp" : "sl", title: `Bot closed #${t.id} (${t.mode})`, body: `${t.side} ${t.lots} ${t.symbol}, ${REASON[t.exit_reason] || t.exit_reason || "closed"}${t.score != null ? `, ${pts(t.score)} pts` : ""}`, amount: t.pnl, onClick: () => showTab("agent") });
        if (!(alertsState.ok && (t.mode === "demo" || t.mode === "real"))) playEvent(t.pnl >= 0 ? "profit" : "loss");   // demo/real ring from /api/events
        state.cal.loaded = 0;                       // the calendar picks the closed trade up on its next look
      }
    }
  }
  state.bot.known = now;
  renderBotCard(); drawBotOverlay();
  if (state.tab === "agent") renderBotTable();
}
// the one deliberate motion moment: when the bot enters, the chart panel glows gold once
function tradeMoment() {
  const p = $(".chart-panel"); if (!p?.animate || !motionOK() || !shown(p)) return;
  p.animate([{ boxShadow: "0 0 0 1px rgba(201,162,74,.75), 0 0 38px rgba(201,162,74,.3)" }, { boxShadow: "0 0 0 1px rgba(201,162,74,0), 0 0 0 rgba(201,162,74,0)" }],
    { duration: 1600, easing: "cubic-bezier(.22,1,.36,1)" });
}
const ICON = {
  bot: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="7" width="14" height="11" rx="3"/><path d="M12 3v4M9 12h.01M15 12h.01M9 15.5h6"/></svg>`,
  list: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h10M4 17h6"/></svg>`,
};

function renderBotCard() {
  const d = state.bot.data; if (!d) return;
  const box = $("#bot-now"), open = d.open.filter(t => (t.mode === "replay") === !!state.replay?.view);
  const cap = m => m[0].toUpperCase() + m.slice(1);
  setHTML($("#bot-today"), Object.entries(d.stats).filter(([m, s]) => m !== "replay" && (s.closed || s.open))
    .map(([m, s]) => `<span title="${pts(s.today_score)} points today">${cap(m)} today <b class="${cls(s.today_pnl)}">${signed(s.today_pnl)}</b></span>`).join(""));
  // top bar: the bot's money today in the stage it is working at
  const sm = d.stats[state.mode] || {}, top = $("#bot-today-top");
  $("#today-label").textContent = `Bot today · ${state.mode}`;
  setNum(top, sm.today_pnl ?? 0, signed); top.className = `num flashable ${cls(sm.today_pnl)}`;
  if (!open.length) {
    state.bot.cardMax ??= d.recent.reduce((mx, t) => Math.max(mx, t.id), 0);   // so the next entry animates in
    $("#bot-card").classList.remove("live");
    const rp = state.replay?.view && state.replay.last?.total ? state.replay.last : null;
    const a = rp ? { ...rp, mode: "replay", bar: (rp.bar_time_utc || "").slice(11, 16) } : d.agent;
    const pct = v => v == null ? "–" : `${v < 0.1 ? (v * 100).toFixed(1) : Math.round(v * 100)}%`;
    const need = a ? (a.need ?? a.threshold) : 1;
    setHTML(box, a ? `<div class="watch">
        <div class="watch-head"><span class="live-dot"></span><strong>Watching ${state.settings?.symbol || ""} · ${a.mode || ""}</strong><span class="muted small">${a.bar ? "candle " + a.bar : ""}</span></div>
        ${a.p_buy != null ? `<div class="conf"><span>Buy</span><div class="bar"><i style="width:${Math.min(100, a.p_buy / Math.max(need, .001) * 100)}%"></i></div><span class="num">${pct(a.p_buy)}</span></div>
        <div class="conf"><span>Sell</span><div class="bar"><i style="width:${Math.min(100, a.p_sell / Math.max(need, .001) * 100)}%"></i></div><span class="num">${pct(a.p_sell)}</span></div>
        <p class="muted small" style="margin:4px 0 0">Needs ${pct(need)} to enter${a.practice ? " (practice: its best ~10% of readings)" : ""} · ${a.open ?? 0}/${a.max_open ?? "–"} open</p>` : ""}
        ${a.setups?.length ? `<div class="setups"><span class="muted small">Pro read:</span>${a.setups.map(x => `<span class="setup-chip">${x}</span>`).join("")}</div>` : ""}
        <p class="small" style="margin:8px 0 0"><b>${a.decision}</b>${a.reason ? ` · <span class="muted">${a.reason}</span>` : ""}</p></div>`
      : `<div class="empty-state compact">${ICON.bot}<div><b>The bot isn't running</b>Start it on the Agent tab. When it enters you get an alert, and its entry, stop and target are drawn on the chart.</div><button class="btn xs" data-goto="agent">Open Agent</button></div>`);
    return;
  }
  $("#bot-card").classList.add("live");
  const now = state.replay?.view ? state.replay.last : d.agent;
  const proRead = now?.setups?.length ? `<div class="setups" style="margin:0 0 8px"><span class="muted small">Pro read:</span>${now.setups.map(x => `<span class="setup-chip">${x}</span>`).join("")}</div>` : "";
  const firstCard = state.bot.cardMax == null, cardMax = state.bot.cardMax ?? Infinity;
  state.bot.cardMax = Math.max(state.bot.cardMax ?? 0, ...open.map(t => t.id));
  const prevPl = state.bot.pl || {}; state.bot.pl = Object.fromEntries(open.map(t => [t.id, t.pnl]));
  setHTML(box, proRead + open.slice().reverse().map(t => {
    const risk = Math.abs(t.entry - t.sl0), rNow = t.price != null && risk ? ((t.side === "buy" ? t.price - t.entry : t.entry - t.price) / risk) : null;
    return `<div class="bt2${!firstCard && t.id > cardMax ? " enter" : ""}">
      <div class="bt2-head"><span class="bt2-side"><span class="dir ${t.side}">${t.side === "buy" ? "▲ BUY" : "▼ SELL"}</span>${t.symbol}<span class="who">BOT</span></span>
        <span class="bt2-pl"><b class="flashable ${cls(t.pnl)}" data-pl="${t.id}">${signed(t.pnl)}</b><small>${rNow != null ? `${rNow >= 0 ? "+" : ""}${rNow.toFixed(2)}R now` : ""}</small></span></div>
      <dl class="bt2-meta"><dt>Lots</dt><dd>${t.lots}</dd><dt>Mode</dt><dd>${t.mode}</dd><dt>Conf.</dt><dd>${t.prob ? Math.round(t.prob * 100) + "%" : "–"}</dd><dt>Trade</dt><dd>#${t.id}</dd>
        ${t.setup ? `<dt>Setup</dt><dd class="wide">${d.setup_names?.[t.setup] || t.setup}</dd>` : ""}</dl>
      <div class="bt2-levels"><div><span>Entry</span><b>${px(t.entry, t.symbol)}</b></div><div class="sl"><span>Stop</span><b>${px(t.sl, t.symbol)}</b></div><div class="tp"><span>Target</span><b>${px(t.tp, t.symbol)}</b></div></div>
      <div class="bt2-foot"><span>opened ${(t.open_utc || "").slice(11, 16)} UTC</span>
        <span class="row gap"><button class="btn xs" data-follow="${t.id}" title="Put the bot's stop into the sizer to size your own copy">Size mine</button><button class="btn xs" data-copy="${t.id}">Copy levels</button></span></div></div>`;
  }).join(""));
  open.forEach(t => { const p0 = prevPl[t.id]; if (p0 != null && t.pnl != null && t.pnl !== p0) flash(box.querySelector(`[data-pl="${t.id}"]`), t.pnl > p0 ? 1 : -1); });
}
$("#bot-now").addEventListener("click", async e => {
  const f = e.target.closest("[data-follow]"), c = e.target.closest("[data-copy]");
  const t = state.bot.data?.open.find(x => x.id == (f || c)?.dataset[f ? "follow" : "copy"]); if (!t) return;
  if (f) {
    selectSymbol(t.symbol); $("#sz-entry").value = ""; $("#sz-stop").value = px(t.sl, t.symbol); sizeTrade();
    toast("Sizer filled with the bot's stop. Entry uses the current price; adjust the risk slider for your size.");
  } else {
    const txt = `${t.symbol} ${t.side.toUpperCase()} entry ${px(t.entry, t.symbol)} SL ${px(t.sl, t.symbol)} TP ${px(t.tp, t.symbol)}`;
    try { await navigator.clipboard.writeText(txt); toast("Copied: " + txt); } catch (err) { toast(txt); }
  }
});

function drawBotOverlay() {
  const d = state.bot.data; if (!d || !state.series) return;
  state.bot.lines.forEach(l => state.series.removePriceLine(l)); state.bot.lines = [];
  const inView = t => (t.mode === "replay") === !!state.replay?.view;
  d.open.filter(t => t.symbol === state.symbol && inView(t)).forEach(t => {
    const mk = (price, color, title, style) => price && state.bot.lines.push(state.series.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }));
    mk(t.entry, "#89cff0", `bot ${t.side}`, 2); mk(t.sl, "#e0574f", "bot SL", 0); mk(t.tp, "#3fb68b", "bot TP", 0);
  });
  const r = state.barRange; if (!r) { state.series.setMarkers([]); return; }
  const snap = t => t - (t % 60), inRange = t => t && t >= r[0] && t <= r[1] + 60;
  const marks = [];
  d.recent.filter(t => t.symbol === state.symbol && inView(t)).forEach(t => {
    if (inRange(t.open_bar)) marks.push({ time: Math.min(snap(t.open_bar), r[1]), position: t.side === "buy" ? "belowBar" : "aboveBar",
      color: t.side === "buy" ? "#3fb68b" : "#e0574f", shape: t.side === "buy" ? "arrowUp" : "arrowDown", text: `bot ${t.side} ${t.lots}` });
    if (t.status === "closed" && inRange(t.close_bar)) marks.push({ time: Math.min(snap(t.close_bar), r[1]), position: t.side === "buy" ? "aboveBar" : "belowBar",
      color: t.pnl >= 0 ? "#3fb68b" : "#e0574f", shape: "circle", text: t.r_multiple != null ? `${t.r_multiple >= 0 ? "+" : ""}${t.r_multiple}R` : t.exit_reason });
  });
  marks.sort((a, b) => a.time - b.time);
  state.series.setMarkers(marks);
  scheduleSessions();
}

function renderBotTable() {
  const d = state.bot.data; if (!d) return;
  const m = state.bot.filter, day = state.cal.day;
  // a picked calendar day shows every trade that closed that day (from the calendar's longer list)
  const rows = day ? state.cal.trades.filter(t => (!m || t.mode === m) && t.close_utc.slice(0, 10) === day)
                   : d.recent.filter(t => !m || t.mode === m);
  const dayBox = $("#bt-day"); dayBox.hidden = !day;
  if (day) setHTML(dayBox, `<span>${rows.length} trade${rows.length === 1 ? "" : "s"} closed on <b class="num">${day}</b> (UTC)</span><button data-clear-day>Show all trades</button>`);
  const firstRows = state.bot.rowMax == null, rowMax = state.bot.rowMax ?? Infinity;
  if (!day) state.bot.rowMax = Math.max(state.bot.rowMax ?? 0, ...rows.map(t => t.id));
  const S = m ? d.stats[m] : Object.values(d.stats).reduce((a, s) => ({ closed: a.closed + s.closed, open: a.open + s.open,
    net_pnl: a.net_pnl + s.net_pnl, today_pnl: a.today_pnl + s.today_pnl, total_r: a.total_r + s.total_r,
    wins: a.wins + (s.win_pct || 0) * s.closed / 100, score: a.score + (s.score || 0), today_score: a.today_score + (s.today_score || 0),
    sl_hits: a.sl_hits + (s.sl_hits || 0), early_exits: a.early_exits + (s.early_exits || 0) }),
    { closed: 0, open: 0, net_pnl: 0, today_pnl: 0, total_r: 0, wins: 0, score: 0, today_score: 0, sl_hits: 0, early_exits: 0 });
  const win = m ? S.win_pct : (S.closed ? (100 * S.wins / S.closed).toFixed(1) : null);
  const avgR = m ? S.avg_r : (S.closed ? (S.total_r / S.closed).toFixed(2) : null);
  const card = (label, val, c = "") => `<div class="stat"><span>${label}</span><strong class="${c}">${val ?? "—"}</strong></div>`;
  const avgScore = S.closed ? (S.score / S.closed).toFixed(1) : "—";
  setHTML($("#bt-stats"), card("Score", pts(S.score), cls(S.score)) + card("Today's score", pts(S.today_score), cls(S.today_score))
    + card("Avg points / trade", avgScore) + card("Stops hit / early exits", `${S.sl_hits} / ${S.early_exits}`)
    + card("Closed trades", S.closed) + card("Open", S.open) + card("Win rate", win != null ? `${win}%` : "—")
    + card("Net P/L", signed(S.net_pnl), cls(S.net_pnl)) + card("Today", signed(S.today_pnl), cls(S.today_pnl))
    + card("Total R", S.total_r != null ? `${S.total_r >= 0 ? "+" : ""}${Number(S.total_r).toFixed(2)}` : "—", cls(S.total_r))
    + card("Avg R / trade", avgR) + (m ? card("Profit factor", S.profit_factor) : ""));
  setHTML($("#bt-table tbody"), rows.map(t => `<tr class="${t.status === "open" ? "open-row" : ""}${!firstRows && !day && t.id > rowMax ? " enter" : ""}"><td>${t.id}</td><td>${t.mode}</td>
    <td>${(t.open_utc || "").replace("T", " ").slice(0, 16)}</td><td>${t.symbol}</td><td class="${t.side === "buy" ? "up" : "down"}">${t.side === "buy" ? "▲" : "▼"} ${t.side}</td><td>${t.lots}</td>
    <td>${px(t.entry, t.symbol)}</td><td>${px(t.sl, t.symbol)}</td><td>${px(t.tp, t.symbol)}</td>
    <td>${t.status === "open" ? "open" : px(t.exit, t.symbol)}</td><td>${t.exit_reason || ""}</td>
    <td class="${cls(t.pnl)}">${t.status === "open" ? "" : signed(t.pnl)}</td><td class="${cls(t.r_multiple)}">${t.r_multiple ?? ""}</td><td class="${cls(t.score)}">${t.status === "open" ? "" : pts(t.score)}</td><td>${t.prob ? Math.round(t.prob * 100) + "%" : ""}</td><td class="small">${t.setup ? (d.setup_names?.[t.setup] || t.setup) : ""}</td></tr>`).join("")
    || `<tr><td colspan="16" class="muted">No bot trades yet${m ? ` in ${m} mode` : ""}. Start the agent and every trade it takes is recorded here, including ones that hit stop or target while the app was closed.</td></tr>`);
}
$("#bt-filter").addEventListener("click", e => {
  const b = e.target.closest("[data-m]"); if (!b) return;
  state.bot.filter = b.dataset.m; state.cal.day = null;
  $$("#bt-filter .chip").forEach(x => x.classList.toggle("active", x === b)); renderCalendar(); renderBotTable();
});
$("#bt-day").addEventListener("click", e => { if (e.target.closest("[data-clear-day]")) { state.cal.day = null; renderCalendar(); renderBotTable(); } });

/* ---------- daily P/L calendar: closed bot trades grouped by the UTC day they closed ---------- */
state.cal = { trades: [], loaded: 0, month: null, modeFor: null, day: null, animKey: "", days: new Map() };
async function loadCalendar(force = false) {
  if (force || Date.now() - state.cal.loaded > 60000) {
    try { const d = await api("/api/bot/trades?limit=3000"); state.cal.trades = d.recent.filter(t => t.status === "closed" && t.close_utc); state.cal.loaded = Date.now(); }
    catch (e) { /* keep what we had */ }
  }
  renderCalendar();
}
const pad2 = n => String(n).padStart(2, "0");
const shortPl = v => { const a = Math.abs(v); return (v >= 0 ? "+" : "−") + (a >= 1000 ? `${(a / 1000).toFixed(1)}k` : a >= 100 ? Math.round(a) : a.toFixed(1)); };
function renderCalendar() {
  const box = $("#bt-cal"), mode = state.bot.filter, days = new Map();
  for (const t of state.cal.trades) {
    if (mode && t.mode !== mode) continue;
    const k = t.close_utc.slice(0, 10), x = days.get(k) || { pnl: 0, n: 0, w: 0, l: 0, score: 0 }, p = t.pnl || 0;
    x.pnl += p; x.n++; if (p > 0) x.w++; else if (p < 0) x.l++; x.score += t.score || 0; days.set(k, x);
  }
  state.cal.days = days;
  const keys = [...days.keys()].sort(), today = new Date().toISOString().slice(0, 10);
  if (!state.cal.month || state.cal.modeFor !== mode) { state.cal.month = (keys[keys.length - 1] || today).slice(0, 7); state.cal.modeFor = mode; }
  const ym = state.cal.month, [Y, M] = ym.split("-").map(Number);
  const nDays = new Date(Date.UTC(Y, M, 0)).getUTCDate(), lead = (new Date(Date.UTC(Y, M - 1, 1)).getUTCDay() + 6) % 7;
  const month = keys.filter(k => k.startsWith(ym)).map(k => days.get(k));
  const maxAbs = Math.max(0.01, ...month.map(v => Math.abs(v.pnl)));
  const net = month.reduce((a, v) => a + v.pnl, 0), green = month.filter(v => v.pnl > 0).length, red = month.filter(v => v.pnl < 0).length;
  const best = Math.max(0, ...month.map(v => v.pnl)), worst = Math.min(0, ...month.map(v => v.pnl));
  const first = (keys[0] || today).slice(0, 7), last = [keys[keys.length - 1] || today, today].sort()[1].slice(0, 7);
  const label = new Date(Date.UTC(Y, M - 1, 1)).toLocaleString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
  let cells = "";
  for (let i = 0; i < lead; i++) cells += `<div class="cal-day pad"></div>`;
  for (let dd = 1; dd <= nDays; dd++) {
    const k = `${ym}-${pad2(dd)}`, v = days.get(k);
    const c = ["cal-day", v && "has", k === today && "today", k === state.cal.day && "sel", k > today && "future"].filter(Boolean).join(" ");
    const a = v ? (0.14 + 0.5 * Math.sqrt(Math.abs(v.pnl) / maxAbs)).toFixed(3) : 0;
    const bg = v ? `background:rgba(${v.pnl >= 0 ? "63,182,139" : "224,87,79"},${a})` : "";
    cells += `<div class="${c}" style="--i:${lead + dd - 1};${bg}"${v ? ` data-day="${k}"` : ""}><span class="d">${dd}</span>${v ? `<span class="n">${v.n}</span><span class="p">${shortPl(v.pnl)}</span>` : ""}</div>`;
  }
  const animKey = `${ym}|${mode}`, anim = state.cal.animKey !== animKey && motionOK(); state.cal.animKey = animKey;
  box.classList.toggle("anim", anim);
  if (anim) box._html = null;                    // month or mode changed: rebuild so the days ripple in
  setHTML(box, `<div class="cal-head"><span class="cal-title">${label}<small>daily P/L · UTC days</small></span>
      <span class="cal-nav"><button data-cal="-1" ${ym <= first ? "disabled" : ""} aria-label="Previous month">‹</button><button data-cal="1" ${ym >= last ? "disabled" : ""} aria-label="Next month">›</button></span></div>
    <div class="cal-sum"><span>Net <b class="${cls(net)}">${signed(net)}</b></span><span>Green days <b>${green}</b></span><span>Red days <b>${red}</b></span>${best > 0 ? `<span>Best <b class="up">${signed(best)}</b></span>` : ""}${worst < 0 ? `<span>Worst <b class="down">${signed(worst)}</b></span>` : ""}</div>
    <div class="cal-grid">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(x => `<span class="cal-dow">${x}</span>`).join("")}${cells}</div>
    ${keys.length ? "" : `<p class="cal-empty">No closed trades${mode ? ` in ${mode} mode` : ""} yet. Each day fills in as the bot's trades close: green for a winning day, red for a losing one.</p>`}
    <div class="cal-tip" hidden></div>`);
  renderLeaderboard();
}
function renderLeaderboard() {                   // which setups make money: net P/L per setup, same mode filter
  const mode = state.bot.filter, by = {}, names = state.bot.data?.setup_names || {};
  for (const t of state.cal.trades) {
    if (mode && t.mode !== mode) continue;
    const k = t.setup || "none", x = by[k] ||= { pl: 0, n: 0, w: 0 }, pl = t.pnl || 0;
    x.pl += pl; x.n++; if (pl > 0) x.w++;
  }
  const rows = Object.entries(by).sort((a, b) => b[1].pl - a[1].pl), mx = Math.max(1e-9, ...rows.map(([, v]) => Math.abs(v.pl)));
  $("#lb-meta").textContent = `${mode || "all modes"} · net P/L · trades · win %`;
  setHTML($("#leaderboard"), rows.length ? rows.slice(0, 10).map(([k, v]) => {
    const wd = (Math.abs(v.pl) / mx * 50).toFixed(1), name = k === "none" ? "No setup tagged" : names[k] || k;
    return `<span class="name" title="${name}">${name}</span><span class="track"><i class="${v.pl < 0 ? "neg" : ""}" style="${v.pl >= 0 ? `left:50%;width:${wd}%;background:var(--up)` : `right:50%;width:${wd}%;background:var(--down)`}"></i></span><span class="pl ${cls(v.pl)}">${signed(v.pl)}</span><span class="n">${v.n} · ${Math.round(100 * v.w / v.n)}%</span>`;
  }).join("") : `<div class="empty-state compact lb-empty">${ICON.list}<div><b>No closed trades yet</b>Each setup the bot trades gets a bar here: green when it makes money, red when it loses.</div></div>`);
}
$("#bt-cal").addEventListener("click", e => {
  const nav = e.target.closest("[data-cal]:not(:disabled)");
  if (nav) { const [Y, M] = state.cal.month.split("-").map(Number); state.cal.month = new Date(Date.UTC(Y, M - 1 + +nav.dataset.cal, 1)).toISOString().slice(0, 7); renderCalendar(); return; }
  const day = e.target.closest("[data-day]");
  if (day) { state.cal.day = state.cal.day === day.dataset.day ? null : day.dataset.day; renderCalendar(); renderBotTable(); }
});
$("#bt-cal").addEventListener("mouseover", e => {
  const c = e.target.closest("[data-day]"), tip = $("#bt-cal .cal-tip"); if (!tip) return;
  const v = c && state.cal.days.get(c.dataset.day); if (!v) { tip.hidden = true; return; }
  tip.innerHTML = `${c.dataset.day}<br>${v.n} trade${v.n > 1 ? "s" : ""} · ${v.w} won · ${v.l} lost<br>P/L <span class="${cls(v.pnl)}">${signed(v.pnl)}</span> · score ${pts(v.score)}`;
  tip.hidden = false;
  const bx = $("#bt-cal").getBoundingClientRect(), r = c.getBoundingClientRect();
  tip.style.left = Math.max(4, Math.min(r.left - bx.left, bx.width - tip.offsetWidth - 4)) + "px"; tip.style.top = (r.bottom - bx.top + 6) + "px";
});
$("#bt-cal").addEventListener("mouseleave", () => { const t = $("#bt-cal .cal-tip"); if (t) t.hidden = true; });

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
    const ps = await getPositions(), box = $("#positions");
    $("#pos-count").textContent = ps.length ? `${ps.length} open` : ""; $("#open-count").textContent = ps.length;
    const seen = state.posSeen; state.posSeen = new Set(ps.map(p => p.ticket));
    guessCloses(ps);
    if (!ps.length) { setHTML(box, `<div class="empty-state compact">${ICON.list}<div><b>Nothing open</b>Positions from the bot, Hermes or your own MT5 trades show up here.</div></div>`); return; }
    setHTML(box, ps.map(p => `<div class="pos ${p.side}${seen && !seen.has(p.ticket) ? " enter" : ""}">
      <span><strong>${p.symbol}</strong><span class="tag ${p.owner}">${{ bot: "Bot", hermes: "Hermes", you: "You" }[p.owner] || "You"}</span> <span class="${p.side === "buy" ? "up" : "down"}">${p.side === "buy" ? "▲" : "▼"}</span> <span class="muted">${p.side} ${p.volume}</span></span>
      <button class="btn xs" data-close="${p.ticket}">Close</button>
      <span class="num small muted">SL ${p.sl || "none"}  TP ${p.tp || "none"}</span>
      <span class="num small"><span class="pl ${p.profit >= 0 ? "up" : "down"}">${p.profit >= 0 ? "+" : ""}${fmt(p.profit)}</span> <span class="muted">from ${p.open}</span></span></div>`).join(""));
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
/* ---------- stage ladder: Paper -> Demo -> Real 2 -> Real 5 -> Real full ---------- */
state.progress = null; state.confirmReal = false;
async function loadProgress() {
  let p;
  try { p = await api("/api/progress"); } catch (e) { return; }
  const prevStage = state.progress?.stage?.id;
  state.progress = p; state.mode = p.stage.mode;
  if (p.event?.type === "promoted") { toast(`The bot moved up to ${p.event.to}.`); playEvent("promoted"); }
  if (p.event?.type === "demoted") { toast(`Drawdown limit hit. The bot moved back to ${p.event.to}.`, true); playEvent("demoted"); }
  if (prevStage && prevStage !== p.stage.id) loadPlan();
  const idx = p.stages.findIndex(x => x.id === p.stage.id);
  const lock = `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>`;
  const c0 = p.checks[0], prog = c0 && typeof c0.value === "number" && c0.target ? Math.min(100, 100 * c0.value / c0.target) : 0;
  setHTML($("#ladder"), p.stages.map((x, i) => {
    const sub = i < idx ? "passed" : i === idx ? (c0 ? `now · ${c0.value} / ${c0.target} ${c0.name.toLowerCase()}` : "now") : x.mode === "real" ? "real money" : "next";
    return `<li class="${i < idx ? "done" : i === idx ? "current" : ""} ${x.mode === "real" ? "real" : ""}" title="${x.note}"${i === idx + 1 ? ` style="--prog:${prog.toFixed(0)}%"` : ""}>
      <i class="dot">${i < idx ? "✓" : x.mode === "real" && i > idx ? lock : i + 1}</i><span><b>${x.label}</b><small>${sub}</small></span></li>`;
  }).join(""));
  const rows = p.checks.map(c => {
    const v = typeof c.value === "number" ? c.value : c.target * 2;
    const pct = c.limit ? Math.min(100, (v / (c.target || 1)) * 100) : Math.min(100, c.target ? (v / c.target) * 100 : 100);
    return `<div class="check-row ${c.ok ? "ok" : c.limit ? "bad" : ""}"><span>${c.name}</span><span class="num">${c.value} ${c.limit ? "/ max " : "/ "}${c.target}${c.ok ? " ✓" : ""}</span><div class="track"><i style="width:${pct}%"></i></div></div>`;
  }).join("");
  const nxt = p.next;
  let action = "";
  if (!nxt) action = `<span class="muted small">Top stage. Keep an eye on the drawdown limit.</span>`;
  else if (p.eligible && p.needs_approval) action = state.confirmReal
      ? `<span class="small">Type REAL to move to <b>${nxt.label}</b>:</span><input id="real-confirm" autocomplete="off"><button class="btn primary" id="promote-go">Move to real money</button><button class="btn" id="promote-cancel">Cancel</button>`
      : `<button class="btn primary" id="promote">Promote to ${nxt.label}</button><span class="muted small">Passed. Real money needs your OK.</span>`;
  else if (p.eligible) action = `<button class="btn primary" id="promote">Promote to ${nxt.label}</button>`;
  else action = `<span class="muted small">Next: ${nxt.label}${nxt.id === "demo" && state.settings?.auto_promote_demo ? " (automatic when every check is green)" : nxt.mode === "real" ? " (needs your OK when every check is green)" : ""}</span>`;
  setHTML($("#gate"), `<div class="panel-head"><h3>${p.stage.label} gate</h3><span class="muted small">${nxt ? `then ${nxt.label}` : "top stage"}</span></div>
    <p class="muted small" style="margin:0 0 6px">${p.stage.note} · since ${p.since.replace("T", " ").slice(0, 16)} UTC</p>${rows}
    <div class="actions">${action}${idx > 0 ? `<button class="btn xs" id="demote">Move back a stage</button>` : ""}</div>`);
  renderLearned(p.learned);
}
$("#gate").addEventListener("click", async e => {
  const id = e.target.id;
  try {
    if (id === "promote") {
      if (state.progress.needs_approval) { state.confirmReal = true; return loadProgress(); }
      await api("/api/progress/promote", { method: "POST", body: {} }); toast("Promoted."); loadProgress();
    } else if (id === "promote-go") {
      await api("/api/progress/promote", { method: "POST", body: { confirm: $("#real-confirm").value.trim() } });
      state.confirmReal = false; toast("Moved to real money. Start small and watch it."); loadProgress();
    } else if (id === "promote-cancel") { state.confirmReal = false; loadProgress(); }
    else if (id === "demote") { await api("/api/progress/demote", { method: "POST" }); toast("Moved back a stage."); loadProgress(); }
  } catch (err) { toast(err.message, true); }
});
function renderLearned(r) {
  if (!r || (!r.generated && !r.latest_lesson)) return;
  const chips = [...(r.blocked_hours || []).map(h => `skip ${String(h).padStart(2, "0")}:00 UTC`),
    ...(r.min_confidence ? [`confidence ≥ ${r.min_confidence}`] : []), ...(r.disabled_side ? [`no ${r.disabled_side} trades`] : []),
    ...(r.blocked_setups || []).map(k => `skip ${state.bot.data?.setup_names?.[k] || k}`)];
  const names = state.bot.data?.setup_names || {};
  const lesson = r.latest_lesson ? `<div class="lesson"><b>Latest lesson</b><span class="muted small">${(r.latest_lesson_utc || "").replace("T", " ").slice(5, 16)} UTC${r.mistakes ? `, lesson ${r.mistakes}` : ""}</span><p>${r.latest_lesson}</p></div>` : "";
  const cautions = (r.cautions || []).length ? `<div class="learned-rules">${r.cautions.map(c => `<span class="rule-chip caution" title="${(c.why || "").replace(/"/g, "&quot;")}">${c.side === "buy" ? "▲" : "▼"} ${names[c.setup] || c.setup}: needs ${Math.round(c.min_prob * 100)}% until ${(c.until_utc || c.until || "").replace("T", " ").slice(5, 16)}</span>`).join("")}</div>` : "";
  $("#learned").innerHTML = lesson + cautions + `<div class="learned-rules">${chips.length ? chips.map(c => `<span class="rule-chip">${c}</span>`).join("") : `<span class="muted small">No filters yet. Nothing has lost consistently enough to block.</span>`}</div>
    <p class="muted small" style="margin:0">From ${r.trades_analyzed} closed trades · updated ${r.generated.replace("T", " ")} UTC · ${state.settings?.use_learned ? "applied to new entries" : "not applied (Settings)"} · saved to <code>.claude/skills/m1-bot-lessons/</code></p>
    ${(r.reasons || []).length ? `<ul class="small muted" style="margin:6px 0 0;padding-left:18px">${r.reasons.map(x => `<li>${x}</li>`).join("")}</ul>` : ""}`;
}
$("#learn-now").onclick = async () => { try { const r = await api("/api/learn", { method: "POST" }); renderLearned(r.rules); toast("Lessons updated from the bot's trades."); } catch (e) { toast(e.message, true); } };

async function loadPlan() {
  const box = $("#plan");
  let p;
  try { p = await api(`/api/plan?mode=${state.mode === "paper" ? "paper" : state.mode}`); }
  catch (e) { setHTML(box, `<div class="panel-head"><h3>Each trade right now</h3></div><p class="empty">${e.status === 503 ? "Open MT5 to see the per-trade plan." : e.message}</p>`); return; }
  const c = p.currency || "", d = p.digits ?? 2, money = v => `${fmt(v)} ${c}`;
  const cell = (label, val, wide) => `<div class="${wide ? "wide" : ""}"><span>${label}</span><strong>${val}</strong></div>`;
  setHTML(box, `<div class="panel-head"><h3>Each ${p.symbol} trade right now</h3><span class="muted small">${p.mode} · 1:${p.leverage}</span></div><div class="plan-grid">
    ${cell("Balance", money(p.balance))}${cell("Leverage", p.ref_leverage ? `1:${p.leverage} real · exits at 1:${p.ref_leverage}` : `1:${p.leverage}`)}
    ${cell("Stake (margin)", money(p.stake))}${cell("Lots", p.lots)}
    ${cell(`Stop: −${p.sl_pct}% of stake`, `−${money(p.sl_money)}<small>${Number(p.sl_dist).toFixed(d)} from entry</small>`)}
    ${cell(`Target: +${p.tp_pct}% of stake`, `+${money(p.tp_money)}<small>${Number(p.tp_dist).toFixed(d)} from entry</small>`)}
    ${cell("Reward : risk", `${p.reward_risk} : 1`)}${cell("TP scale (200% → 50%)", `${money(p.tp_scale[0])} → ${money(p.tp_scale[1])} stake`)}${cell("Spread now", Number(p.spread_px).toFixed(d))}${cell("Margin for 1.00 lot", money(p.margin_per_lot))}
    ${cell(`If all ${state.settings.max_open_trades} open trades stop out`, `−${money(p.worst_case_all_open)} (${p.worst_case_pct}% of balance)`, true)}</div>
    ${p.forced_min ? `<p class="plan-note warn">${state.settings.stake_pct}% of balance is ${money(p.stake_target)}, below the ${p.volume_min}-lot minimum, so each trade uses the minimum lot (stake ${money(p.stake)}).</p>` : ""}
    ${p.worst_case_pct > 5 ? `<p class="plan-note warn">That worst case is more than 5% of the balance. Consider fewer open trades or a larger balance.</p>` : ""}
    ${p.spread_px > p.sl_dist * 0.35 ? `<p class="plan-note warn">The spread is over 35% of the stop distance right now, so the bot will skip entries until it narrows.</p>` : ""}`);
}
function bindSlider(id, key, suffix, digits) {
  const el = $(id), txt = $(`${id}-txt`);
  el.value = state.settings[key]; txt.textContent = `${Number(el.value).toFixed(digits)}${suffix}`;
  el.oninput = () => txt.textContent = `${Number(el.value).toFixed(digits)}${suffix}`;
  el.onchange = () => api("/api/settings", { method: "POST", body: { [key]: parseFloat(el.value) } });
}
$("#agent-start").onclick = async () => {
  const msg = $("#agent-msg"); msg.className = "note";
  if (state.mode === "real" && !confirm(`Start the agent at ${state.progress?.stage?.label}? It will place REAL-money orders.`)) return;
  try { await api("/api/agent/start", { method: "POST", body: {} }); msg.textContent = `Started at the ${state.progress?.stage?.label || state.mode} stage. It acts when the next M1 candle closes.`; pollStatus(); openLog(); }
  catch (e) { msg.textContent = e.message; msg.className = "note err"; }
};
$("#agent-stop").onclick = async () => { await api("/api/agent/stop", { method: "POST" }); $("#agent-msg").textContent = "Stopped. Any open position keeps its server-side stop loss and take profit."; pollStatus(); };
// console panels show a small "nothing yet" card until their job has written something
function showLog(which, log, stickToEnd) {
  if (!log || !log.trim()) return;
  const pre = $(`#${which}-log`); $(`#${which}-empty`).hidden = true; pre.hidden = false;
  if (pre.textContent === log) return;
  if (which === "agent" && !$("#log-drawer").classList.contains("open")) $("#log-toggle .log-dot").hidden = false;   // new lines while it's closed
  const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
  pre.textContent = log;
  if (!stickToEnd || atEnd) pre.scrollTop = pre.scrollHeight;
}
/* live log: a drawer over the page, opened from the Agent control bar */
function openLog() { $("#log-drawer").classList.add("open"); $("#log-toggle").setAttribute("aria-expanded", "true"); $("#log-toggle .log-dot").hidden = true; pollAgentLog(); }
function closeLog() { $("#log-drawer")?.classList.remove("open"); $("#log-toggle")?.setAttribute("aria-expanded", "false"); }
$("#log-toggle").onclick = () => $("#log-drawer").classList.contains("open") ? closeLog() : openLog();
$("#log-close").onclick = closeLog;
async function pollAgentLog() {
  try { const r = await api("/api/jobs/agent/log?lines=300"); showLog("agent", r.log, true); } catch (e) {}
}
async function loadJournal() {
  try {
    const rows = await api("/api/journal?limit=200"), last = state.journalLast;
    state.journalLast = rows.reduce((mx, r) => (r.time_utc || "") > mx ? r.time_utc : mx, last || "");
    setHTML($("#journal tbody"), rows.reverse().map(r => `<tr${last != null && (r.time_utc || "") > last ? ` class="enter"` : ""}><td>${(r.time_utc || "").replace("T", " ").slice(0, 19)}</td><td>${r.mode}</td>
      <td class="ev-${r.event}">${r.event}</td><td class="${r.side === "buy" ? "up" : r.side === "sell" ? "down" : ""}">${r.side ? (r.side === "buy" ? "▲ " : "▼ ") + r.side : ""}</td><td>${r.lots || ""}</td><td>${r.price ? Number(r.price).toFixed(state.digits) : ""}</td>
      <td>${r.sl ? Number(r.sl).toFixed(state.digits) : ""}</td><td>${r.tp ? Number(r.tp).toFixed(state.digits) : ""}</td><td>${r.prob || ""}</td><td>${r.note || ""}</td></tr>`).join("")
      || `<tr><td colspan="10" class="muted">No entries yet. Start the agent in Paper mode and signals will be logged as candles close.</td></tr>`);
  } catch (e) {}
}

/* ---------- train ---------- */
let lastTrainJob = "train";
$("#btn-fetch").onclick = async () => { try { await api("/api/fetch", { method: "POST" }); lastTrainJob = "fetch"; showLog("train", "Starting the download…"); pollTrainLog(); pollStatus(); } catch (e) { toast(e.message, true); } };
$("#btn-history").onclick = async () => { try { await api("/api/history/download", { method: "POST", body: JSON.stringify({ years: +$("#hist-years").value }) }); lastTrainJob = "history"; showLog("train", "Starting the history download…"); pollTrainLog(); pollStatus(); } catch (e) { toast(e.message, true); } };
$("#btn-train").onclick = async () => { try { await api("/api/train", { method: "POST" }); lastTrainJob = "train"; showLog("train", "Starting training…"); pollTrainLog(); pollStatus(); } catch (e) { toast(e.message, true); } };
async function pollTrainLog() {
  try { const r = await api(`/api/jobs/${lastTrainJob}/log?lines=400`); showLog("train", r.log, false); } catch (e) {}
}

/* ---------- Hermes chat ---------- */
const BACKEND_NAME = { hermes_agent: "Hermes Agent", local: "Local model" };
function addMsg(role, text, tools, animate = false, backend = null) {
  const d = document.createElement("div"); d.className = `msg ${role}${animate ? " enter" : ""}`; d.textContent = text;
  if ((tools && tools.length) || backend) {
    const t = document.createElement("div"); t.className = "tools";
    if (backend) { const b = document.createElement("span"); b.className = `by ${backend}`; b.textContent = BACKEND_NAME[backend] || backend; t.appendChild(b); }
    if (tools && tools.length) t.append(`used: ${tools.map(x => x.tool).join(", ")}`);
    d.appendChild(t);
  }
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
  $("#suggest").classList.add("hidden"); $("#chat-intro").classList.add("hidden"); addMsg("user", text, null, true);
  const agent = whoAnswers() === "hermes_agent", pending = addMsg("assistant pending", agent ? "Hermes Agent is working" : "Thinking", null, true), t0 = Date.now();
  const tick = setInterval(() => {                // Hermes Agent tasks can take minutes: show that it's still going
    const sec = Math.round((Date.now() - t0) / 1000); if (sec < 8) return;
    pending.textContent = `${agent ? "Hermes Agent is still working" : "Still thinking"} (${sec < 60 ? `${sec} s` : `${Math.floor(sec / 60)} min ${sec % 60} s`})${agent && sec >= 20 ? ". Agent tasks can take a few minutes." : ""}`;
  }, 1000);
  try {
    const r = await api("/api/chat", { method: "POST", body: { text } }); pending.remove(); addMsg("assistant", r.reply, r.tools, true, r.backend); loadFacts();
    if (state.tab !== "chat" || document.hidden) playEvent("hermes");
    if ((r.reply || "").startsWith("⚠")) brainStatus();       // set-up messages: refresh the status line
  }
  catch (e) { pending.remove(); addMsg("assistant", `Couldn't reach the assistant: ${e.message}`, null, true); }
  clearInterval(tick);
}
$("#chat-form").onsubmit = e => { e.preventDefault(); const i = $("#chat-input"); const t = i.value; i.value = ""; i.style.height = ""; send(t); };
$("#chat-input").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chat-form").requestSubmit(); } });
$("#chat-input").addEventListener("input", e => { e.target.style.height = "auto"; e.target.style.height = e.target.scrollHeight + "px"; });
$$("#suggest button").forEach(b => b.onclick = () => send(b.textContent));
// status pill + next step + Set up button; the local model can install/start/download itself (backend by Chat A)
const LOCAL_TEXT = { not_installed: "Ollama not installed", stopped: "Ollama not running", no_model: "Model not downloaded", error: "Set-up problem", starting: "Starting Ollama…" };
/* which one answers the next message: the Hermes Agent app when it's up (or forced), else the small local model */
function whoAnswers(s = state.brain) {
  if (!s) return null;
  const agentUp = s.agent ? s.agent === "ready" : s.hermes_agent;
  return s.backend_setting === "hermes_agent" || (s.backend_setting === "auto" && agentUp) ? "hermes_agent" : "local";
}
async function brainStatus() {
  let s; try { s = await api("/api/assistant/status"); } catch (e) { return; }
  state.brain = s;
  const el = $("#brain-state"), next = $("#brain-next"), setup = $("#brain-setup");
  const useAgent = whoAnswers(s) === "hermes_agent", agentUp = s.agent ? s.agent === "ready" : s.hermes_agent;
  const agentBusy = s.agent === "starting", agentFix = ["stopped", "error"].includes(s.agent) && s.backend_setting !== "local";
  const localReady = s.local ? s.local === "ready" : s.ollama;
  const which = $("#brain-which"); which.hidden = !s.agent; which.textContent = useAgent ? "Hermes Agent" : "Local model";
  which.className = `by ${useAgent ? "hermes_agent" : "local"}`;
  which.title = useAgent ? "Replies come from the Hermes Agent app in WSL" : `Replies come from the small local model${s.agent && s.agent !== "off" && s.agent !== "ready" ? " until Hermes Agent is running" : ""}`;
  let text, live = false;
  if (useAgent && agentUp) { text = "Hermes Agent · ready"; live = true; }
  else if (agentBusy && s.backend_setting !== "local") text = "Starting Hermes Agent…";
  else if (useAgent) text = "Hermes Agent not running";
  else if (localReady) { text = `${s.model} on ${s.device || "GPU"}`; live = true; }
  else if (s.installing) text = "Installing Ollama…";
  else if (s.local === "downloading") text = `Downloading ${Math.round((s.download_pct || 0) * 100)}%`;
  else text = LOCAL_TEXT[s.local] || "Ollama not running";
  setHTML(el, live ? `<span class="live-dot"></span>${text}` : text);
  el.className = "pill " + (live ? "live" : "warn");
  const step = s.agent_step && s.backend_setting !== "local" && s.agent !== "off" && !agentUp ? s.agent_step : !live && s.next_step ? s.next_step : "";
  if (next.textContent !== step) next.textContent = step;
  next.hidden = !step;
  setup.hidden = !agentFix && (useAgent || s.installing || !["not_installed", "stopped", "no_model", "error"].includes(s.local));
  const dl = s.local === "downloading" && !useAgent;
  $("#brain-dl").hidden = !dl; if (dl) $("#brain-bar").style.width = `${Math.round((s.download_pct || 0) * 100)}%`;
  clearTimeout(state.brainT);                    // poll faster while it is busy setting itself up
  if (agentBusy || (!useAgent && (s.installing || ["downloading", "starting"].includes(s.local)))) state.brainT = setTimeout(brainStatus, 2000);
}
$("#brain-setup").onclick = async () => {
  const b = $("#brain-setup"); b.disabled = true; b.textContent = "Setting up…";
  try { const r = await api("/api/assistant/setup", { method: "POST", body: {} }); if (r.note) toast(r.note); }
  catch (e) { toast(e.message, true); }
  b.disabled = false; b.textContent = "Set up"; brainStatus();
};
async function loadFacts() {
  try {
    const f = await api("/api/memory"), max = state.factMax;
    state.factMax = f.reduce((mx, x) => Math.max(mx, x.id), max ?? 0);
    $("#fact-count").textContent = f.length ? `${f.length} saved` : "";
    setHTML($("#facts"), f.map(x => `<li${max != null && x.id > max ? ` class="enter"` : ""}><span>${x.text.replace(/</g, "&lt;")}</span><button title="Forget" data-forget="${x.id}">×</button></li>`).join("")
      || `<li class="muted">Nothing yet. Try "Remember my broker is on GMT+3" or "Remember I only trade the London–New York overlap".</li>`);
  } catch (e) {}
}
$("#facts").addEventListener("click", async e => { const b = e.target.closest("[data-forget]"); if (!b) return; await api(`/api/memory/${b.dataset.forget}`, { method: "DELETE" }); loadFacts(); });
$("#fact-form").onsubmit = async e => { e.preventDefault(); const i = $("#fact-input"); if (!i.value.trim()) return; await api("/api/memory", { method: "POST", body: { text: i.value } }); i.value = ""; loadFacts(); };

/* ---------- settings ---------- */
function fillSettings() {
  const f = $("#settings-form"), s = state.settings;
  for (const el of f.elements) {
    if (!el.name) continue;
    const known = el.name in s; el.disabled = !known;          // a setting the backend doesn't have yet waits for it
    el.closest("label")?.classList.toggle("waiting", !known);
    if (!known) { el.closest("label") && (el.closest("label").title = "Waits for its backend (Chat A is building it)"); continue; }
    if (el.type === "checkbox") el.checked = !!s[el.name];
    else el.value = Array.isArray(s[el.name]) ? s[el.name].join(el.tagName === "TEXTAREA" ? "\n" : ", ") : s[el.name];
  }
}
/* settings: every field is compared with the saved settings; the save bar names what changed */
function formValues() {
  const body = {};
  for (const el of $("#settings-form").elements) {
    if (!el.name || el.disabled) continue;
    if (el.type === "checkbox") body[el.name] = el.checked;
    else if (el.name === "symbols_watch") body[el.name] = el.value.split(",").map(x => x.trim()).filter(Boolean);
    else if (el.name === "web_sites") body[el.name] = el.value.split(/[\n,]+/).map(x => x.trim()).filter(Boolean);
    else if (el.type === "number") body[el.name] = parseFloat(el.value);
    else body[el.name] = el.value.trim();
  }
  return body;
}
const sameVal = (a, b) => Array.isArray(a) || Array.isArray(b) ? String(a ?? "") === String(b ?? "")
  : typeof a === "number" || typeof b === "number" ? Number(a) === Number(b) || (Number.isNaN(Number(a)) && Number.isNaN(Number(b)))
  : (a ?? "") === (b ?? "");
const RETRAIN = new Set(["sl_pct_of_stake", "tp_pct_small", "tp_pct_large", "small_stake", "large_stake", "label_horizon", "ref_leverage"]);
function labelOf(el) {
  const l = el.closest("label"); if (!l) return el.name;
  const txt = l.classList.contains("check") ? l.textContent : [...l.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(" ");
  return txt.replace(/\s+/g, " ").trim();
}
function updateDirty() {
  if (!state.settings) return;
  const body = formValues(), s = state.settings, changed = [];
  for (const el of $("#settings-form").elements) {
    if (!el.name || el.disabled) continue;
    const dirty = !sameVal(body[el.name], s[el.name]);
    el.closest("label")?.classList.toggle("changed", dirty);
    if (dirty) changed.push(el);
  }
  $$("#set-nav a").forEach(a => a.classList.toggle("dirty", changed.some(el => el.closest("fieldset")?.id === a.getAttribute("href").slice(1))));
  $("#savebar").classList.toggle("is-dirty", changed.length > 0);
  $("#set-save").disabled = $("#set-discard").disabled = !changed.length;
  const txt = $("#set-dirty-txt");
  if (!changed.length) { txt.textContent = "All changes saved"; return; }
  const show = (el, v) => el.type === "password" ? "••••" : Array.isArray(v) ? v.join(", ") : typeof v === "boolean" ? (v ? "on" : "off") : v === "" || v == null || Number.isNaN(v) ? "empty" : v;
  const one = changed[0];
  const what = changed.length === 1 ? `${labelOf(one)}: ${show(one, s[one.name])} → ${show(one, body[one.name])}`
    : changed.slice(0, 3).map(labelOf).join(", ") + (changed.length > 3 ? ` and ${changed.length - 3} more` : "");
  txt.textContent = `${changed.length} unsaved change${changed.length > 1 ? "s" : ""} · ${what}${changed.some(el => RETRAIN.has(el.name)) ? " · retrain after saving" : ""}`;
}
$("#settings-form").addEventListener("input", updateDirty);
$("#settings-form").addEventListener("change", updateDirty);
$("#set-discard").onclick = () => { fillSettings(); updateDirty(); };
$("#settings-form").onsubmit = async e => {
  e.preventDefault();
  const body = formValues(), msg = $("#settings-msg");
  try { state.settings = await api("/api/settings", { method: "POST", body }); msg.textContent = "Saved to data/settings.json"; initFromSettings(true); brainStatus(); loadPlan(); }
  catch (err) { msg.textContent = err.message; }
  updateDirty();
  if (msg.animate && motionOK()) msg.animate([{ opacity: 0, transform: "translateX(-4px)" }, { opacity: 1, transform: "none" }], { duration: 260, easing: "cubic-bezier(.22,1,.36,1)" });
};
// section menu: click to jump, and the menu follows as you scroll
let navLock = 0;                                 // a clicked section stays highlighted while the page glides to it
$$("#set-nav a").forEach(a => a.onclick = e => {
  e.preventDefault(); navLock = Date.now() + 1200;
  $(a.getAttribute("href"))?.scrollIntoView({ behavior: motionOK() ? "smooth" : "auto", block: "start" });
  $$("#set-nav a").forEach(x => x.classList.toggle("on", x === a));
});
(() => {
  const seen = new Set(), sections = $$("#settings-form fieldset");
  const spy = new IntersectionObserver(entries => {
    entries.forEach(en => en.isIntersecting ? seen.add(en.target.id) : seen.delete(en.target.id));
    if (Date.now() < navLock) return;
    const m = $("main"), atEnd = m.scrollTop + m.clientHeight >= m.scrollHeight - 4;   // bottom reached: the last visible one
    const vis = sections.filter(f => seen.has(f.id)), top = atEnd ? vis[vis.length - 1] : vis[0]; if (!top) return;
    $$("#set-nav a").forEach(x => x.classList.toggle("on", x.getAttribute("href") === `#${top.id}`));
  }, { root: $("main"), rootMargin: "0px 0px -55% 0px" });
  sections.forEach(f => spy.observe(f));
})();
// Settings > Display: this-PC-only preferences (kept in the window's local storage, never sent to the server)
(() => {
  const el = $("#pref-motion"); el.checked = document.documentElement.classList.contains("reduce-motion");
  el.onchange = () => { document.documentElement.classList.toggle("reduce-motion", el.checked); try { localStorage.setItem("reduceMotion", el.checked ? "1" : "0"); } catch (e) {} };
  const ss = $("#pref-sessions"); ss.checked = state.showSessions; ss.onchange = () => setShowSessions(ss.checked);
})();


function initFromSettings(keepSymbol = false) {
  const s = state.settings;
  if (!keepSymbol || !(s.symbols_watch || []).includes(state.symbol)) state.symbol = s.symbols_watch?.[0] || s.symbol;
  renderChips(); fillSettings();
  bindSlider("#thr", "threshold", "", 2); bindSlider("#stake", "stake_pct", "% of balance", 2);
  if (!initFromSettings.bound) { $("#stake").addEventListener("change", () => setTimeout(loadPlan, 300)); initFromSettings.bound = true; }
  $$(".sym-txt").forEach(x => x.textContent = s.symbol); $("#days-txt").textContent = s.days_history;
  loadBars(); updateDirty(); syncSaved();
}

/* ---------- manual trading (UI by Chat B; the /api/manual/* backend is specced for Chat A in TWO_CHATS.md) ----------
   Watching prices and closing positions work today through /api/bars and /api/positions/{ticket}/close. Placing,
   editing and pending orders switch on by themselves once /api/manual/* answers. */
const man = { symbol: null, backend: null, spec: null, q: null, type: "market", arm: null, owner: "any", pos: [], editing: null, realSession: false, tick: 0,
              auto: null, priceAt: 0, feedErr: null, blocked: null, drag: null, holding: null };
const BULK_LABEL = { profit: "Close profitable", loss: "Close negative", buys: "Close buys", sells: "Close sells", all: "Close all" };
const volStep = () => man.spec?.volume_step || 0.01;
const volDec = () => Math.max(0, Math.round(-Math.log10(volStep())));
const isReal = () => $("#acct-mode").classList.contains("real");
function setPrice(el, v, d) { const prev = el._v; el._v = v; el.textContent = fmt(v, d); if (prev != null && v !== prev) flash(el, v > prev ? 1 : -1); }
function manSymbols() {
  const list = state.settings?.symbols_watch || []; if (!man.symbol) man.symbol = state.symbol || list[0];
  setHTML($("#man-symbols"), list.map(s => `<button class="chip${s === man.symbol ? " active" : ""}" data-sym="${s}" type="button">${s}</button>`).join(""));
}
function manPick(sym) {
  if (!sym || sym === man.symbol) return;
  man.symbol = sym; man.spec = null; man.q = null; man.priceAt = Date.now(); $("#man-bid")._v = $("#man-ask")._v = null;
  $("#man-price").value = ""; man.lineSig = ""; disarm(); manSymbols(); loadManBars(); loadManQuote(); loadManQuotes();
}
async function probeManual() {
  if (man.backend !== null) return;
  try { await api(`/api/manual/quote?symbol=${encodeURIComponent(man.symbol)}`); man.backend = true; }
  catch (e) { man.backend = e.status !== 404; }         // 404 = not built yet; anything else (MT5 closed) means it exists
  $("#man-backend").hidden = man.backend;
  if (man.backend) await loadManAuto(true);
  $$("#man-buy, #man-sell").forEach(b => b.title = man.backend ? "" : "Placing orders needs the manual-trading backend (Chat A is building it)");
}
async function loadManQuote() {
  if (!man.symbol) return;
  let q = null;
  if (man.backend) { try { q = await api(`/api/manual/quote?symbol=${encodeURIComponent(man.symbol)}`); } catch (e) { if (e.status === 404) { man.backend = false; $("#man-backend").hidden = false; } } }
  man.quoteOk = !!q;
  if (!q) return;                                 // no quote: loadManBars fills it from the candles it fetches
  applyManQuote(q);
}
function applyManQuote(q) {
  if (q.symbol !== man.symbol) return;
  if (!man.q || man.q.bid !== q.bid || man.q.ask !== q.ask) man.priceAt = Date.now();
  man.q = q; if (q.volume_step) man.spec = q;
  $("#man-msg").textContent = "";
  setPrice($("#man-bid"), q.bid, q.digits); setPrice($("#man-ask"), q.ask, q.digits);
  $("#man-spread").textContent = Math.round((q.ask - q.bid) / q.point);
  $("#man-sym").textContent = q.symbol;
  updateRisk(); updatePriceHint(); updateLevels(); drawManLines(); renderConn();
}
/* take profit / stop loss: always a fixed number of points from the price (160 above, 80 below by default; editable,
   remembered on this PC). For a sell they flip: take profit below, stop loss above. */
const TPSL = (() => { try { return JSON.parse(localStorage.getItem("manTPSL")) || { tp: 160, sl: 80 }; } catch (e) { return { tp: 160, sl: 80 }; } })();
function levelsFor(side) {
  const q = man.q; if (!q) return null;
  const pt = q.point, tp = (+$("#man-tp-pts").value || 0) * pt, sl = (+$("#man-sl-pts").value || 0) * pt;
  const entry = man.type === "market" ? (side === "buy" ? q.ask : q.bid) : parseFloat($("#man-price").value) || (side === "buy" ? q.ask : q.bid);
  const r = v => +v.toFixed(q.digits);
  return side === "buy" ? { entry: r(entry), tp: r(entry + tp), sl: r(entry - sl) } : { entry: r(entry), tp: r(entry - tp), sl: r(entry + sl) };
}
function updateLevels() {
  const q = man.q; if (!q) return;
  setHTML($("#man-levels tbody"), ["buy", "sell"].map(s => { const L = levelsFor(s);
    return `<tr><td class="${s === "buy" ? "up" : "down"}">${s === "buy" ? "▲ Buy" : "▼ Sell"}</td><td class="num">${fmt(L.entry, q.digits)}</td><td class="num up">${fmt(L.tp, q.digits)}</td><td class="num down">${fmt(L.sl, q.digits)}</td></tr>`; }).join(""));
}
["#man-tp-pts", "#man-sl-pts"].forEach(s => $(s).addEventListener("input", () => {
  TPSL.tp = +$("#man-tp-pts").value || 160; TPSL.sl = +$("#man-sl-pts").value || 80;
  try { localStorage.setItem("manTPSL", JSON.stringify(TPSL)); } catch (e) {}
  updateLevels(); updateRisk(); drawManLines(); disarm();
}));
$("#man-tp-pts").value = TPSL.tp; $("#man-sl-pts").value = TPSL.sl;
/* the Manual tab's own chart: candles for the symbol you trade, your open positions, and a preview of where the take
   profit and stop loss land while you hover Buy or Sell */
function manChart() {
  if (man.chart || !window.LightweightCharts) return;
  man.chart = LightweightCharts.createChart($("#man-chart"), {
    autoSize: true, layout: { background: { color: "transparent" }, textColor: "#8c9098", fontFamily: "IBM Plex Mono, monospace", fontSize: 11 },
    grid: { vertLines: { color: "rgba(255,255,255,.035)" }, horzLines: { color: "rgba(255,255,255,.035)" } },
    rightPriceScale: { borderColor: "#262c34" }, timeScale: { borderColor: "#262c34", timeVisible: true, secondsVisible: false, rightOffset: 6 },
    crosshair: { mode: 0 }, localization: { locale: "en-US" },
  });
  man.series = man.chart.addCandlestickSeries({ upColor: "#3fb68b", downColor: "#e0574f", borderVisible: false, wickUpColor: "#3fb68b", wickDownColor: "#e0574f" });
  $("#man-chart").addEventListener("dblclick", () => { man.chart.priceScale("right").applyOptions({ autoScale: true }); man.chart.timeScale().scrollToRealTime(); });
}
async function loadManBars() {
  manChart(); if (!man.series || !man.symbol) return;
  const sym = man.symbol, full = man.barsSym !== sym;
  let d; try { d = await api(`/api/bars?symbol=${encodeURIComponent(sym)}&count=${full ? 300 : 3}`); }
  catch (e) { man.feedErr = e.status === 503 ? "MT5 is closed" : "No price feed"; $("#man-msg").textContent = e.status === 503 ? "Open MT5 to trade." : e.message; renderConn(); return; }
  man.feedErr = null;
  if (sym !== man.symbol) return;
  if (!man.backend || !man.quoteOk) applyManQuote({ ...(man.q?.symbol === d.symbol ? man.q : {}), symbol: d.symbol, bid: d.bid, ask: d.ask, digits: d.digits, point: d.point });
  const bars = d.bars.map(pickBar);
  if (full || (bars.length && bars[0].time > man.lastBar + 60)) {
    if (!full) return (man.barsSym = null, loadManBars());     // candles were missed: reload
    man.series.applyOptions({ priceFormat: { type: "price", precision: d.digits, minMove: d.point } });
    man.series.setData(bars); man.barsSym = sym; man.lastBar = bars.length ? bars[bars.length - 1].time : 0;
    man.chart.timeScale().scrollToRealTime(); man.lineSig = "";
  } else for (const b of bars) if (b.time >= man.lastBar) { man.series.update(b); man.lastBar = b.time; }
  drawManLines();
}
function drawManLines() {
  const q = man.q; if (!man.series || !q || man.drag) return;      // never rebuild a line while it's being dragged
  const want = [];
  man.pos.filter(p => p.symbol === man.symbol).forEach(p => {
    want.push([p.open, p.owner === "bot" ? "#89cff0" : "#c9a24a", `${p.owner === "bot" ? "bot" : "you"} ${p.side} ${p.volume}`, 2]);
    const trail = man.auto?.tickets?.[p.ticket]?.trail_points ? " trail" : "";
    if (p.sl) want.push([p.sl, "#e0574f", `SL${trail}`, 0, { ticket: p.ticket, kind: "sl" }]);
    if (p.tp) want.push([p.tp, "#3fb68b", "TP", 0, { ticket: p.ticket, kind: "tp" }]);
  });
  if (man.preview) { const L = levelsFor(man.preview); want.push([L.tp, "#3fb68b", `TP if you ${man.preview}`, 1], [L.sl, "#e0574f", `SL if you ${man.preview}`, 1]); }
  const sig = want.map(w => `${w[0].toFixed(q.digits)}${w[2]}`).join("|");
  if (sig === man.lineSig) return; man.lineSig = sig;
  (man.lines || []).forEach(l => man.series.removePriceLine(l.line));
  man.lines = want.map(([price, color, title, lineStyle, meta]) => ({ price, meta, color, title,
    line: man.series.createPriceLine({ price, color, lineWidth: meta ? 2 : 1, lineStyle, axisLabelVisible: true, title }) }));
}
["buy", "sell"].forEach(s => {
  const b = $(`#man-${s}`);
  const on = () => { man.preview = s; drawManLines(); }, off = () => { if (man.preview === s) { man.preview = null; drawManLines(); } };
  b.addEventListener("mouseenter", on); b.addEventListener("focus", on); b.addEventListener("mouseleave", off); b.addEventListener("blur", off);
});
function orderText(side) { return `${side.toUpperCase()}${man.type === "market" ? "" : " " + man.type} ${(+$("#man-vol").value).toFixed(volDec())}`; }
function disarm() {
  if (!man.arm) return;
  clearTimeout(man.arm.t); $(`#man-${man.arm.side}`).classList.remove("armed"); $(`#man-${man.arm.side}-note`).textContent = ""; man.arm = null;
}
async function manTrade(side) {
  if (!man.backend) { toast("Placing orders needs the manual-trading backend. Chat A is building it from the spec in TWO_CHATS.md.", true); return; }
  if (man.blocked) { disarm(); toast(`Not sending: ${man.blocked.toLowerCase()}.`, true); return; }
  const oneClick = $("#man-oneclick").checked && (!isReal() || man.realSession);
  if (!oneClick && man.arm?.side !== side) {             // first click arms, the second sends
    disarm(); $(`#man-${side}`).classList.add("armed");
    $(`#man-${side}-note`).textContent = `click again: ${orderText(side)}${isReal() ? " · REAL money" : ""}`;
    man.arm = { side, t: setTimeout(disarm, 4000) }; return;
  }
  disarm();
  if (!(await realCheck())) return;
  const body = { symbol: man.symbol, side, type: man.type, volume: +$("#man-vol").value, deviation: +$("#man-dev").value || 20 };
  if (man.auto) Object.assign(body, { be_points: +$("#man-be-pts").value || 0, trail_points: +$("#man-trail-pts").value || 0 });
  if (man.type !== "market" && !parseFloat($("#man-price").value)) { toast("Set the price for the pending order.", true); return; }
  const L = levelsFor(side); if (!L) return;
  Object.assign(body, { sl: L.sl, tp: L.tp, sl_points: +$("#man-sl-pts").value, tp_points: +$("#man-tp-pts").value });
  if (man.type !== "market") {
    body.price = parseFloat($("#man-price").value); body.expiration = $("#man-exp").value;
    if (!body.price) { toast("Set the price for the pending order.", true); return; }
  }
  if (isReal()) body.confirm_real = true;
  const b = $(`#man-${side}`); b.disabled = true;
  try {
    const r = await api("/api/manual/order", { method: "POST", body });
    const d = man.q?.digits ?? 2, lv = r.ok && (r.sl || r.tp) ? `, TP ${fmt(r.tp, d)}, SL ${fmt(r.sl, d)}` : "";
    toast(r.ok ? `${orderText(side)} ${man.symbol} ${man.type === "market" ? `filled at ${fmt(r.price, d)}` : "placed"}${lv} · #${r.ticket}${r.note ? `. ${r.note}` : ""}` : `Order refused: ${r.comment}`, !r.ok || !!r.note);
    playEvent(r.ok ? "orderOk" : "orderFail");
  } catch (e) { toast(e.message, true); playEvent("orderFail"); }
  b.disabled = false; loadManPositions(); loadManOrders(); loadPositions();
}
$("#man-buy").onclick = () => manTrade("buy"); $("#man-sell").onclick = () => manTrade("sell");
$("#man-symbols").addEventListener("click", e => { const b = e.target.closest("[data-sym]"); if (b) manPick(b.dataset.sym); });
function setVol(v) {
  const s = volStep(), mn = man.spec?.volume_min || s, mx = man.spec?.volume_max || 100;
  $("#man-vol").value = Math.min(mx, Math.max(mn, Math.round(v / s) * s)).toFixed(volDec()); updateRisk(); disarm();
}
$$("[data-vol]").forEach(b => b.onclick = () => setVol(+$("#man-vol").value + (+b.dataset.vol) * volStep()));
$("#man-vol-presets").addEventListener("click", e => { const b = e.target.closest("[data-v]"); if (b) setVol(b.dataset.v === "min" ? (man.spec?.volume_min || volStep()) : +b.dataset.v); });
$("#man-vol").addEventListener("change", () => setVol(+$("#man-vol").value));
$("#man-type").addEventListener("click", e => {
  const b = e.target.closest("[data-type]"); if (!b) return;
  man.type = b.dataset.type; $$("#man-type .seg-opt").forEach(x => x.classList.toggle("on", x === b));
  $(".man-price").hidden = man.type === "market";
  if (man.type !== "market" && !$("#man-price").value && man.q) $("#man-price").value = ((man.q.bid + man.q.ask) / 2).toFixed(man.q.digits);
  updatePriceHint(); updateRisk(); updateLevels(); drawManLines(); disarm();
});
function updatePriceHint() {
  const q = man.q, h = $("#man-price-hint"); if (!q || man.type === "market") return;
  h.textContent = man.type === "limit" ? `A buy limit sits below ${fmt(q.ask, q.digits)}, a sell limit above ${fmt(q.bid, q.digits)}.`
    : `A buy stop sits above ${fmt(q.ask, q.digits)}, a sell stop below ${fmt(q.bid, q.digits)}.`;
}
function updateRisk() {
  const q = man.q, el = $("#man-risk-txt"); if (!q) return;
  const dist = (+$("#man-sl-pts").value || 0) * q.point, v = +$("#man-vol").value;
  const money = q.tick_value && q.tick_size ? dist / q.tick_size * q.tick_value * v : null;
  el.textContent = `Stop ${Math.round(dist / q.point).toLocaleString()} points away${money != null ? ` · risks ${fmt(money)}${state.acct?.currency ? " " + state.acct.currency : ""}` : ""}`;
}
$("#man-price").addEventListener("input", () => { updateRisk(); updatePriceHint(); updateLevels(); drawManLines(); disarm(); });
$("#man-size").onclick = async () => {
  const L = levelsFor("buy"); if (!L) return;
  const sl = L.sl, entry = L.entry;
  try {
    const r = await api(`/api/size?symbol=${encodeURIComponent(man.symbol)}&entry=${entry}&stop=${sl}&risk=${$("#man-risk").value}`);
    if (r.lots) { setVol(r.lots); toast(`${r.lots} lots risks ${fmt(r.risk_money)} of ${fmt(r.equity)}.`); }
    else toast(`Even the minimum lot risks more than ${$("#man-risk").value}% with that stop.`, true);
  } catch (e) { toast(e.message, true); }
};
(() => {                                         // one-click trading: remembered on this PC; on real money it asks once
  const el = $("#man-oneclick"); try { el.checked = localStorage.getItem("oneClick") === "1"; } catch (e) {}
  el.onchange = async () => {
    if (el.checked && isReal() && !(await realCheck())) { el.checked = false; return; }   // on real money: type REAL first
    try { localStorage.setItem("oneClick", el.checked ? "1" : "0"); } catch (e) {}
    disarm();
  };
})();
async function loadManPositions() {
  const tb = $("#man-pos tbody"), a = state.acct;
  if (a) setHTML($("#man-acct"), `<span>Balance <b>${fmt(a.balance)}</b></span><span>Equity <b>${fmt(a.equity)}</b></span><span>Margin <b>${fmt(a.margin)}</b></span><span>Free <b>${fmt(a.margin_free)}</b></span><span>Level <b>${a.margin_level ? Math.round(a.margin_level) + "%" : "–"}</b></span>`);
  let ps; try { ps = await getPositions(); } catch (e) { setHTML(tb, `<tr><td colspan="11" class="muted">${e.status === 503 ? "Open MT5 to see positions." : e.message}</td></tr>`); return; }
  man.pos = ps;
  const sel = ps.filter(p => man.owner === "any" || p.owner === man.owner);
  const groups = { profit: sel.filter(p => p.profit > 0), loss: sel.filter(p => p.profit < 0), buys: sel.filter(p => p.side === "buy"), sells: sel.filter(p => p.side === "sell"), all: sel };
  $$("[data-bulk]").forEach(b => {
    if (b.classList.contains("armed")) return;
    const g = groups[b.dataset.bulk], sum = g.reduce((s, p) => s + p.profit, 0);
    setHTML(b, `${BULK_LABEL[b.dataset.bulk]}<span class="cnt">${g.length}${g.length ? ` · ${signed(sum)}` : ""}</span>`); b.disabled = !g.length;
  });
  const net = sel.reduce((s, p) => s + p.profit, 0);
  setHTML($("#man-open-sum"), sel.length ? `${sel.length} open, net <b class="num ${cls(net)}">${signed(net)}</b>` : "");
  const real = isReal();
  if (man.holding == null) setHTML($("#man-open"), sel.map(p => `<span class="tchip ${p.profit >= 0 ? "pos" : "neg"}${man.chipArm === p.ticket ? " armed" : ""}" title="#${p.ticket} opened at ${p.open}">
      <span class="${p.side === "buy" ? "up" : "down"}">${p.side === "buy" ? "▲" : "▼"}</span><b>${p.symbol}</b><span class="muted">${p.volume}</span><span class="tag ${p.owner}">${{ bot: "Bot", hermes: "Hermes", you: "You" }[p.owner] || "You"}</span>
      <em class="num ${cls(p.profit)}">${signed(p.profit)}</em><button type="button" data-quick="${p.ticket}" aria-label="Close #${p.ticket}"${real ? ` title="Real account: hold to close"` : ""}>${man.chipArm === p.ticket ? "close?" : real ? "hold ×" : "×"}</button></span>`).join("")
    || `<span class="muted small">No open trades${man.owner === "any" ? "" : " for this filter"}. Buy or Sell under the chart opens one.</span>`);
  drawManLines();
  if (man.editing != null) return;               // don't wipe the SL/TP editor while you type
  const off = man.backend ? "" : " disabled title=\"Needs the manual-trading backend\"", seen = man.posSeen;
  man.posSeen = new Set(ps.map(p => p.ticket));
  setHTML(tb, sel.map(p => `<tr data-t="${p.ticket}"${seen && !seen.has(p.ticket) ? ` class="enter"` : ""}><td>${p.symbol}</td><td><span class="tag ${p.owner}">${{ bot: "Bot", hermes: "Hermes", you: "You" }[p.owner] || "You"}</span></td>
      <td class="${p.side === "buy" ? "up" : "down"}">${p.side === "buy" ? "▲" : "▼"} ${p.side}</td><td>${p.volume}</td><td>${p.open}</td><td>${p.current}</td><td>${p.sl || "–"}</td><td>${p.tp || "–"}</td><td>${autoCell(p.ticket)}</td>
      <td class="${cls(p.profit)}">${signed(p.profit)}</td><td><span class="acts"><button data-act="be" title="Move the stop loss to the entry price"${off}>BE</button><button data-act="edit" title="Change stop loss / take profit"${off}>SL/TP</button><button data-act="auto" title="Break-even and trailing stop for this trade"${man.auto ? "" : ` disabled title="Waits for its backend"`}>Auto</button><button data-act="half" title="Close half"${off}>½</button><button class="x" data-act="close">Close</button></span></td></tr>`).join("")
    || `<tr><td colspan="11" class="muted">No positions${man.owner === "any" ? "" : " for this filter"}.</td></tr>`);
}
$("#man-owner").addEventListener("click", e => {
  const b = e.target.closest("[data-o]"); if (!b) return;
  man.owner = b.dataset.o; $$("#man-owner .chip").forEach(x => x.classList.toggle("active", x === b)); loadManPositions();
});
$("#man-pos").addEventListener("click", async e => {
  const b = e.target.closest("[data-act]"); if (!b || b.disabled) return;
  const tr = b.closest("tr"), row = tr.classList.contains("edit") ? tr.previousElementSibling : tr;   // Save/Cancel sit in the editor row
  const tk = +row.dataset.t, p = man.pos.find(x => x.ticket === tk); if (!p) return;
  const act = b.dataset.act;
  if (act === "edit") {
    man.editing = tk; tr.nextElementSibling?.classList.contains("edit") && tr.nextElementSibling.remove();
    tr.insertAdjacentHTML("afterend", `<tr class="edit"><td colspan="11"><div class="edit-row">Stop loss <input id="ed-sl" type="number" step="any" value="${p.sl || ""}" placeholder="none"> Take profit <input id="ed-tp" type="number" step="any" value="${p.tp || ""}" placeholder="none">
      <button class="btn xs primary" data-act="save">Save</button><button class="btn xs" data-act="cancel">Cancel</button></div></td></tr>`);
    $("#ed-sl").focus(); return;
  }
  if (act === "auto") {
    const a = man.auto?.tickets?.[tk] || {};
    man.editing = tk; tr.nextElementSibling?.classList.contains("edit") && tr.nextElementSibling.remove();
    tr.insertAdjacentHTML("afterend", `<tr class="edit"><td colspan="11"><div class="edit-row">Break-even after <input id="ed-be" type="number" min="0" step="10" value="${a.be_points || 0}"> points, trailing stop <input id="ed-trail" type="number" min="0" step="10" value="${a.trail_points || 0}"> points (0 = off)
      <button class="btn xs primary" data-act="save-auto">Save</button><button class="btn xs" data-act="cancel">Cancel</button>${p.owner === "bot" ? `<span class="muted small">This is the bot's trade; it manages its own exits too.</span>` : ""}</div></td></tr>`);
    $("#ed-be").focus(); return;
  }
  if (act === "cancel") { man.editing = null; loadManPositions(); return; }
  b.disabled = true;
  try {
    let r;
    if (act === "close") { selfClosed.add(tk); r = await api(`/api/positions/${tk}/close`, { method: "POST" }); toast(r.retcode === 10009 ? `Closed #${tk} · ${signed(p.profit)}` : `Close result: ${r.comment}`, r.retcode !== 10009); }
    if (act === "half") { const v = Math.max(volStep(), Math.round(p.volume / 2 / volStep()) * volStep()); r = await api("/api/manual/close", { method: "POST", body: { tickets: [tk], volume: +v.toFixed(volDec()) } }); toast(`Closed ${v.toFixed(volDec())} of #${tk}.`); }
    if (act === "be") { r = await api("/api/manual/modify", { method: "POST", body: { ticket: tk, sl: p.open, tp: p.tp || 0 } }); toast(r.ok ? `#${tk}: stop moved to entry ${p.open}.` : r.comment, !r.ok); }
    if (act === "save") {
      const tr0 = tr.previousElementSibling, t0 = +tr0.dataset.t;
      r = await api("/api/manual/modify", { method: "POST", body: { ticket: t0, sl: parseFloat($("#ed-sl").value) || 0, tp: parseFloat($("#ed-tp").value) || 0 } });
      toast(r.ok ? `#${t0}: stop loss and take profit updated.` : r.comment, !r.ok); man.editing = null;
    }
    if (act === "save-auto") {
      const t0 = +tr.previousElementSibling.dataset.t, be = +$("#ed-be").value || 0, trail = +$("#ed-trail").value || 0;
      r = await api("/api/manual/auto", { method: "POST", body: { ticket: t0, be_points: be, trail_points: trail } });
      toast(r.comment || (be || trail ? `#${t0}: ${[be && `break-even after ${be} points`, trail && `trailing ${trail} points behind`].filter(Boolean).join(", ")}.` : `#${t0}: automatic stop off.`));
      man.editing = null; await loadManAuto();
    }
  } catch (err) { toast(err.message, true); }
  loadManPositions(); loadPositions();
});
$("#man-open").addEventListener("click", async e => {    // × on a chip: two clicks, then that trade closes
  const b = e.target.closest("[data-quick]"); if (!b || isReal()) return;     // real account: hold instead (below)
  const tk = +b.dataset.quick;
  if (man.chipArm !== tk) { man.chipArm = tk; clearTimeout(man.chipT); man.chipT = setTimeout(() => { man.chipArm = null; loadManPositions(); }, 3000); loadManPositions(); return; }
  clearTimeout(man.chipT); man.chipArm = null; selfClosed.add(tk);
  try { const r = await api(`/api/positions/${tk}/close`, { method: "POST" }); toast(r.retcode === 10009 ? `Closed #${tk}.` : `Close result: ${r.comment}`, r.retcode !== 10009); } catch (err) { toast(err.message, true); }
  loadManPositions(); loadPositions();
});
document.addEventListener("click", async e => {
  const b = e.target.closest("#tab-manual [data-bulk]"); if (!b || b.disabled) return;
  const kind = b.dataset.bulk, match = { profit: p => p.profit > 0, loss: p => p.profit < 0, buys: p => p.side === "buy", sells: p => p.side === "sell", all: () => true }[kind];
  const sel = man.pos.filter(p => (man.owner === "any" || p.owner === man.owner) && match(p));
  if (!b.classList.contains("armed")) {          // two clicks, like Wipe: the first shows exactly what will close
    $$("#tab-manual .bulk-btns .btn.armed").forEach(x => x.classList.remove("armed"));
    b.classList.add("armed"); b.textContent = `Click again: close ${sel.length} (${signed(sel.reduce((s, p) => s + p.profit, 0))})`;
    clearTimeout(man.bulkT); man.bulkT = setTimeout(() => { b.classList.remove("armed"); b._html = null; loadManPositions(); }, 4000); return;
  }
  clearTimeout(man.bulkT); b.classList.remove("armed"); b._html = null; b.disabled = true;
  sel.forEach(p => selfClosed.add(p.ticket));
  let closed = 0, failed = 0;
  if (man.backend) {
    try { const r = await api("/api/manual/close", { method: "POST", body: { filter: kind, owner: man.owner } }); closed = r.closed.length; failed = r.failed.length; }
    catch (err) { toast(err.message, true); }
  } else {
    for (const p of sel) { try { const r = await api(`/api/positions/${p.ticket}/close`, { method: "POST" }); r.retcode === 10009 ? closed++ : failed++; } catch (err) { failed++; } }
  }
  toast(`Closed ${closed} position${closed === 1 ? "" : "s"}${failed ? ` · ${failed} failed` : ""}.`, failed > 0);
  loadManPositions(); loadPositions();
});
async function loadManOrders() {
  const tb = $("#man-orders tbody"), all = $("#man-cancel-all");
  if (!man.backend) { setHTML(tb, `<tr><td colspan="8" class="muted">Pending orders show up here once the manual-trading backend is in.</td></tr>`); all.disabled = true; return; }
  let os; try { os = await api("/api/manual/orders"); } catch (e) { setHTML(tb, `<tr><td colspan="8" class="muted">${e.status === 503 ? "Open MT5 to see pending orders." : e.message}</td></tr>`); return; }
  all.disabled = !os.length;
  setHTML(tb, os.map(o => `<tr><td>${o.symbol}</td><td class="${o.type.startsWith("buy") ? "up" : "down"}">${o.type.startsWith("buy") ? "▲" : "▼"} ${o.type.replace("_", " ")}</td><td>${o.volume}</td><td>${o.price}</td><td>${o.sl || "–"}</td><td>${o.tp || "–"}</td>
      <td>${(o.time_setup || "").replace("T", " ").slice(5, 16)}</td><td><span class="acts"><button class="x" data-cancel="${o.ticket}">Cancel</button></span></td></tr>`).join("")
    || `<tr><td colspan="8" class="muted">No pending orders.</td></tr>`);
}
$("#man-orders").addEventListener("click", async e => {
  const b = e.target.closest("[data-cancel]"); if (!b) return; b.disabled = true;
  try { await api("/api/manual/orders/cancel", { method: "POST", body: { tickets: [+b.dataset.cancel] } }); toast("Order cancelled."); } catch (err) { toast(err.message, true); }
  loadManOrders();
});
$("#man-cancel-all").onclick = async () => {
  const b = $("#man-cancel-all");
  if (!b.classList.contains("armed")) { b.classList.add("armed", "danger-outline"); b.textContent = "Click again to cancel all"; clearTimeout(man.cancelT); man.cancelT = setTimeout(() => { b.classList.remove("armed", "danger-outline"); b.textContent = "Cancel all"; }, 4000); return; }
  clearTimeout(man.cancelT); b.classList.remove("armed", "danger-outline"); b.textContent = "Cancel all";
  try { const r = await api("/api/manual/orders/cancel", { method: "POST", body: { all: true } }); toast(`Cancelled ${r.cancelled.length} order(s)${r.failed.length ? ` · ${r.failed.length} failed` : ""}.`, r.failed.length > 0); } catch (err) { toast(err.message, true); }
  loadManOrders();
};
async function loadManHistory() {
  const tb = $("#man-hist tbody");
  if (!man.backend) { setHTML(tb, `<tr><td colspan="8" class="muted">Today's closed deals show up here once the manual-trading backend is in.</td></tr>`); return; }
  let hs; try { hs = await api("/api/manual/history?days=1"); } catch (e) { setHTML(tb, `<tr><td colspan="8" class="muted">${e.message}</td></tr>`); return; }
  const net = hs.reduce((s, h) => s + (h.profit || 0), 0);
  setHTML($("#man-hist-meta"), hs.length ? `${hs.length} closed · net <b class="num ${cls(net)}">${signed(net)}</b>` : "");
  man.hist = hs;
  setHTML(tb, hs.map((h, i) => `<tr class="click" data-h="${i}" title="Replay this trade"><td>${srvHM(h.time)}</td><td>${h.symbol}</td><td class="${h.side === "buy" ? "up" : "down"}">${h.side === "buy" ? "▲" : "▼"} ${h.side}</td><td>${h.volume}</td><td>${h.open}</td><td>${h.close}</td>
      <td class="${cls(h.profit)}">${signed(h.profit)}</td><td><span class="tag ${h.owner}">${{ bot: "Bot", hermes: "Hermes", you: "You" }[h.owner] || "You"}</span></td></tr>`).join("")
    || `<tr><td colspan="8" class="muted">Nothing closed today yet.</td></tr>`);
}
async function loadManQuotes() {
  const syms = state.settings?.symbols_watch || []; if (!syms.length) return;
  let qs = null;
  if (man.backend) { try { qs = await api(`/api/manual/quotes?symbols=${encodeURIComponent(syms.join(","))}`); } catch (e) { qs = null; } }
  if (!qs) qs = (await Promise.all(syms.map(s => api(`/api/bars?symbol=${encodeURIComponent(s)}&count=1`)
    .then(d => ({ symbol: d.symbol, bid: d.bid, ask: d.ask, digits: d.digits, point: d.point })).catch(() => null)))).filter(Boolean);
  setHTML($("#man-quotes tbody"), qs.map(q => `<tr data-sym="${q.symbol}"${q.symbol === man.symbol ? ` class="sel"` : ""}><td>${q.symbol}</td><td class="num">${fmt(q.bid, q.digits)}</td><td class="num">${fmt(q.ask, q.digits)}</td><td class="num">${Math.round((q.ask - q.bid) / q.point)}</td></tr>`).join("")
    || `<tr><td colspan="4" class="muted">Open MT5 to see quotes.</td></tr>`);
}
$("#man-quotes").addEventListener("click", e => { const r = e.target.closest("[data-sym]"); if (r) manPick(r.dataset.sym); });
async function openManual() {
  manSymbols(); await probeManual();
  loadManBars(); loadManQuote(); loadManPositions(); loadManQuotes(); loadManOrders(); loadManHistory();
  realBanner(); renderKeysHint(); renderConn();
}
setInterval(() => {                               // only while the Manual tab is open: quote 1 s, positions 2 s, lists 3 s, history 15 s
  if (state.tab !== "manual" || document.hidden) return;
  man.tick++; loadManBars(); if (man.backend) loadManQuote(); else renderConn();
  if (man.tick % 2 === 0) { loadManPositions(); realBanner(); }
  if (man.tick % 3 === 0) { loadManQuotes(); loadManOrders(); if (man.auto) loadManAuto(); }
  if (man.tick % 15 === 0) loadManHistory();
}, 1000);

/* real-account guard: a red banner on the Manual tab, "type REAL" once per app session before the first real order
   (and before one-click can be switched on), and hold-to-close on the quick-close chips */
function realBanner() {
  const real = isReal(); $("#man-real").hidden = !real;
  if (man.wasReal !== real) { man.wasReal = real; if (state.tab === "manual") loadManPositions(); }   // chips switch to hold-to-close $("#tab-manual").classList.toggle("is-real", real);
  if (real) $("#man-real-acct").textContent = $("#acct-server").textContent || "this account";
}
function realCheck() {
  if (!isReal() || man.realSession) return Promise.resolve(true);
  const dlg = $("#real-dlg"), inp = $("#real-input");
  $("#real-acct").textContent = $("#acct-server").textContent || "this account";
  inp.value = ""; $("#real-ok").disabled = true; dlg.returnValue = ""; dlg.showModal(); inp.focus();
  return new Promise(res => { dlg.onclose = () => { const ok = dlg.returnValue === "ok"; if (ok) { man.realSession = true; toast("Real-money orders are on until you close the app."); } res(ok); }; });
}
$("#real-input").addEventListener("input", e => $("#real-ok").disabled = e.target.value.trim().toUpperCase() !== "REAL");
$("#real-input").addEventListener("keydown", e => {        // Enter confirms only when REAL is typed (never the Cancel button)
  if (e.key !== "Enter") return; e.preventDefault(); if (!$("#real-ok").disabled) $("#real-dlg").close("ok");
});
$("#man-open").addEventListener("pointerdown", e => {    // real account: hold × for a second to close that trade
  const b = e.target.closest("[data-quick]"); if (!b || !isReal() || e.button !== 0) return;
  e.preventDefault(); const tk = +b.dataset.quick; man.holding = tk; b.classList.add("holding");
  const stop = () => { clearTimeout(man.holdT); b.classList.remove("holding"); man.holding = null; document.removeEventListener("pointerup", stop); b.removeEventListener("pointerleave", stop); };
  document.addEventListener("pointerup", stop); b.addEventListener("pointerleave", stop);
  man.holdT = setTimeout(async () => {
    stop(); selfClosed.add(tk);
    try { const r = await api(`/api/positions/${tk}/close`, { method: "POST" }); toast(r.retcode === 10009 ? `Closed #${tk}.` : `Close result: ${r.comment}`, r.retcode !== 10009); } catch (err) { toast(err.message, true); }
    loadManPositions(); loadPositions();
  }, 1000);
});

/* connection: Buy and Sell grey out when MT5 is offline, the broker link is down, the market is closed or the price
   stopped ticking. Uses the backend's connected / tick_age / market_open when present, else what the page can see. */
function connState() {
  const q = man.q;
  if (man.feedErr) return ["off", man.feedErr];
  if (q?.connected === false) return ["off", "MT5 has no broker connection"];
  if (q?.market_open === false) return ["closed", "Market closed"];
  if (q?.tick_age != null) return q.tick_age > 10 ? ["stale", `No new price for ${Math.round(q.tick_age)} s`] : ["live", `Live, last tick ${q.tick_age < 1 ? "under 1" : Math.round(q.tick_age)} s ago`];
  if (!q) return ["wait", "Connecting…"];
  const { day } = serverClock(); if (day === 6 || day === 0) return ["closed", "Market closed for the weekend"];
  const age = Math.round((Date.now() - man.priceAt) / 1000);
  return age > 20 ? ["quiet", `Price unchanged for ${age} s`] : ["live", "Live"];
}
function renderConn() {
  const [k, txt] = connState(), el = $("#man-conn");
  if (el._k !== k) { el.className = `conn ${k}`; el._k = k; }
  if (el.lastChild.textContent !== txt) el.lastChild.textContent = txt;
  const block = k === "off" || k === "stale" || k === "closed";
  if ((k === "off" || k === "stale") && (man.connWas === "live" || man.connWas === "quiet")) feedLost();
  man.connWas = k; man.blocked = block ? txt : null;
  $$("#man-buy, #man-sell").forEach(b => { b.classList.toggle("blocked", block); b.title = block ? `Can't trade: ${txt.toLowerCase()}` : ""; });
}

/* drag a position's SL or TP line on the chart; letting go sends /api/manual/modify (a bad level snaps back) */
(() => {
  const wrap = $("#man-chart");
  const yOf = e => e.clientY - wrap.getBoundingClientRect().top;
  function lineAt(y) {
    let best = null;
    (man.lines || []).forEach(L => {
      if (!L.meta) return; const ly = man.series.priceToCoordinate(L.price); if (ly == null) return;
      const d = Math.abs(ly - y); if (d < 7 && (!best || d < best.d)) best = { ...L, d };
    });
    return best;
  }
  function check(d) {                             // is this level on the right side of the price, outside the stop level?
    const q = man.q, gap = (q.stops_level || 0) * q.point, buy = d.p.side === "buy", ref = buy ? q.bid : q.ask;
    const below = d.price < ref - gap, above = d.price > ref + gap;
    return d.kind === "sl" ? (buy ? below : above) : (buy ? above : below);
  }
  function title(d) {
    const q = man.q, dir = d.p.side === "buy" ? 1 : -1, pts = Math.round((d.price - d.p.open) * dir / q.point);
    const money = q.tick_value && q.tick_size ? (d.price - d.p.open) * dir / q.tick_size * q.tick_value * d.p.volume : null;
    return `${d.kind.toUpperCase()} ${fmt(d.price, q.digits)}  ${pts >= 0 ? "+" : ""}${pts} pts${money != null ? `  ${signed(money)}` : ""}${check(d) ? "" : "  (not allowed here)"}`;
  }
  wrap.addEventListener("pointermove", e => {
    if (man.drag) {
      const q = man.q, raw = man.series.coordinateToPrice(yOf(e)); if (raw == null) return;
      man.drag.price = +(Math.round(raw / q.point) * q.point).toFixed(q.digits);
      man.drag.line.applyOptions({ price: man.drag.price, title: title(man.drag), color: check(man.drag) ? man.drag.color : "#8c9098" });
      return;
    }
    wrap.classList.toggle("grab-line", !!(man.backend && lineAt(yOf(e))));
  });
  wrap.addEventListener("pointerdown", e => {    // capture phase: runs before the chart, so it doesn't pan
    if (e.button !== 0 || !man.backend || !man.q) return;
    const hit = lineAt(yOf(e)); if (!hit) return;
    const p = man.pos.find(x => x.ticket === hit.meta.ticket); if (!p) return;
    e.preventDefault(); e.stopPropagation();
    man.drag = { ...hit.meta, p, line: hit.line, color: hit.color, from: hit.price, price: hit.price };
    man.chart.applyOptions({ handleScroll: false, handleScale: false });
    wrap.setPointerCapture(e.pointerId); wrap.classList.add("dragging");
  }, true);
  const drop = async e => {
    const d = man.drag; if (!d) return;
    man.drag = null; wrap.classList.remove("dragging");
    man.chart.applyOptions({ handleScroll: true, handleScale: true });
    try { wrap.releasePointerCapture(e.pointerId); } catch (err) {}
    const back = () => { man.lineSig = ""; drawManLines(); };
    if (e.type === "pointercancel" || Math.abs(d.price - d.from) < man.q.point / 2) return back();
    if (!check(d)) { toast(`A ${d.p.side}'s ${d.kind === "sl" ? "stop loss" : "take profit"} can't go there: it has to sit ${(d.kind === "sl") === (d.p.side === "buy") ? "below" : "above"} the price${man.q.stops_level ? `, at least ${man.q.stops_level} points away` : ""}.`, true); return back(); }
    const body = { ticket: d.ticket, sl: d.kind === "sl" ? d.price : (d.p.sl || 0), tp: d.kind === "tp" ? d.price : (d.p.tp || 0) };
    try {
      const r = await api("/api/manual/modify", { method: "POST", body });
      if (r.ok) { d.p[d.kind] = d.price; toast(`#${d.ticket}: ${d.kind === "sl" ? "stop loss" : "take profit"} moved to ${fmt(d.price, man.q.digits)}${d.p.owner === "bot" ? " (the bot's trade)" : ""}.`); }
      else toast(`Not moved: ${r.comment}`, true);
    } catch (err) { toast(err.message, true); }
    back(); loadManPositions();
  };
  wrap.addEventListener("pointerup", drop, true); wrap.addEventListener("pointercancel", drop, true);
})();

/* keyboard shortcuts (Settings > Manual trading, this PC): B buy, S sell, Shift+X close all, Esc cancel, +/- lots.
   They press the same buttons, so the two-click confirm, one-click and the real-money check all still apply. */
const pref = (k, dflt) => { try { const v = localStorage.getItem(k); return v == null ? dflt : v === "1"; } catch (e) { return dflt; } };
const setPref = (k, on) => { try { localStorage.setItem(k, on ? "1" : "0"); } catch (e) {} };
document.addEventListener("click", e => {          // links that open a Settings section
  const a = e.target.closest("[data-sec]"); if (!a) return; e.preventDefault();
  setTimeout(() => $(`#set-nav a[href="#${a.dataset.sec}"]`)?.click(), 60);
});

/* break-even + trailing stop: the backend moves the stop (it keeps working with the tab closed); the ticket sets it
   for the next order, Positions > Auto for one trade */
async function loadManAuto(first = false) {
  try { man.auto = await api("/api/manual/auto"); }
  catch (e) { if (e.status === 404) man.auto = false; }
  const on = !!man.auto;
  $$("#man-be-pts, #man-trail-pts").forEach(i => i.disabled = !on);
  $("#man-auto-note").textContent = on ? "0 = off. The app moves the stop for you, even with this tab closed." : "Break-even and trailing stops wait for their backend (Chat A is building it).";
  if (on && first) { $("#man-be-pts").value = man.auto.defaults?.be_points || 0; $("#man-trail-pts").value = man.auto.defaults?.trail_points || 0; }
  if (on) { man.lineSig = ""; drawManLines(); }
}
function autoCell(tk) {
  const a = man.auto?.tickets?.[tk]; if (!a || (!a.be_points && !a.trail_points)) return `<span class="muted">–</span>`;
  return `<span class="auto-tags">${a.be_points ? `<span class="tag${a.be_done ? " done" : ""}" title="${a.be_done ? "Stop already at break-even" : `Stop moves to entry after ${a.be_points} points`}">BE ${a.be_points}${a.be_done ? " ✓" : ""}</span>` : ""}${a.trail_points ? `<span class="tag" title="Stop follows the price ${a.trail_points} points behind">Trail ${a.trail_points}</span>` : ""}</span>`;
}

/* history rows and bot-trade rows open that trade in Review > Trade replay */
const srvHM = t => typeof t === "number" ? new Date(t * 1000).toISOString().slice(11, 16) : String(t || "").slice(11, 16);
$("#man-hist").addEventListener("click", e => { const r = e.target.closest("[data-h]"); if (!r) return; const h = man.hist?.[+r.dataset.h]; if (h) openReplay("you", h.ticket); });
$("#bt-table").addEventListener("click", e => { const r = e.target.closest("tr"); const id = +r?.firstElementChild?.textContent; if (id && !r.classList.contains("open-row")) openReplay("bot", id); });

/* ---------- alerts: a sound and a banner when a take profit or stop loss is hit, on every tab ----------
   From /api/events when the backend has it; until then a close is guessed from positions that vanish next to their
   TP or SL (closes you made from this app are skipped). */
const selfClosed = new Set();
const alertsState = { since: null, ok: null, prev: null, titleT: null };
const ALERT = {
  tp: { head: "Take profit hit", cls: "tp" },
  sl: { head: "Stop loss hit", cls: "sl" },
  be: { head: "Stop moved to break-even", tone: null, cls: "info" },
  trail: { head: "Trailing stop moved", tone: null, cls: "info" },
};
function showAlert(ev) {
  let a = ALERT[ev.kind]; if (!a) return;
  if ((ev.kind === "trail") && alertsState.lastTrail === ev.ticket) return;   // one banner per trailing trade, not every step
  if (ev.kind === "trail") alertsState.lastTrail = ev.ticket;
  if (a.cls === "info") playEvent("stopMoved");
  else playEvent(ev.profit != null ? (ev.profit >= 0 ? "profit" : "loss") : ev.kind === "tp" ? "profit" : "loss");
  if (ev.kind === "sl" && ev.profit > 0) a = { head: "Stop hit, in profit", cls: "tp" };   // a trailed or break-even stop
  if (!pref("tpslAlerts", true)) return;
  const who = { bot: "Bot", hermes: "Hermes", you: "You" }[ev.owner] || "You";
  notify({ kind: a.cls === "info" ? "info" : a.cls, title: `${a.head}${ev.guess ? " (probably)" : ""}`,
    html: `<span class="${ev.side === "buy" ? "up" : "down"}">${ev.side === "buy" ? "▲" : "▼"}</span> ${esc(ev.side || "")} ${ev.volume ?? ""} ${esc(ev.symbol || "")}${ev.price ? ` at ${ev.price}` : ""} <span class="tag ${esc(ev.owner || "you")}">${who}</span>`,
    body: `${ev.side || ""} ${ev.volume ?? ""} ${ev.symbol || ""}${ev.price ? ` at ${ev.price}` : ""} (${who})`,
    amount: ev.profit != null && a.cls !== "info" ? ev.profit : null, onClick: () => showTab("manual") });
  if (document.hidden && a.cls !== "info") {        // the taskbar title says it too while the window is in the background
    const t0 = document.title; document.title = `${a.head}: ${signed(ev.profit)}`;
    const back = () => { document.title = t0; document.removeEventListener("visibilitychange", back); };
    document.addEventListener("visibilitychange", back);
  }
}
async function pollEvents() {
  if (alertsState.ok === false) return;
  try {
    const r = await api(`/api/events${alertsState.since != null ? `?since=${alertsState.since}` : ""}`);
    alertsState.ok = true;
    if (alertsState.since != null) (r.events || []).forEach(ev => {
      if (ev.kind === "close" && ev.profit != null) {           // closed early or by hand
        playEvent(ev.profit >= 0 ? "profit" : "loss");
        if (selfClosed.delete(ev.ticket) || !pref("tpslAlerts", true)) return;   // closed from this app: its own message already said so
        const who = { bot: "Bot", hermes: "Hermes", you: "You" }[ev.owner] || "You";
        notify({ kind: ev.profit >= 0 ? "tp" : "sl", title: `${who === "You" ? "Your" : `${who}'s`} trade closed`, body: `${ev.side || ""} ${ev.volume ?? ""} ${ev.symbol || ""}${ev.price ? ` at ${ev.price}` : ""}`, amount: ev.profit, onClick: () => showTab("manual") });
      } else showAlert(ev);
    });
    alertsState.since = r.last_id;
  } catch (e) { if (e.status === 404) alertsState.ok = false; }
}
function guessCloses(ps) {                         // fallback while /api/events isn't there
  const now = new Map(ps.map(p => [p.ticket, p])), prev = alertsState.prev; alertsState.prev = now;
  if (!prev || alertsState.ok !== false) return;
  prev.forEach((p, tk) => {
    if (now.has(tk) || selfClosed.delete(tk)) return;
    const near = lvl => lvl && Math.abs(p.current - lvl) <= Math.max(Math.abs(lvl - p.open) * 0.25, 1e-9);
    const kind = near(p.tp) ? "tp" : near(p.sl) ? "sl" : null;
    if (kind) showAlert({ kind, guess: true, ticket: tk, symbol: p.symbol, side: p.side, volume: p.volume, price: kind === "tp" ? p.tp : p.sl, profit: p.profit, owner: p.owner });
  });
}
setInterval(pollEvents, 3000); pollEvents();

/* ---------- review: you vs the bot, trade replay, weekly summary ----------
   /api/stats/compare when the backend has it; until then the same numbers are worked out here from the bot's ledger
   and /api/manual/history. Times are broker server time, like the charts. */
const rv = { days: 30, mode: "paper", who: "all", trades: [], sel: null, chart: null, series: null, lines: [], curve: null, week: null, pending: null, busy: false };
const WHO = { bot: "Bot", hermes: "Hermes", you: "You" };
const REASON = { tp: "Take profit", sl: "Stop loss", manual: "Closed by hand", so: "Stop out", early: "Bot closed early", model: "Bot closed early", kill: "Kill switch" };
function srvOffset() {                           // broker server time = New York time + 7 h
  const now = new Date(), ny = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" })), utc = new Date(now.toLocaleString("en-US", { timeZone: "UTC" }));
  return Math.round((ny - utc) / 60000) * 60 + 7 * 3600;
}
const epoch = v => v == null ? null : typeof v === "number" ? v : Math.round(Date.parse(v) / 1000) || null;
const srvDate = t => t ? new Date(t * 1000).toLocaleString("en-US", { timeZone: "UTC", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) : "—";
const held = m => m == null ? "—" : m < 60 ? `${Math.max(1, Math.round(m))} min` : m < 1440 ? `${Math.floor(m / 60)} h ${Math.round(m % 60)} min` : `${(m / 1440).toFixed(1)} days`;
function normBot(t) {
  const off = srvOffset();
  return { src: "bot", key: `bot-${t.id}`, id: t.id, owner: "bot", symbol: t.symbol, side: t.side, volume: t.lots, open: t.entry, close: t.exit,
    sl: t.sl0 ?? t.sl, tp: t.tp, profit: t.pnl ?? 0, reason: t.exit_reason, r: t.r_multiple, setup: t.setup, mode: t.mode,
    openT: t.entry_time || t.open_bar || (epoch(t.open_utc) && epoch(t.open_utc) + off), closeT: t.exit_time || t.close_bar || (epoch(t.close_utc) && epoch(t.close_utc) + off) };
}
function normYou(h) {
  return { src: "you", key: `you-${h.ticket}`, id: h.ticket, owner: h.owner || "you", symbol: h.symbol, side: h.side, volume: h.volume, open: h.open, close: h.close,
    sl: h.sl, tp: h.tp, profit: h.profit ?? 0, reason: h.reason, openT: epoch(h.open_time), closeT: epoch(h.time) };
}
function statsOf(ts) {
  const n = ts.length, wins = ts.filter(t => t.profit > 0), losses = ts.filter(t => t.profit < 0);
  const sum = a => a.reduce((s, t) => s + t.profit, 0), net = sum(ts), gw = sum(wins), gl = -sum(losses);
  const holds = ts.filter(t => t.openT && t.closeT).map(t => (t.closeT - t.openT) / 60);
  const by_hour = Array.from({ length: 24 }, (_, hour) => ({ hour, trades: 0, net: 0 }));
  ts.forEach(t => { const tt = t.closeT || t.openT; if (!tt) return; const b = by_hour[new Date(tt * 1000).getUTCHours()]; b.trades++; b.net += t.profit; });
  let cum = 0; const curve = ts.filter(t => t.closeT).sort((a, b) => a.closeT - b.closeT).map(t => ({ time: t.closeT, cum: (cum += t.profit) }));
  return { trades: n, wins: wins.length, losses: losses.length, win_rate: n ? 100 * wins.length / n : null, net,
    avg_win: wins.length ? gw / wins.length : null, avg_loss: losses.length ? -gl / losses.length : null,
    profit_factor: gl ? gw / gl : gw ? Infinity : null, expectancy: n ? net / n : null,
    best_trade: n ? Math.max(...ts.map(t => t.profit)) : null, worst_trade: n ? Math.min(...ts.map(t => t.profit)) : null,
    avg_hold_min: holds.length ? holds.reduce((a, b) => a + b, 0) / holds.length : null, by_hour, curve };
}
async function loadReview() {
  if (rv.busy) return; rv.busy = true;
  const d = rv.days, m = rv.mode, since = d ? Date.now() / 1000 + srvOffset() - d * 86400 : 0, notes = [];
  let bot = [], you = [], cmp = null;
  try { cmp = await api(`/api/stats/compare?days=${d}&mode=${m}`); } catch (e) { cmp = null; }
  try { const b = await api("/api/bot/trades?limit=3000"); bot = b.recent.filter(t => t.status === "closed" && (m === "all" || t.mode === m)).map(normBot); } catch (e) { notes.push("The bot's trades couldn't be loaded."); }
  try { you = (await api(`/api/manual/history?days=${d || 90}`)).map(normYou).filter(t => t.owner !== "bot"); }
  catch (e) { notes.push(e.status === 404 ? "Your own trades show here once the manual-trading backend is in." : e.status === 503 ? "Open MT5 to include your own trades." : `Your trades: ${e.message}.`); }
  if (!d) notes.push("“All” covers the last 90 days of your MT5 history.");
  bot = bot.filter(t => !since || (t.closeT || 0) >= since);
  rv.trades = [...you, ...bot].sort((a, b) => (b.closeT || 0) - (a.closeT || 0));
  const S = cmp || { you: statsOf(you.filter(t => t.owner === "you")), bot: statsOf(bot) };
  renderVs(S); renderCurve(S); renderHours(S);
  $("#rv-note").textContent = notes.join(" ");
  renderRvList(); rv.busy = false;
  if (rv.pending) { const t = rv.trades.find(x => x.key === rv.pending); rv.pending = null; if (t) { showReplay(t); $(`#rv-list [data-k="${t.key}"]`)?.scrollIntoView({ block: "nearest" }); } else toast("That trade isn't in this period's list.", true); }
  else if (!rv.sel && rv.trades.length) showReplay(filteredRv()[0] || rv.trades[0]);
}
function renderVs(S) {
  const Y = S.you || {}, B = S.bot || {}, pct = v => v == null ? "—" : `${Math.round(v)}%`;
  const pf = v => v == null ? "—" : v === Infinity || v > 999 ? "no losses" : (+v).toFixed(2), mins = v => held(v);
  [Y, B].forEach(x => { if (x.trades && !x.losses && x.profit_factor == null) x.profit_factor = Infinity; });
  const rows = [["Trades", "trades", v => v ?? 0, null], ["Win rate", "win_rate", pct, 1], ["Net P/L", "net", signed, 1],
    ["Average win", "avg_win", signed, 1], ["Average loss", "avg_loss", signed, 1], ["Profit factor", "profit_factor", pf, 1],
    ["Per trade", "expectancy", signed, 1], ["Best trade", "best_trade", signed, 1], ["Worst trade", "worst_trade", signed, 1], ["Average hold", "avg_hold_min", mins, null]];
  const head = !Y.trades && !B.trades ? "No closed trades in this period yet."
    : `${rv.days ? `Last ${rv.days} days` : "All of it"}: you ${Y.trades ? `made <b class="${cls(Y.net)}">${signed(Y.net)}</b> on ${Y.trades} trade${Y.trades === 1 ? "" : "s"}` : "have no closed trades"}, the bot ${B.trades ? `<b class="${cls(B.net)}">${signed(B.net)}</b> on ${B.trades}` : "has none"}.`;
  setHTML($("#rv-vs"), `<p class="vs-lead">${head}</p><div class="vs-grid"><span></span><span class="vs-h you">You</span><span class="vs-h bot">Bot</span>${rows.map(([label, k, f, hi]) => {
    const a = Y[k], b = B[k], both = a != null && b != null && Y.trades && B.trades && hi;
    const aw = both && (a === Infinity || a > b), bw = both && (b === Infinity || b > a);
    return `<span class="vs-l">${label}</span><b class="num${aw ? " win" : ""}">${f(a)}</b><b class="num${bw ? " win" : ""}">${f(b)}</b>`; }).join("")}</div>`);
}
function rvCurveChart() {
  if (rv.curve || !window.LightweightCharts) return;
  rv.curve = LightweightCharts.createChart($("#rv-curve"), {
    autoSize: true, layout: { background: { color: "transparent" }, textColor: "#8c9098", fontFamily: "IBM Plex Mono, monospace", fontSize: 11 },
    grid: { vertLines: { visible: false }, horzLines: { color: "rgba(255,255,255,.035)" } },
    rightPriceScale: { borderColor: "#262c34" }, timeScale: { borderColor: "#262c34", timeVisible: true, secondsVisible: false }, handleScroll: false, handleScale: false,
  });
  rv.cYou = rv.curve.addLineSeries({ color: "#c9a24a", lineWidth: 2, priceLineVisible: false });
  rv.cBot = rv.curve.addLineSeries({ color: "#89cff0", lineWidth: 2, priceLineVisible: false });
}
function renderCurve(S) {
  rvCurveChart(); if (!rv.curve) return;
  const pts = c => { const out = []; (c || []).forEach(p => { const t = Math.floor(epoch(p.time)); if (out.length && out[out.length - 1].time >= t) out[out.length - 1].value = p.cum; else out.push({ time: t, value: p.cum }); }); return out; };
  rv.cYou.setData(pts(S.you?.curve)); rv.cBot.setData(pts(S.bot?.curve)); rv.curve.timeScale().fitContent();
}
function renderHours(S) {
  const rowsOf = [["you", S.you?.by_hour || []], ["bot", S.bot?.by_hour || []]];
  const max = Math.max(1e-9, ...rowsOf.flatMap(([, h]) => h.map(x => Math.abs(x.net))));
  const best = h => { const b = h.filter(x => x.trades).sort((a, c) => c.net - a.net)[0]; return b && b.net > 0 ? `${String(b.hour).padStart(2, "0")}:00 (${signed(b.net)})` : "none yet"; };
  setHTML($("#rv-hours"), `<div class="hr-title"><b>Best hours</b><span class="muted small">server time, by the hour each trade closed</span></div>${rowsOf.map(([who, h]) => `<div class="hr-row"><span class="${who}">${WHO[who]}</span><div class="hr-cells">${
    Array.from({ length: 24 }, (_, i) => { const x = h.find(y => y.hour === i) || { trades: 0, net: 0 }, a = Math.abs(x.net) / max;
      return `<i style="--a:${x.trades ? (0.18 + 0.82 * a).toFixed(2) : 0}" class="${x.net > 0 ? "pos" : x.net < 0 ? "neg" : ""}" title="${String(i).padStart(2, "0")}:00  ${x.trades} trade${x.trades === 1 ? "" : "s"}  ${signed(x.net)}"></i>`; }).join("")}</div><span class="muted small">best ${best(h)}</span></div>`).join("")}
    <div class="hr-row hr-axis"><span></span><div class="hr-cells">${Array.from({ length: 24 }, (_, i) => `<small>${i % 3 ? "" : i}</small>`).join("")}</div><span></span></div>`);
}
const filteredRv = () => rv.trades.filter(t => rv.who === "all" || (rv.who === "bot" ? t.src === "bot" : t.src === "you"));
function renderRvList() {
  const list = filteredRv().slice(0, 300);
  setHTML($("#rv-list"), list.map(t => `<div class="rv-item${t.key === rv.sel ? " sel" : ""}" role="option" aria-selected="${t.key === rv.sel}" data-k="${t.key}">
      <span class="${t.side === "buy" ? "up" : "down"}">${t.side === "buy" ? "▲" : "▼"}</span><b>${t.symbol}</b><span class="tag ${t.owner}">${WHO[t.owner] || "You"}</span>
      <span class="muted small">${srvDate(t.closeT)}</span><span class="rsn">${t.reason ? (t.reason === "tp" ? "TP" : t.reason === "sl" ? "SL" : "") : ""}</span><em class="num ${cls(t.profit)}">${signed(t.profit)}</em></div>`).join("")
    || `<div class="empty-state compact"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg><div><b>No closed trades here yet</b>Closed trades from the bot and from the Manual tab land in this list.</div></div>`);
}
function rvChart() {
  if (rv.chart || !window.LightweightCharts) return;
  rv.chart = LightweightCharts.createChart($("#rv-chart"), {
    autoSize: true, layout: { background: { color: "transparent" }, textColor: "#8c9098", fontFamily: "IBM Plex Mono, monospace", fontSize: 11 },
    grid: { vertLines: { color: "rgba(255,255,255,.035)" }, horzLines: { color: "rgba(255,255,255,.035)" } },
    rightPriceScale: { borderColor: "#262c34" }, timeScale: { borderColor: "#262c34", timeVisible: true, secondsVisible: false }, localization: { locale: "en-US" },
  });
  rv.series = rv.chart.addCandlestickSeries({ upColor: "#3fb68b", downColor: "#e0574f", borderVisible: false, wickUpColor: "#3fb68b", wickDownColor: "#e0574f",
    autoscaleInfoProvider: orig => {             // keep the trade's entry, SL, TP and exit on screen
      const r = orig(); if (!r || !rv.levels?.length) return r;
      return { ...r, priceRange: { minValue: Math.min(r.priceRange.minValue, ...rv.levels), maxValue: Math.max(r.priceRange.maxValue, ...rv.levels) } };
    } });
}
async function showReplay(t) {
  rv.sel = t.key; $$("#rv-list .rv-item").forEach(x => { const on = x.dataset.k === t.key; x.classList.toggle("sel", on); x.setAttribute("aria-selected", on); });
  const dir = t.side === "buy" ? 1 : -1, pts = t.open != null && t.close != null && man.q?.symbol === t.symbol ? Math.round((t.close - t.open) * dir / man.q.point) : null;
  setHTML($("#rv-title"), `<span class="${t.side === "buy" ? "up" : "down"}">${t.side === "buy" ? "▲ Buy" : "▼ Sell"}</span> <b>${t.volume} ${t.symbol}</b> <span class="tag ${t.owner}">${WHO[t.owner] || "You"}</span>
    <em class="num ${cls(t.profit)}">${signed(t.profit)}</em>${pts != null ? `<span class="muted small">${pts >= 0 ? "+" : ""}${pts} points</span>` : ""}`);
  const mins = t.openT && t.closeT ? (t.closeT - t.openT) / 60 : null;
  const fact = (k, v) => v == null || v === "" ? "" : `<div><span>${k}</span><b class="num">${v}</b></div>`;
  setHTML($("#rv-facts"), fact("Opened", t.openT ? srvDate(t.openT) : "not recorded") + fact("Closed", srvDate(t.closeT)) + fact("Held", held(mins))
    + fact("Entry", t.open) + fact("Exit", t.close) + fact("Stop loss", t.sl || "none") + fact("Take profit", t.tp || "none")
    + fact("How it ended", REASON[t.reason] || t.reason || null) + fact("Result in R", t.r != null ? `${t.r >= 0 ? "+" : ""}${t.r}R` : null)
    + fact("Setup", t.setup ? (state.bot.data?.setup_names?.[t.setup] || t.setup) : null) + fact("Mode", t.mode || null));
  rvChart(); if (!rv.series) return;
  const end = (t.closeT || t.openT) + 30 * 60, count = Math.min(1500, Math.max(150, Math.ceil((mins || 0) + 90)));
  let d; try { d = await api(`/api/bars?symbol=${encodeURIComponent(t.symbol)}&count=${count}&before=${end}`); }
  catch (e) { rv.series.setData([]); $("#rv-facts").insertAdjacentHTML("afterbegin", `<p class="note span-all">${e.status === 503 ? "Open MT5 to see the chart for this trade." : e.message}</p>`); return; }
  if (rv.sel !== t.key) return;
  rv.series.applyOptions({ priceFormat: { type: "price", precision: d.digits, minMove: d.point } });
  rv.series.setData(d.bars.map(pickBar));
  rv.lines.forEach(l => rv.series.removePriceLine(l)); rv.levels = [t.open, t.sl, t.tp, t.close].filter(v => v);
  const ln = (price, color, title, lineStyle) => price ? rv.series.createPriceLine({ price, color, lineWidth: 1, lineStyle, axisLabelVisible: true, title }) : null;
  rv.lines = [ln(t.open, t.src === "bot" ? "#89cff0" : "#c9a24a", "entry", 2), ln(t.sl, "#e0574f", "SL", 0), ln(t.tp, "#3fb68b", "TP", 0), ln(t.close, "#8c9098", "exit", 1)].filter(Boolean);
  const snap = x => x - (x % 60), marks = [];
  if (t.openT) marks.push({ time: snap(t.openT), position: t.side === "buy" ? "belowBar" : "aboveBar", color: t.side === "buy" ? "#3fb68b" : "#e0574f", shape: t.side === "buy" ? "arrowUp" : "arrowDown", text: `${t.side} ${t.volume}` });
  if (t.closeT) marks.push({ time: snap(t.closeT), position: t.side === "buy" ? "aboveBar" : "belowBar", color: t.profit >= 0 ? "#3fb68b" : "#e0574f", shape: "circle", text: signed(t.profit) });
  rv.series.setMarkers(marks.sort((a, b) => a.time - b.time));
  try { rv.chart.timeScale().setVisibleRange({ from: (t.openT || t.closeT) - 25 * 60, to: (t.closeT || t.openT) + 25 * 60 }); } catch (e) { rv.chart.timeScale().fitContent(); }
}
function openReplay(src, id) { rv.who = "all"; $$("#rv-who .chip").forEach(x => x.classList.toggle("active", x.dataset.w === "all")); rv.pending = `${src}-${id}`; showTab("review"); }
function openReview() { loadReview(); loadWeek(); }
$("#rv-list").addEventListener("click", e => { const r = e.target.closest("[data-k]"); const t = r && rv.trades.find(x => x.key === r.dataset.k); if (t) showReplay(t); });
function stepReplay(d) {                          // next / previous trade in the replay list (keys on the Keybinds page)
  const list = filteredRv(), i = list.findIndex(t => t.key === rv.sel), n = list[Math.min(list.length - 1, Math.max(0, i + d))];
  if (n && n.key !== rv.sel) { showReplay(n); $(`#rv-list [data-k="${n.key}"]`)?.scrollIntoView({ block: "nearest" }); }
}
[["#rv-days", "d", v => rv.days = +v], ["#rv-mode", "m", v => rv.mode = v], ["#rv-who", "w", v => rv.who = v]].forEach(([box, k, set]) =>
  $(box).addEventListener("click", e => {
    const b = e.target.closest(`[data-${k}]`); if (!b) return;
    set(b.dataset[k]); $$(`${box} .chip`).forEach(x => x.classList.toggle("active", x === b));
    if (k === "w") { renderRvList(); const f = filteredRv(); if (f.length && !f.some(t => t.key === rv.sel)) showReplay(f[0]); } else { rv.sel = null; loadReview(); }
  }));

/* weekly summary: written by Hermes when it's up (rule-based text otherwise), one per ISO week */
const isoWeek = dt => { const d = new Date(Date.UTC(dt.getUTCFullYear(), dt.getUTCMonth(), dt.getUTCDate())), wd = d.getUTCDay() || 7; d.setUTCDate(d.getUTCDate() + 4 - wd);
  const y = d.getUTCFullYear(); return `${y}-W${String(Math.ceil(((d - Date.UTC(y, 0, 1)) / 864e5 + 1) / 7)).padStart(2, "0")}`; };
const weekStart = wk => { const [y, w] = wk.split("-W").map(Number), j4 = new Date(Date.UTC(y, 0, 4)); return new Date(j4.getTime() + ((1 - (j4.getUTCDay() || 7)) + (w - 1) * 7) * 864e5); };
const shiftWeek = (wk, n) => isoWeek(new Date(weekStart(wk).getTime() + n * 7 * 864e5));
function weekLabel(wk) {
  const a = weekStart(wk), b = new Date(a.getTime() + 6 * 864e5), f = x => x.toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
  return `Week ${+wk.split("-W")[1]}, ${f(a)} to ${f(b)}`;
}
async function loadWeek(poll = 0) {
  const cur = isoWeek(new Date()); rv.week = rv.week || shiftWeek(cur, -1);
  $("#rv-week-label").textContent = weekLabel(rv.week); $("#rv-next").disabled = rv.week >= cur;
  const box = $("#rv-week"), src = $("#rv-src"), regen = $("#rv-regen");
  if (rv.weekApi === undefined) { try { await api("/api/review/weeks"); rv.weekApi = true; } catch (e) { rv.weekApi = e.status !== 404; } }
  if (!rv.weekApi) {
    src.hidden = true; regen.disabled = true;
    setHTML(box, `<div class="empty-state compact"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z"/></svg><div><b>Waits for its backend</b>Chat A is building it: every week Hermes reads your trades, the bot's trades and its lessons, and writes what went well and what to fix.</div></div>`);
    return;
  }
  regen.disabled = false;
  let w; try { w = await api(`/api/review/weekly?week=${rv.week}`); } catch (e) { w = null; }
  if (w?.working && poll < 90) { regen.textContent = "Writing…"; regen.classList.add("busy"); setTimeout(() => loadWeek(poll + 1), 2000); return; }
  regen.textContent = "Write it again"; regen.classList.remove("busy");
  if (!w || (!w.went_well?.length && !w.fix?.length)) {
    src.hidden = true;
    setHTML(box, `<div class="empty-state compact"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z"/></svg><div><b>No summary for this week yet</b>Press Write it again and Hermes writes one from this week's trades.</div></div>`);
    return;
  }
  rv.weekGen = w.generated_utc;
  src.hidden = false; src.className = `tag ${w.source === "hermes" ? "hermes" : ""}`; src.textContent = w.source === "hermes" ? "Written by Hermes" : "Rule-based (Hermes was off)";
  const li = a => (a || []).map(x => `<li>${String(x).replace(/</g, "&lt;")}</li>`).join("");
  const nums = (who, n) => n ? `<span><b class="${who}">${WHO[who]}</b> ${n.trades} trade${n.trades === 1 ? "" : "s"}, ${n.win_rate != null ? `${Math.round(n.win_rate)}% won, ` : ""}<b class="num ${cls(n.net)}">${signed(n.net)}</b>${n.profit_factor ? `, profit factor ${(+n.profit_factor).toFixed(2)}` : ""}</span>` : "";
  setHTML(box, `<div class="wk-cols"><div class="wk-col good"><h4>What went well</h4><ul>${li(w.went_well) || "<li class='muted'>Nothing stood out.</li>"}</ul></div>
      <div class="wk-col fix"><h4>What to fix</h4><ul>${li(w.fix) || "<li class='muted'>Nothing to fix this week.</li>"}</ul></div></div>
    <div class="wk-nums">${nums("you", w.numbers?.you)}${nums("bot", w.numbers?.bot)}</div>
    <p class="muted small">Written ${(w.generated_utc || "").replace("T", " ").slice(0, 16)} UTC</p>`);
}
$("#rv-prev").onclick = () => { rv.week = shiftWeek(rv.week, -1); loadWeek(); };
$("#rv-next").onclick = () => { rv.week = shiftWeek(rv.week, 1); loadWeek(); };
$("#rv-regen").onclick = async () => {
  const b = $("#rv-regen"); b.textContent = "Writing…"; b.classList.add("busy");
  try { await api("/api/review/weekly", { method: "POST", body: { week: rv.week } }); loadWeek(1); }
  catch (e) { toast(e.message, true); b.textContent = "Write it again"; b.classList.remove("busy"); }
};

/* ---------- settings backup: the backend writes files to data/backups/ (the window can't download); restoring from a
   file works today through POST /api/settings, and through /api/settings/restore once it exists ---------- */
const bk = { api: undefined, pending: null };
async function loadBackups() {
  const box = $("#bk-list");
  let list; try { list = await api("/api/settings/backups"); bk.api = true; }
  catch (e) { bk.api = e.status !== 404; setHTML(box, `<p class="muted small">${bk.api ? e.message : "Saved backups wait for their backend (Chat A is building it). Restoring from a file and copying already work."}</p>`); $("#bk-now").disabled = !bk.api; return; }
  $("#bk-now").disabled = false;
  setHTML(box, list.length ? `<table class="bk-table"><thead><tr><th>Backup</th><th>Saved</th><th>Size</th><th></th></tr></thead><tbody>${list.map(b => `<tr><td class="num">${b.name}</td><td>${typeof b.time === "number" ? new Date(b.time * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : String(b.time || "").replace("T", " ").slice(0, 16)}</td><td class="num">${b.size != null ? `${(b.size / 1024).toFixed(1)} KB` : ""}</td><td><button class="btn xs" type="button" data-restore="${b.name}">Restore</button></td></tr>`).join("")}</tbody></table>`
    : `<p class="muted small">No backups yet. Back up now saves one.</p>`);
}
$("#bk-now").onclick = async () => {
  try { const r = await api("/api/settings/backup", { method: "POST" }); toast(`Saved ${r.path || r.name}.`); } catch (e) { toast(e.message, true); }
  loadBackups();
};
$("#bk-list").addEventListener("click", async e => {          // two clicks: the first names what will happen
  const b = e.target.closest("[data-restore]"); if (!b) return;
  if (!b.classList.contains("armed")) { b.classList.add("armed", "danger-outline"); b.textContent = "Click again"; clearTimeout(bk.t); bk.t = setTimeout(() => { b.classList.remove("armed", "danger-outline"); b.textContent = "Restore"; }, 4000); return; }
  clearTimeout(bk.t);
  try { const r = await api("/api/settings/restore", { method: "POST", body: { name: b.dataset.restore } }); afterRestore(r); } catch (err) { toast(err.message, true); }
});
async function afterRestore(r) {
  toast(`Restored: ${r.changed?.length ?? 0} setting${r.changed?.length === 1 ? "" : "s"} changed${r.backup ? `; the old ones are in ${r.backup}` : ""}.`);
  try { const s = await api("/api/status"); state.settings = s.settings; keys.synced = snd.synced = false; initFromSettings(true); updateDirty(); } catch (e) {}
  loadBackups();
}
$("#bk-file-btn").onclick = () => $("#bk-file").click();
$("#bk-file").onchange = async e => {
  const f = e.target.files[0]; e.target.value = ""; if (!f) return;
  let obj; try { obj = JSON.parse(await f.text()); obj = obj.settings && typeof obj.settings === "object" ? obj.settings : obj; }
  catch (err) { toast(`${f.name} isn't a settings file (not valid JSON).`, true); return; }
  const s = state.settings, known = Object.keys(obj).filter(k => k in s && k !== "hermes_key" || (k === "hermes_key" && obj[k]));
  const changed = known.filter(k => JSON.stringify(obj[k]) !== JSON.stringify(s[k])), unknown = Object.keys(obj).filter(k => !(k in s));
  bk.pending = { obj, known, name: f.name };
  const box = $("#bk-preview"); box.hidden = false;
  setHTML(box, `<b>${f.name}</b>: ${changed.length ? `${changed.length} setting${changed.length === 1 ? "" : "s"} would change` : "same as your current settings"}${unknown.length ? `, ${unknown.length} unknown ignored` : ""}.
    ${changed.length ? `<ul>${changed.slice(0, 8).map(k => `<li><code>${k}</code> ${k === "hermes_key" ? "••••" : JSON.stringify(s[k])} → ${k === "hermes_key" ? "••••" : JSON.stringify(obj[k])}</li>`).join("")}${changed.length > 8 ? `<li class="muted">and ${changed.length - 8} more</li>` : ""}</ul>` : ""}
    <span class="row gap"><button class="btn xs primary" type="button" id="bk-apply"${changed.length ? "" : " disabled"}>Restore these</button><button class="btn xs" type="button" id="bk-cancel">Cancel</button></span>`);
};
$("#bk-preview").addEventListener("click", async e => {
  if (e.target.id === "bk-cancel") { $("#bk-preview").hidden = true; bk.pending = null; return; }
  if (e.target.id !== "bk-apply" || !bk.pending) return;
  const { obj, known } = bk.pending, pick = Object.fromEntries(known.map(k => [k, obj[k]]));
  try { const r = await api("/api/settings/restore", { method: "POST", body: { settings: pick } }); afterRestore(r); }
  catch (err) {
    if (err.status !== 404) { toast(err.message, true); return; }
    try { state.settings = await api("/api/settings", { method: "POST", body: { ...state.settings, ...pick } }); initFromSettings(true); updateDirty(); toast(`Restored from ${bk.pending.name}.`); }
    catch (err2) { toast(err2.message, true); return; }
  }
  $("#bk-preview").hidden = true; bk.pending = null;
});
$("#bk-copy").onclick = async () => {
  const { hermes_key, ...rest } = state.settings || {}, txt = JSON.stringify(rest, null, 2);
  try { await navigator.clipboard.writeText(txt); toast("Settings copied (without the Hermes API key)."); } catch (e) { toast("Couldn't reach the clipboard.", true); }
};
// Settings > Manual trading: this-PC switches
(() => {
  const t = $("#pref-tpsl");
  t.checked = pref("tpslAlerts", true); t.onchange = () => setPref("tpslAlerts", t.checked);
  $('#set-nav a[href="#set-backup"]').addEventListener("click", loadBackups);
  $$(".rail-btn").forEach(b => b.addEventListener("click", () => b.dataset.tab === "settings" && loadBackups()));
})();

/* ---------- first-run checklist: a Setup pill in the top bar while anything required is missing; the list opens
   by itself once on a fresh install. /api/setup/checklist when it exists, else built from what the app already knows. ---------- */
const FIX = { "/api/fetch": "Download data", "/api/train": "Train", "/api/assistant/setup": "Set up Hermes", "/api/mcp/start": "Start bridge", "/api/history/download": "Download" };
const setup = { data: null, api: undefined, t: 0 };
function localChecklist() {
  const st = state.status, a = state.acct, b = state.brain, j = st?.jobs || {};
  const item = (id, label, ok, detail, action = null, optional = false) => ({ id, label, ok: !!ok, detail, action, optional });
  const items = [
    item("mt5", "MetaTrader 5 open", !!a, a ? `${a.server}` : "Open MetaTrader 5 on this PC and log in."),
    item("account", "Logged in to a trading account", !!a, a ? (a.demo ? "demo account" : "real account") : "Log in inside MT5."),
    item("data", "Price history downloaded", st?.data_ready, st?.data_ready ? `${state.settings?.symbol} M1` : "Downloads the M1 candles the bot learns from.", "/api/fetch"),
    item("model", "Bot trained", st?.model_ready, st?.model_ready ? "model ready" : "Trains the bot on the downloaded history (a few minutes on the RTX 4060).", "/api/train"),
    item("hermes", "Hermes assistant ready", b && (b.local === "ready" || b.hermes_agent), b ? (b.next_step || "ready") : "Checking…", b && b.local !== "ready" ? "/api/assistant/setup" : null, true),
    item("mcp", "MT5 bridge for Hermes Agent", j.mcp?.running, j.mcp?.running ? "running" : "Only needed for Hermes Agent in WSL.", "/api/mcp/start", true),
  ];
  return { items, done: items.filter(i => i.ok).length, total: items.length };
}
async function loadChecklist() {
  let d = null;
  if (setup.api !== false) { try { d = await api("/api/setup/checklist"); setup.api = true; } catch (e) { if (e.status === 404) setup.api = false; } }
  d = d || localChecklist(); setup.data = d;
  const req = d.items.filter(i => !i.optional), reqDone = req.filter(i => i.ok).length;
  const pill = $("#setup-pill"); pill.hidden = reqDone === req.length;
  $("#setup-count").textContent = `${reqDone}/${req.length}`;
  $("#setup-bar").style.width = `${100 * d.items.filter(i => i.ok).length / Math.max(1, d.items.length)}%`;
  $("#setup-sum").textContent = reqDone === req.length ? "Everything you need is set up." : `${req.length - reqDone} required step${req.length - reqDone === 1 ? "" : "s"} left.`;
  setHTML($("#setup-list"), d.items.map(i => `<li class="${i.ok ? "ok" : "todo"}${i.optional ? " optional" : ""}"><span class="ck" aria-hidden="true">${i.ok ? "✓" : ""}</span>
      <div><b>${i.label}${i.optional ? ` <small class="muted">optional</small>` : ""}</b><small>${i.detail || ""}</small></div>
      ${!i.ok && i.action ? `<button class="btn xs" type="button" data-fix="${i.action}">${FIX[i.action] || "Fix"}</button>` : ""}</li>`).join(""));
  if (!pill.hidden && !pref("setupSeen", false) && state.status) { setPref("setupSeen", true); openSetup(); }
}
function openSetup() { $("#setup-drawer").classList.add("open"); $("#setup-pill").setAttribute("aria-expanded", "true"); loadChecklist(); }
function closeSetup() { $("#setup-drawer").classList.remove("open"); $("#setup-pill").setAttribute("aria-expanded", "false"); }
$("#setup-pill").onclick = () => $("#setup-drawer").classList.contains("open") ? closeSetup() : openSetup();
$("#setup-close").onclick = closeSetup;
$("#setup-list").addEventListener("click", async e => {
  const b = e.target.closest("[data-fix]"); if (!b) return; b.disabled = true;
  try { await api(b.dataset.fix, { method: "POST", body: {} }); toast(`${FIX[b.dataset.fix] || "Started"}: working on it.`); if (b.dataset.fix === "/api/fetch" || b.dataset.fix === "/api/train") showTab("train"); }
  catch (err) { toast(err.message, true); b.disabled = false; }
  setTimeout(loadChecklist, 1500);
});
setTimeout(loadChecklist, 4000);
setInterval(() => { if (document.hidden) return; setup.t++; if ($("#setup-drawer").classList.contains("open") || setup.t % 6 === 0) loadChecklist(); }, 5000);

/* ---------- saved objects: keybinds and sounds live in data/settings.json (the server keeps them and backups carry
   them); the window's own storage holds a copy so they work before the first status answer ---------- */
const esc = v => String(v ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const saved = {
  timers: {},
  local(key) { try { return JSON.parse(localStorage.getItem(key)) || null; } catch (e) { return null; } },
  load(key) { const v = state.settings?.[key]; return v && typeof v === "object" && Object.keys(v).length ? v : saved.local(key); },
  save(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) {}
    if (!state.settings || !(key in state.settings)) return;
    state.settings[key] = val;
    clearTimeout(saved.timers[key]);            // one write per burst of slider moves
    saved.timers[key] = setTimeout(() => api("/api/settings", { method: "POST", body: { [key]: val } }).catch(() => {}), 350);
  },
};
function syncSaved() {                           // runs when settings arrive: the server's copy wins, else this PC's moves up
  if (!state.settings) return;
  if (snd.fresh && !snd.migrated) {              // first run of the Sounds page: an old "no bot sounds" choice starts it muted
    snd.migrated = true;
    const srv = state.settings.sounds;
    if (!(srv && Object.keys(srv).length) && state.settings.alert_sound === false) { snd.data.master.mute = true; saved.save("sounds", snd.data); renderMute(); }
  }
  [["keybinds", keys], ["sounds", snd]].forEach(([key, obj]) => {
    if (obj.synced || !(key in state.settings)) return;
    obj.synced = true;
    const srv = state.settings[key];
    if (srv && typeof srv === "object" && Object.keys(srv).length) obj.adopt(srv);
    else if (saved.local(key)) saved.save(key, obj.data);
  });
}

/* ---------- keybinds: every shortcut can be changed on the Keys page. One dispatcher reads them; keys never fire
   while you type in a box or while a dialog is open. ---------- */
const KEY_GROUPS = {
  manual: { label: "Trading on the Manual tab", on: false,
    desc: "These place and close orders. Buy, Sell and the close buttons still ask twice unless one-click is on, and on a real account the first order still asks you to type REAL." },
  app: { label: "Moving around", on: true, desc: "Switch tabs, realign charts, step through replays, mute. Safe to leave on." },
};
const TAB_NAME = { dash: "Market", manual: "Manual", agent: "Agent", review: "Review", train: "Train", quiz: "Quiz", chat: "Hermes", keys: "Keys", sounds: "Sounds", settings: "Settings" };
function pressBtn(sel) {
  const el = $(sel); if (!el || el.disabled) return;
  el.click(); if (el.animate && motionOK()) el.animate([{ transform: "scale(.96)" }, { transform: "none" }], { duration: 160 });
}
function cancelArmed() {                         // Esc on the Manual tab: nothing waits for a second click any more
  disarm();
  $$("#tab-manual .bulk-btns .btn.armed").forEach(b => { b.classList.remove("armed"); b._html = null; });
  clearTimeout(man.bulkT); if (man.chipArm != null) { clearTimeout(man.chipT); man.chipArm = null; }
  loadManPositions();
}
function cycleSym(d) {
  const list = state.settings?.symbols_watch || []; if (list.length < 2) return;
  manPick(list[(list.indexOf(man.symbol) + d + list.length) % list.length]);
}
function realignHere() {
  if (state.tab === "dash") realignChart(true);
  else if (state.tab === "manual" && man.chart) { man.chart.priceScale("right").applyOptions({ autoScale: true }); man.chart.timeScale().scrollToRealTime(); }
  else if (state.tab === "review" && rv.chart) { const t = rv.trades.find(x => x.key === rv.sel); if (t) showReplay(t); }
}
const KEY_ACTIONS = [
  { id: "man.buy", group: "manual", tabs: ["manual"], label: "Buy", short: "Buy", key: "B", run: () => pressBtn("#man-buy") },
  { id: "man.sell", group: "manual", tabs: ["manual"], label: "Sell", short: "Sell", key: "S", run: () => pressBtn("#man-sell") },
  { id: "man.closeAll", group: "manual", tabs: ["manual"], label: "Close all", short: "Close all", key: "Shift+X", run: () => pressBtn('#tab-manual [data-bulk="all"]') },
  { id: "man.closeProfit", group: "manual", tabs: ["manual"], label: "Close profitable", short: "Close +", key: "Shift+P", run: () => pressBtn('#tab-manual [data-bulk="profit"]') },
  { id: "man.closeLoss", group: "manual", tabs: ["manual"], label: "Close negative", short: "Close −", key: "Shift+N", run: () => pressBtn('#tab-manual [data-bulk="loss"]') },
  { id: "man.cancel", group: "manual", tabs: ["manual"], label: "Cancel what's waiting for a second click", short: "Cancel", key: "Escape", run: cancelArmed },
  { id: "man.lotsUp", group: "manual", tabs: ["manual"], label: "One lot step more", short: "Lots +", key: "+", repeat: true, run: () => setVol(+$("#man-vol").value + volStep()) },
  { id: "man.lotsDown", group: "manual", tabs: ["manual"], label: "One lot step less", short: "Lots −", key: "-", repeat: true, run: () => setVol(+$("#man-vol").value - volStep()) },
  { id: "man.nextSym", group: "manual", tabs: ["manual"], label: "Next symbol", short: "Next sym", key: "]", run: () => cycleSym(1) },
  { id: "man.prevSym", group: "manual", tabs: ["manual"], label: "Previous symbol", short: "Prev sym", key: "[", run: () => cycleSym(-1) },
  { id: "man.market", group: "manual", tabs: ["manual"], label: "Order type: market", short: "Market", key: null, run: () => pressBtn('#man-type [data-type="market"]') },
  { id: "man.limit", group: "manual", tabs: ["manual"], label: "Order type: limit", short: "Limit", key: null, run: () => pressBtn('#man-type [data-type="limit"]') },
  { id: "man.stop", group: "manual", tabs: ["manual"], label: "Order type: stop", short: "Stop", key: null, run: () => pressBtn('#man-type [data-type="stop"]') },
  ...Object.entries({ dash: "1", manual: "2", agent: "3", review: "4", train: "5", quiz: "6", chat: "7", keys: "8", sounds: "9", settings: "0" })
    .map(([t, k]) => ({ id: `tab.${t}`, group: "app", label: `Go to ${TAB_NAME[t]}`, short: TAB_NAME[t], key: k, run: () => showTab(t) })),
  { id: "chart.realign", group: "app", tabs: ["dash", "manual", "review"], label: "Realign the chart", short: "Realign", key: "R", run: realignHere },
  { id: "log", group: "app", tabs: ["agent"], label: "Open or close the live log", short: "Log", key: "L", run: () => $("#log-drawer").classList.contains("open") ? closeLog() : openLog() },
  { id: "review.next", group: "app", tabs: ["review"], label: "Next trade in the replay list", short: "Next", key: "ArrowDown", repeat: true, run: () => stepReplay(1) },
  { id: "review.prev", group: "app", tabs: ["review"], label: "Previous trade in the replay list", short: "Prev", key: "ArrowUp", repeat: true, run: () => stepReplay(-1) },
  { id: "hermes", group: "app", label: "Write to Hermes", short: "Hermes", key: "/", run: () => { showTab("chat"); setTimeout(() => $("#chat-input").focus(), 60); } },
  { id: "mute", group: "app", label: "Mute or unmute every sound", short: "Mute", key: "M", run: () => toggleMute() },
  { id: "setup", group: "app", label: "Open the setup checklist", short: "Setup", key: null, run: () => openSetup() },
];
const actById = id => KEY_ACTIONS.find(a => a.id === id);
const RESERVED = { "Tab": "used to move between buttons", "Ctrl+C": "copy", "Ctrl+V": "paste", "Ctrl+X": "cut", "Ctrl+A": "select all",
  "Ctrl+Z": "undo", "Ctrl+Y": "redo", "Ctrl+R": "reload", "Ctrl+Shift+R": "reload", "F5": "reload", "Ctrl+W": "close", "Ctrl+F": "find",
  "Ctrl+P": "print", "Alt+F4": "close the window", "F11": "full screen", "F12": "developer tools", "Ctrl+Shift+I": "developer tools",
  "Ctrl++": "zoom in", "Ctrl+-": "zoom out", "Ctrl+0": "zoom reset" };
const CODE_BASE = { Minus: "-", Equal: "+", BracketLeft: "[", BracketRight: "]", Semicolon: ";", Quote: "'", Comma: ",", Period: ".", Slash: "/",
  Backslash: "\\", Backquote: "`", NumpadAdd: "+", NumpadSubtract: "-", NumpadMultiply: "Num *", NumpadDivide: "Num /", NumpadDecimal: "Num .", NumpadEnter: "Enter", Space: "Space" };
function comboOf(e) {                            // "Ctrl+Alt+Shift+Key": letters as printed on the key, the +/= key is always "+"
  const k = e.key; if (!k || ["Shift", "Control", "Alt", "Meta", "CapsLock", "AltGraph", "OS"].includes(k)) return null;
  let base;
  if (/^Key[A-Z]$/.test(e.code)) base = k.length === 1 && /[a-z]/i.test(k) ? k.toUpperCase() : e.code.slice(3);
  else if (/^Digit\d$/.test(e.code)) base = e.code.slice(5);
  else if (/^Numpad\d$/.test(e.code)) base = `Num ${e.code.slice(6)}`;
  else if (CODE_BASE[e.code]) base = CODE_BASE[e.code];
  else base = k === " " ? "Space" : k.length === 1 ? k.toUpperCase() : k;
  return `${e.ctrlKey || e.metaKey ? "Ctrl+" : ""}${e.altKey ? "Alt+" : ""}${e.shiftKey && base !== "+" ? "Shift+" : ""}${base}`;
}
const splitCombo = c => { const m = String(c).match(/^((?:Ctrl\+|Alt\+|Shift\+)*)(.+)$/); return { mods: m[1].split("+").filter(Boolean), base: m[2] }; };
const KEY_NAME = { ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→", Escape: "Esc", "-": "−", Backspace: "⌫", Delete: "Del", PageUp: "PgUp", PageDown: "PgDn", Insert: "Ins" };
const keyName = b => KEY_NAME[b] || b;
const keyHTML = c => { const { mods, base } = splitCombo(c); return [...mods, keyName(base)].map(x => `<kbd>${esc(x)}</kbd>`).join(""); };
const keyPlain = c => { const { mods, base } = splitCombo(c); return [...mods, keyName(base)].join("+"); };
const overlap = (a, b) => !a.tabs || !b.tabs || a.tabs.some(t => b.tabs.includes(t));

const keys = { data: null, capturing: null, undo: null, filter: "", flash: null, synced: false };
function keysDefaults() {
  return { bindings: Object.fromEntries(KEY_ACTIONS.map(a => [a.id, a.key])),
           groups: { manual: pref("manKeys", KEY_GROUPS.manual.on), app: KEY_GROUPS.app.on } };   // manKeys: the old Manual-tab switch
}
keys.normalize = d => { const def = keysDefaults(); return { bindings: { ...def.bindings, ...(d?.bindings || {}) }, groups: { ...def.groups, ...(d?.groups || {}) } }; };
keys.adopt = d => { keys.data = keys.normalize(d); renderKeys(); renderKeysHint(); };
keys.data = keys.normalize(saved.load("keybinds"));
const bindOf = a => keys.data.bindings[a.id] ?? null;

document.addEventListener("keydown", e => {        // the one place shortcuts run
  if (keys.capturing || e.defaultPrevented || document.querySelector("dialog[open]")) return;
  if (e.target.closest?.("input, textarea, select, [contenteditable='true']")) return;
  const combo = comboOf(e); if (!combo) return;
  const a = KEY_ACTIONS.find(x => keys.data.groups[x.group] && bindOf(x) === combo && (!x.tabs || x.tabs.includes(state.tab)));
  if (!a || (e.repeat && !a.repeat)) return;
  e.preventDefault(); a.run();
});
function renderKeysHint() {                      // the line under the order ticket shows the keys as they are now
  const el = $("#man-keys"); if (!el) return;
  const show = ["man.buy", "man.sell", "man.closeAll", "man.cancel", "man.lotsUp", "man.lotsDown"].map(actById).filter(a => bindOf(a));
  setHTML(el, keys.data.groups.manual
    ? `${show.map(a => `<span class="kh">${keyHTML(bindOf(a))} ${esc(a.short.toLowerCase())}</span>`).join("")} <a href="#" data-goto="keys">change</a>`
    : `Trading keys are off. <a href="#" data-goto="keys">Turn them on or change them</a>`);
}
const scopeText = a => !a.tabs ? "Anywhere" : `${a.tabs.map(t => TAB_NAME[t]).join(", ")} tab${a.tabs.length > 1 ? "s" : ""}`;
function renderKeys() {
  const box = $("#keys-groups"); if (!box) return;
  const f = keys.filter.trim().toLowerCase();
  const html = Object.entries(KEY_GROUPS).map(([g, G]) => {
    const rows = KEY_ACTIONS.filter(a => a.group === g && (!f || `${a.label} ${scopeText(a)} ${bindOf(a) ? keyPlain(bindOf(a)) : ""}`.toLowerCase().includes(f)));
    if (!rows.length) return "";
    const on = keys.data.groups[g];
    return `<div class="panel kg${on ? "" : " off"}" data-g="${g}">
      <div class="panel-head"><h3>${G.label}</h3><label class="switch"><input type="checkbox" data-group="${g}"${on ? " checked" : ""}><span>${on ? "On" : "Off"}</span></label></div>
      <p class="muted small kg-desc">${G.desc}</p>
      <div class="kb-rows">${rows.map(a => { const b = bindOf(a), cap = keys.capturing === a.id;
        return `<div class="kb-row${keys.flash === a.id ? " flash" : ""}" data-a="${a.id}">
          <div class="kb-what"><b>${esc(a.label)}</b><span class="scope">${scopeText(a)}</span></div>
          <button class="keycap-btn${b ? "" : " empty"}${cap ? " capturing" : ""}" type="button" data-bind="${a.id}" aria-label="Change the key for ${esc(a.label)}">${cap ? `<span class="cap-hint">Press a key…</span>` : b ? keyHTML(b) : `<span class="cap-hint">not set</span>`}</button>
          <button class="icon-btn kb-reset" type="button" data-reset="${a.id}" title="Back to ${a.key ? esc(keyPlain(a.key)) : "no key"}"${b === a.key ? " hidden" : ""}>↺</button></div>`; }).join("")}</div></div>`;
  }).join("");
  setHTML(box, html || `<div class="empty-state"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg><div><b>Nothing matches “${esc(keys.filter)}”</b>Try an action (buy, close, replay) or a key (Shift, M).</div></div>`);
  renderKeymap();
  if (keys.capturing) $(`[data-bind="${keys.capturing}"]`)?.focus();
}
const KB_ROWS = [["`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "+"], ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "[", "]", "\\"],
  ["A", "S", "D", "F", "G", "H", "J", "K", "L", ";", "'"], ["Z", "X", "C", "V", "B", "N", "M", ",", ".", "/"]];
const KB_EXTRA = ["Escape", "Space", "ArrowLeft", "ArrowUp", "ArrowDown", "ArrowRight"];
function renderKeymap() {                        // a small keyboard: lit keys do something, labelled with what
  const box = $("#keymap"); if (!box) return;
  const byBase = new Map();
  KEY_ACTIONS.forEach(a => { const c = bindOf(a); if (!c) return; const { mods, base } = splitCombo(c); if (!byBase.has(base)) byBase.set(base, []); byBase.get(base).push({ a, mods }); });
  const onMap = new Set([...KB_ROWS.flat(), ...KB_EXTRA]), extra = [...byBase.keys()].filter(b => !onMap.has(b));
  const cap = b => {
    const list = byBase.get(b) || [], top = list.find(x => x.a.group === "manual" && keys.data.groups.manual) || list.find(x => keys.data.groups[x.a.group]) || list[0];
    const cls = !top ? "" : keys.data.groups[top.a.group] ? ` ${top.a.group}` : " off";
    const tip = list.length ? list.map(x => `${keyPlain(bindOf(x.a))}: ${x.a.label}`).join("\n") : `${keyName(b)} is free`;
    const mod = top ? top.mods.map(m => ({ Shift: "⇧", Ctrl: "Ctrl", Alt: "Alt" }[m])).join(" ") : "";
    return `<button class="kcap${cls}${b === "Space" ? " wide" : ""}" type="button" data-cap="${esc(b)}" title="${esc(tip)}"><b>${esc(keyName(b))}</b>${top ? `<small>${mod ? `${mod} ` : ""}${esc(top.a.short)}${list.length > 1 ? ` +${list.length - 1}` : ""}</small>` : ""}</button>`;
  };
  setHTML(box, KB_ROWS.map((r, i) => `<div class="krow r${i}">${r.map(cap).join("")}</div>`).join("") + `<div class="krow r4">${[...KB_EXTRA, ...extra].map(cap).join("")}</div>`);
}
function keysNote(html, kind = "", undo = false) {
  const el = $("#keys-note"); el.hidden = false; el.className = `keys-note ${kind}`;
  el.innerHTML = `<span>${html}</span>${undo && keys.undo ? `<button class="btn xs" type="button" id="keys-undo">Undo</button>` : ""}`;
  clearTimeout(keys.noteT); keys.noteT = setTimeout(() => { el.hidden = true; }, 9000);
}
function assign(id, combo) {
  const a = actById(id); keys.undo = JSON.stringify(keys.data.bindings);
  const clash = combo ? KEY_ACTIONS.filter(b => b.id !== id && bindOf(b) === combo && overlap(a, b)) : [];
  clash.forEach(b => { keys.data.bindings[b.id] = null; });
  keys.data.bindings[id] = combo; endCapture();
  saved.save("keybinds", keys.data); keys.flash = id; renderKeys(); renderKeysHint();
  clearTimeout(keys.flashT); keys.flashT = setTimeout(() => { keys.flash = null; renderKeys(); }, 1300);
  if (clash.length) keysNote(`${keyHTML(combo)} was on ${clash.map(b => `<b>${esc(b.label)}</b>`).join(", ")}; ${clash.length > 1 ? "those have" : "that has"} no key now.`, "warn", true);
  else keysNote(combo ? `<b>${esc(a.label)}</b> is now ${keyHTML(combo)}.` : `<b>${esc(a.label)}</b> has no key now.`, "", true);
}
function startCapture(id) {
  endCapture(); keys.capturing = id; renderKeys();
  keys.onKey = e => {
    e.preventDefault(); e.stopPropagation();
    const plain = !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey;
    if (e.key === "Escape" && plain) { endCapture(); renderKeys(); return; }
    if ((e.key === "Backspace" || e.key === "Delete") && plain) { assign(id, null); return; }
    const combo = comboOf(e), btn = $(`[data-bind="${id}"]`);
    if (!combo) { if (btn) btn.innerHTML = `<span class="cap-hint">${[e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift"].filter(Boolean).join(" + ")} + …</span>`; return; }
    if (RESERVED[combo]) { keysNote(`${keyHTML(combo)} is ${RESERVED[combo]}. Pick another key.`, "warn"); return; }
    assign(id, combo);
  };
  keys.onDown = ev => { if (!ev.target.closest?.(`[data-bind="${id}"]`)) { endCapture(); renderKeys(); } };
  window.addEventListener("keydown", keys.onKey, true);
  setTimeout(() => document.addEventListener("pointerdown", keys.onDown, true));
}
function endCapture() {
  if (!keys.capturing) return;
  window.removeEventListener("keydown", keys.onKey, true); document.removeEventListener("pointerdown", keys.onDown, true);
  keys.capturing = null;
}
$("#keys-groups").addEventListener("click", e => {
  const b = e.target.closest("[data-bind]");
  if (b) { if (keys.capturing === b.dataset.bind) { endCapture(); renderKeys(); } else startCapture(b.dataset.bind); return; }
  const r = e.target.closest("[data-reset]"); if (r) { const a = actById(r.dataset.reset); assign(a.id, a.key); }
});
$("#keys-groups").addEventListener("change", e => {
  const g = e.target.dataset.group; if (!g) return;
  keys.data.groups[g] = e.target.checked; saved.save("keybinds", keys.data); renderKeys(); renderKeysHint();
  keysNote(`${KEY_GROUPS[g].label}: keys ${e.target.checked ? "on" : "off"}.`);
});
$("#keys-note").addEventListener("click", e => {
  if (e.target.id !== "keys-undo" || !keys.undo) return;
  keys.data.bindings = JSON.parse(keys.undo); keys.undo = null; saved.save("keybinds", keys.data); renderKeys(); renderKeysHint(); keysNote("Undone.");
});
$("#keys-find").addEventListener("input", e => { keys.filter = e.target.value; renderKeys(); });
$("#keys-reset").onclick = () => {
  const b = $("#keys-reset");
  if (!b.classList.contains("armed")) { b.classList.add("armed", "danger-outline"); b.textContent = "Click again to reset"; clearTimeout(keys.resetT); keys.resetT = setTimeout(() => { b.classList.remove("armed", "danger-outline"); b.textContent = "Reset all keys"; }, 4000); return; }
  clearTimeout(keys.resetT); b.classList.remove("armed", "danger-outline"); b.textContent = "Reset all keys";
  keys.undo = JSON.stringify(keys.data.bindings); keys.data.bindings = keysDefaults().bindings;
  saved.save("keybinds", keys.data); renderKeys(); renderKeysHint(); keysNote("Every key is back to its default.", "", true);
};
$("#keymap").addEventListener("click", e => {    // a lit key jumps to its action
  const c = e.target.closest("[data-cap]"); if (!c) return;
  const a = KEY_ACTIONS.find(x => bindOf(x) && splitCombo(bindOf(x)).base === c.dataset.cap);
  if (!a) { keysNote(`${keyHTML(c.dataset.cap)} is free. Click the key next to any action and press it.`); return; }
  if (keys.filter) { keys.filter = ""; $("#keys-find").value = ""; }
  keys.flash = a.id; renderKeys(); $(`.kb-row[data-a="${a.id}"]`)?.scrollIntoView({ block: "center", behavior: motionOK() ? "smooth" : "auto" });
  clearTimeout(keys.flashT); keys.flashT = setTimeout(() => { keys.flash = null; renderKeys(); }, 1300);
});

/* ---------- sounds: every sound the app makes is set on the Sounds page. Built-in sounds are made by the app
   (Web Audio), your own files are kept in data/sounds/ by the server. Pitch moves a built-in sound without changing
   its speed; on your own files it works like a record (lower = slower), which is how the loss bell was made. ---------- */
function envTone(c, d, t, { f, type = "sine", peak = .2, a = .004, dec = .3, f2 = null, fT = .05 }) {
  if (f >= c.sampleRate / 2) return 0;           // above what this context can play
  const o = c.createOscillator(), g = c.createGain(); o.type = type; o.frequency.setValueAtTime(f, t);
  if (f2) o.frequency.exponentialRampToValueAtTime(Math.max(20, f2), t + fT);
  g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(Math.max(0.0002, peak), t + a); g.gain.exponentialRampToValueAtTime(0.0001, t + a + dec);
  o.connect(g); g.connect(d); o.start(t); o.stop(t + a + dec + .03); return a + dec;
}
function noiseHit(c, d, t, { dur = .012, hp = 3000, lp = 0, peak = .05 }) {
  const len = Math.max(1, Math.floor(c.sampleRate * dur)), buf = c.createBuffer(1, len, c.sampleRate), ch = buf.getChannelData(0);
  for (let i = 0; i < len; i++) ch[i] = (Math.random() * 2 - 1) * (1 - i / len);
  const n = c.createBufferSource(), f = c.createBiquadFilter(), g = c.createGain();
  n.buffer = buf; f.type = lp ? "lowpass" : "highpass"; f.frequency.value = Math.min(lp || hp, c.sampleRate / 2 - 100); g.gain.value = peak;
  n.connect(f); f.connect(g); g.connect(d); n.start(t); return dur;
}
const notes = (c, d, t, list, r, L, o = {}) => { list.forEach((f, i) => envTone(c, d, t + i * .16 * L, { f: f * r, peak: .18, a: .02, dec: .2 * L, ...o })); return (list.length - 1) * .16 * L + .22 * L; };
const VOICES = {
  bell: { label: "Bell", note: "small, bright bell", len: .9, play(c, d, t, r, L) {
    const f0 = 1318.5 * r; let end = 0;
    [[1, 1, .9], [2.76, .42, .42], [5.4, .2, .22], [8.93, .09, .12]].forEach(([k, amp, dec]) => { end = Math.max(end, envTone(c, d, t, { f: f0 * k, peak: .26 * amp, a: .003, dec: dec * L })); });
    noiseHit(c, d, t, { hp: 3000 * Math.min(r, 3), peak: .05 }); return end; } },
  chime: { label: "Chime", note: "two rising notes", len: .38, play: (c, d, t, r, L) => notes(c, d, t, [660, 880], r, L) },
  rise: { label: "Rise", note: "three rising notes", len: .54, play: (c, d, t, r, L) => notes(c, d, t, [660, 880, 1100], r, L) },
  drop: { label: "Drop", note: "two falling notes", len: .38, play: (c, d, t, r, L) => notes(c, d, t, [520, 390], r, L) },
  coin: { label: "Coin", note: "quick two-tone ding", len: .5, play(c, d, t, r, L) {
    envTone(c, d, t, { f: 987.8 * r, type: "square", peak: .06, a: .002, dec: .07 * L });
    return .075 * L + envTone(c, d, t + .075 * L, { f: 1318.5 * r, type: "square", peak: .06, a: .002, dec: .42 * L }); } },
  pop: { label: "Pop", note: "soft bubble pop", len: .1, play: (c, d, t, r, L) => envTone(c, d, t, { f: 1100 * r, f2: 320 * r, fT: .06 * L, peak: .32, a: .003, dec: .1 * L }) },
  tick: { label: "Tick", note: "tiny click", len: .03, play(c, d, t, r, L) {
    noiseHit(c, d, t, { dur: .006 * L, hp: 3500 * Math.min(r, 3), peak: .18 }); return envTone(c, d, t, { f: 2400 * r, peak: .1, a: .001, dec: .025 * L }); } },
  knock: { label: "Knock", note: "two wooden knocks", len: .28, play(c, d, t, r, L) {
    [0, .15 * L].forEach(dt => { envTone(c, d, t + dt, { f: 190 * r, f2: 150 * r, fT: .08, peak: .5, a: .002, dec: .12 * L }); noiseHit(c, d, t + dt, { dur: .03, lp: 900 * r, peak: .25 }); });
    return .28 * L; } },
  gong: { label: "Gong", note: "low, long ring", len: 3.2, play(c, d, t, r, L) {
    const f0 = 147 * r; let end = 0;
    [[1, 1, 3.2], [1.004, .6, 3], [1.47, .55, 2.4], [2.09, .45, 1.9], [2.56, .3, 1.5], [3.14, .22, 1.1], [4.18, .12, .8]]
      .forEach(([k, amp, dec]) => { end = Math.max(end, envTone(c, d, t, { f: f0 * k, peak: .2 * amp, a: .012, dec: dec * L })); });
    noiseHit(c, d, t, { dur: .02, lp: 600 * r, peak: .2 }); return end; } },
  alarm: { label: "Alarm", note: "urgent two-tone", len: .84, play(c, d, t, r, L) {
    for (let i = 0; i < 6; i++) envTone(c, d, t + i * .14 * L, { f: (i % 2 ? 660 : 880) * r, type: "square", peak: .07, a: .005, dec: .11 * L });
    return .84 * L; } },
};
const SOUND_BASE = { on: true, sound: "bell", pitch: 0, volume: .8, tone: 1, length: 1 };
const SOUND_EVENTS = [
  { id: "profit", label: "Trade closed in profit", short: "profit", desc: "Take profit hit, or closed early or by hand in profit: yours, the bot's and Hermes'.", def: { volume: .8 } },
  { id: "loss", label: "Stop loss hit or losing close", short: "loss", desc: "Starts as the profit bell, two octaves deeper and softer.", def: { pitch: -24, volume: 1, tone: .43, length: 2.2 } },
  { id: "botOpen", label: "Bot opened a trade", short: "bot opens", def: { sound: "chime", volume: .7 } },
  { id: "orderOk", label: "Your order filled or was placed", short: "order filled", def: { sound: "coin", volume: .6 } },
  { id: "orderFail", label: "Your order was refused", short: "order refused", def: { sound: "drop", volume: .7 } },
  { id: "stopMoved", label: "Stop moved to break-even or trailed", short: "stop moved", desc: "Once per trade for trailing, so it doesn't tick on every step.", def: { on: false, sound: "tick", volume: .6 } },
  { id: "promoted", label: "Bot moved up a stage", short: "stage up", def: { sound: "rise", volume: .7 } },
  { id: "demoted", label: "Bot moved back a stage", short: "stage down", desc: "Its drawdown limit was hit.", def: { sound: "gong", volume: .8, tone: .6 } },
  { id: "feedLost", label: "MT5 or the price feed went quiet", short: "feed lost", desc: "MT5 closed or lost its connection, or prices stopped while the market is open.", def: { sound: "alarm", volume: .5, tone: .7 } },
  { id: "hermes", label: "Hermes replied", short: "Hermes", desc: "Only when you're not looking at the Hermes tab.", def: { sound: "pop", volume: .6 } },
];
const SND_MASTER = { volume: .8, mute: false, gap: .45, quiet: { on: false, from: "23:00", to: "07:00" } };
const evDef = id => ({ ...SOUND_BASE, ...SOUND_EVENTS.find(e => e.id === id).def });
const snd = { data: null, next: 0, synced: false, lostAt: 0 };
snd.fresh = !saved.local("sounds");
snd.normalize = d => {
  const m = d?.master || {}, out = { master: { ...SND_MASTER, ...m, quiet: { ...SND_MASTER.quiet, ...(m.quiet || {}) } }, events: {} };
  SOUND_EVENTS.forEach(e => {
    const c = { ...evDef(e.id), ...(d?.events?.[e.id] || {}) };
    if (!String(c.sound).startsWith("custom:") && !VOICES[c.sound]) c.sound = evDef(e.id).sound;
    ["pitch", "volume", "tone", "length"].forEach(k => { c[k] = Number.isFinite(+c[k]) ? +c[k] : evDef(e.id)[k]; });
    out.events[e.id] = c;
  });
  return out;
};
snd.adopt = d => { snd.data = snd.normalize(d); renderMute(); if (state.tab === "sounds") renderSounds(true); };
snd.data = snd.normalize(saved.load("sounds"));

function quietNow() {
  const q = snd.data.master.quiet; if (!q.on) return false;
  const mins = s => { const [h, m] = String(s).split(":").map(Number); return (h || 0) * 60 + (m || 0); };
  const d = new Date(), now = d.getHours() * 60 + d.getMinutes(), a = mins(q.from), b = mins(q.to);
  return a === b ? false : a < b ? now >= a && now < b : now >= a || now < b;
}
function voiceChain(c, dest, cfg, vol) {          // volume, then (below full) a low-pass for the tone
  const g = c.createGain(); g.gain.value = vol; g.connect(dest);
  if (cfg.tone >= .995) return g;
  const lp = c.createBiquadFilter(); lp.type = "lowpass"; lp.Q.value = .5;
  lp.frequency.value = Math.min(300 * Math.pow(20000 / 300, cfg.tone), c.sampleRate / 2 - 100); lp.connect(g); return lp;
}
function renderInto(c, d, t, cfg, buf) {         // plays the sound into d at t; returns its length in seconds
  const r = 2 ** (cfg.pitch / 12);
  if (buf) {
    const s = c.createBufferSource(); s.buffer = buf; s.playbackRate.value = r;
    const full = buf.duration / r, len = full * Math.min(1, cfg.length);
    if (cfg.length < 1) {                         // shorter: fade out instead of cutting
      const g = c.createGain(); g.gain.setValueAtTime(1, t + Math.max(0, len - .06)); g.gain.linearRampToValueAtTime(0.0001, t + len);
      s.connect(g); g.connect(d); s.start(t); s.stop(t + len + .02);
    } else { s.connect(d); s.start(t); }
    return len;
  }
  return (VOICES[cfg.sound] || VOICES.bell).play(c, d, t, r, cfg.length);
}
async function playSound(cfg, { queue = false, vol = null, evId = null } = {}) {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const c = audioCtx; let buf = null;
    if (String(cfg.sound).startsWith("custom:")) { buf = await customBuffer(cfg.sound.slice(7)); if (!buf) cfg = { ...cfg, sound: evId ? evDef(evId).sound : "bell" }; }
    const t = queue ? Math.max(c.currentTime + .01, snd.next || 0) : c.currentTime + .01;
    if (queue) snd.next = t + snd.data.master.gap;          // two things at once ring one after the other
    return renderInto(c, voiceChain(c, c.destination, cfg, vol ?? cfg.volume * snd.data.master.volume), t, cfg, buf);
  } catch (e) { return 0; }
}
function playEvent(id) {
  const cfg = snd.data?.events?.[id], m = snd.data?.master;
  if (!cfg?.on || !m || m.mute || quietNow()) return;
  playSound(cfg, { queue: true, evId: id });
}
const preview = (cfg, evId) => playSound(cfg, { vol: cfg.volume * snd.data.master.volume, evId });   // always plays: it's a test
function feedLost() { const now = Date.now(); if (now - snd.lostAt < 30000) return; snd.lostAt = now; playEvent("feedLost"); }
function toggleMute(force) {
  const m = snd.data.master; m.mute = force ?? !m.mute; saved.save("sounds", snd.data); renderMute();
  if ($("#snd-mute")) $("#snd-mute").checked = m.mute;
  toast(m.mute ? "Every sound is muted." : "Sounds are back on.");
}
function renderMute() {
  const m = snd.data.master, q = !m.mute && quietNow(), pill = $("#mute-pill");
  pill.hidden = !m.mute && !q;
  $("#mute-txt").textContent = m.mute ? "Muted" : `Quiet till ${m.quiet.to}`;
  pill.title = m.mute ? "Sounds are muted: click to turn them back on" : `Quiet hours: no sounds until ${m.quiet.to}. Click to open Sounds.`;
  const qn = $("#snd-quiet-now"); if (qn) qn.hidden = !quietNow();
}
$("#mute-pill").onclick = () => { if (snd.data.master.mute) toggleMute(false); else showTab("sounds"); };
setInterval(renderMute, 30000); renderMute();

/* your own sounds: kept by the server (data/sounds/); decoded once, then reused */
const lib = { list: [], bufs: new Map(), api: null };
const b64 = buf => { const u = new Uint8Array(buf); let s = ""; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(s); };
const fmtSize = n => n == null ? "" : n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1048576).toFixed(1)} MB`;
async function customBuffer(id) {
  if (lib.bufs.has(id)) return lib.bufs.get(id);
  const row = lib.list.find(r => r.id === id); if (!row) return null;
  try {
    const ab = await (await fetch(row.url || `/api/sounds/${encodeURIComponent(id)}`)).arrayBuffer();
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const buf = await audioCtx.decodeAudioData(ab); lib.bufs.set(id, buf); return buf;
  } catch (e) { return null; }
}
async function libLoad() {
  try { lib.list = await api("/api/sounds"); lib.api = true; } catch (e) { lib.api = e.status === 404 ? false : lib.api; }
  if (state.tab === "sounds") { renderLib(); renderSounds(true); }
}
setTimeout(libLoad, 3000);                        // so an event set to your own sound can play it
async function addSounds(files) {
  if (lib.api === false) { toast("Adding your own sounds needs the newest server. Restart the app after it updates.", true); return; }
  let added = 0;
  for (const f of files) {
    if (f.size > 5 * 1024 * 1024) { toast(`${f.name} is ${(f.size / 1048576).toFixed(1)} MB; the limit is 5 MB.`, true); continue; }
    let data, buf;
    try { data = await f.arrayBuffer(); audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)(); buf = await audioCtx.decodeAudioData(data.slice(0)); }
    catch (e) { toast(`${f.name} couldn't be read as a sound.`, true); continue; }
    try {
      const row = await api("/api/sounds", { method: "POST", body: { name: f.name.replace(/\.[^.]+$/, "").slice(0, 40) || "sound", type: f.type || "", data: b64(data) } });
      lib.bufs.set(row.id, buf); added++;
      toast(`Added “${row.name}” (${buf.duration.toFixed(1)} s). Pick it for any event, or use "Use for…" below.`);
    } catch (e) { toast(`${f.name}: ${e.message}`, true); }
  }
  if (added) await libLoad();
}
function renderLib() {
  const box = $("#snd-lib-list"); if (!box) return;
  $("#snd-lib-store").textContent = lib.api ? "kept in data/sounds/ on this PC" : lib.api === false ? "needs the newest server" : "";
  setHTML(box, lib.list.map(r => {
    const buf = lib.bufs.get(r.id), used = SOUND_EVENTS.filter(e => snd.data.events[e.id].sound === `custom:${r.id}`).map(e => e.short);
    return `<div class="lib-row" data-id="${esc(r.id)}">
      <button class="icon-btn play" type="button" data-lplay="${esc(r.id)}" aria-label="Play ${esc(r.name)}">▶</button>
      <div class="lib-name"><b data-rename="${esc(r.id)}" title="Click to rename">${esc(r.name)}</b><small>${buf ? `${buf.duration.toFixed(1)} s, ` : ""}${fmtSize(r.size)}${used.length ? `, used for ${used.join(", ")}` : ""}</small></div>
      <select data-use="${esc(r.id)}" aria-label="Use ${esc(r.name)} for"><option value="">Use for…</option>${SOUND_EVENTS.map(e => `<option value="${e.id}">${e.label}</option>`).join("")}</select>
      <button class="btn xs danger-outline" type="button" data-ldel="${esc(r.id)}">Delete</button></div>`; }).join("")
    || `<p class="muted small lib-empty">No sounds of your own yet.</p>`);
  lib.list.filter(r => !lib.bufs.has(r.id)).forEach(r => customBuffer(r.id).then(b => { if (b) { clearTimeout(lib.rt); lib.rt = setTimeout(renderLib, 80); } }));
}
function soundOptions(sel) {
  const mine = lib.list.map(r => `<option value="custom:${esc(r.id)}"${sel === `custom:${r.id}` ? " selected" : ""}>${esc(r.name)}</option>`).join("");
  const missing = String(sel).startsWith("custom:") && !lib.list.some(r => `custom:${r.id}` === sel) ? `<option value="${esc(sel)}" selected>${lib.api === null ? "your sound (loading…)" : "missing sound: plays the default"}</option>` : "";
  return `<optgroup label="Built-in">${Object.entries(VOICES).map(([k, v]) => `<option value="${k}"${sel === k ? " selected" : ""}>${v.label}</option>`).join("")}</optgroup>`
    + (mine ? `<optgroup label="Your sounds">${mine}</optgroup>` : "") + missing;
}
const isCustom = c => String(c.sound).startsWith("custom:");
const pitchTxt = p => p === 0 ? "0" : `${p > 0 ? "+" : "−"}${Math.abs(p)}${Math.abs(p) % 12 === 0 ? ` (${Math.abs(p) / 12} oct ${p > 0 ? "up" : "down"})` : ""}`;
const toneTxt = t => t >= .995 ? "full" : t >= .7 ? "bright" : t >= .45 ? "warm" : t >= .25 ? "soft" : "muffled";
const lenTxt = (L, c) => isCustom(c) && L >= 1 ? "full" : `×${L.toFixed(2).replace(/0$/, "")}`;
const sameCfg = (c, id) => { const d = evDef(id); return ["on", "sound", "pitch", "volume", "tone", "length"].every(k => String(c[k]) === String(d[k])); };
const ctl = (k, label, min, max, step, v) => `<label class="snd-ctl"><span>${label} <em data-v="${k}"></em></span><input type="range" min="${min}" max="${max}" step="${step}" value="${v}" data-k="${k}"></label>`;
function renderSounds(force = false) {
  const m = snd.data.master;
  $("#snd-mute").checked = m.mute; $("#snd-vol").value = m.volume; $("#snd-gap").value = m.gap;
  $("#snd-quiet").checked = m.quiet.on; $("#snd-qfrom").value = m.quiet.from; $("#snd-qto").value = m.quiet.to;
  masterLabels();
  const box = $("#snd-rows");
  if (force || !box.childElementCount) {
    box.innerHTML = SOUND_EVENTS.map(e => { const c = snd.data.events[e.id];
      return `<div class="snd-row" data-e="${e.id}">
        <label class="switch" title="Play this sound"><input type="checkbox" data-k="on"${c.on ? " checked" : ""} aria-label="${e.label}: on or off"></label>
        <div class="snd-what"><b>${e.label}</b>${e.desc ? `<small>${e.desc}</small>` : ""}</div>
        <canvas class="snd-wave" aria-hidden="true"></canvas>
        <select data-k="sound" aria-label="Sound for ${e.label}">${soundOptions(c.sound)}</select>
        <div class="snd-ctls">${ctl("pitch", "Pitch", -24, 24, 1, c.pitch)}${ctl("volume", "Volume", 0, 1, .01, c.volume)}${ctl("tone", "Tone", 0, 1, .01, c.tone)}${ctl("length", "Length", .25, 3, .05, c.length)}</div>
        <span class="snd-acts"><button class="icon-btn play" type="button" data-play aria-label="Play ${e.label}">▶</button><button class="icon-btn" type="button" data-sreset title="Back to this event's default">↺</button></span></div>`; }).join("");
    $$("#snd-rows .snd-row").forEach(r => { rowLabels(r); waveSoon(r); });
  }
  if (!$("#snd-voices").childElementCount) setHTML($("#snd-voices"), Object.entries(VOICES).map(([k, v]) => `<button class="voice" type="button" data-voice="${k}"><span class="v-play">▶</span><b>${v.label}</b><small>${v.note}</small></button>`).join(""));
  renderLib(); renderMute();
}
function masterLabels() {
  const m = snd.data.master;
  $("#snd-vol-v").textContent = `${Math.round(m.volume * 100)}%`; $("#snd-gap-v").textContent = `${m.gap.toFixed(2)} s`;
  $("#tab-sounds").classList.toggle("muted-all", m.mute);
}
function rowLabels(row) {
  const id = row.dataset.e, c = snd.data.events[id];
  row.querySelector('[data-v="pitch"]').textContent = pitchTxt(c.pitch);
  row.querySelector('[data-v="volume"]').textContent = `${Math.round(c.volume * 100)}%`;
  row.querySelector('[data-v="tone"]').textContent = toneTxt(c.tone);
  row.querySelector('[data-v="length"]').textContent = lenTxt(c.length, c);
  row.classList.toggle("off", !c.on); row.querySelector("[data-sreset]").hidden = sameCfg(c, id);
}
const waveT = new WeakMap();
function waveSoon(row) { clearTimeout(waveT.get(row)); waveT.set(row, setTimeout(() => drawWave(row), 120)); }
async function drawWave(row) {                   // the sound as it will play: rendered offline, 3 s window, same scale for all
  const cv = row.querySelector("canvas"), id = row.dataset.e, cfg = snd.data.events[id]; if (!cv || !cv.clientWidth) return;
  let src = cfg, buf = null;
  if (isCustom(cfg)) { buf = await customBuffer(cfg.sound.slice(7)); if (!buf) src = { ...cfg, sound: evDef(id).sound }; }
  const r = 2 ** (cfg.pitch / 12), dur = Math.min(3, (buf ? buf.duration / r * Math.min(1, cfg.length) : (VOICES[src.sound] || VOICES.bell).len * cfg.length) + .05);
  const sr = 12000, oc = new OfflineAudioContext(1, Math.max(1, Math.ceil(sr * dur)), sr);
  renderInto(oc, voiceChain(oc, oc.destination, src, cfg.volume), 0, src, buf);
  let data; try { data = (await oc.startRendering()).getChannelData(0); } catch (e) { return; }
  const dpr = window.devicePixelRatio || 1, W = cv.width = Math.round(cv.clientWidth * dpr), H = cv.height = Math.round(cv.clientHeight * dpr);
  const g = cv.getContext("2d"), mid = H / 2, per = sr * 3 / W, scale = (H / 2 - 1) / .5;
  g.clearRect(0, 0, W, H); g.fillStyle = cfg.on ? "#c9a24a" : "#4a525c";
  for (let x = 0; x < W; x++) {
    const a = Math.floor(x * per), b = Math.min(data.length, Math.floor((x + 1) * per)); if (a >= data.length) break;
    let mn = 0, mx = 0; for (let i = a; i < b; i++) { const v = data[i]; if (v < mn) mn = v; else if (v > mx) mx = v; }
    const top = Math.max(0, mid - mx * scale), bot = Math.min(H, mid - mn * scale); g.fillRect(x, top, 1, Math.max(1, bot - top));
  }
}
(() => {                                          // Sounds page > Notifications
  const r = $("#note-secs"), v = $("#note-secs-v"), show = () => { v.textContent = `${noteSecs().toFixed(1)} s`; };
  r.value = noteSecs(); show();
  r.oninput = () => { try { localStorage.setItem("noteSecs", r.value); } catch (e) {} show(); };
  const sc = $("#pref-screen"); sc.checked = pref("screenNotes", true); sc.onchange = () => setPref("screenNotes", sc.checked);
  $("#pref-desktop").onchange = async e => {
    try { state.settings = { ...state.settings, ...(await api("/api/settings", { method: "POST", body: { desktop_alerts: e.target.checked } })) }; }
    catch (err) { toast(err.message, true); }
  };
  $("#note-test").onclick = () => {
    notify({ kind: "tp", title: "Take profit hit", html: `<span class="down">▼</span> sell 0.05 XAUUSD at 2,671.48 <span class="tag you">You</span>`, amount: 14.25, screen: false });
    setTimeout(() => notify({ kind: "sl", title: "Stop loss hit", html: `<span class="up">▲</span> buy 0.02 XAUUSD at 2,663.68 <span class="tag bot">Bot</span>`, amount: -12.6, screen: false }), 160);
    setTimeout(() => notify({ kind: "info", title: "Bot bought 0.02 XAUUSD (paper)", body: "at 2,673.26, stop 2,666.76, target 2,683.66", screen: false }), 320);
  };
})();
function syncNoteSettings() {
  const has = !!state.settings && "desktop_alerts" in state.settings;
  $("#desk-row").hidden = !has; if (has) $("#pref-desktop").checked = !!state.settings.desktop_alerts;
}
function openSounds() { renderSounds(); syncNoteSettings(); if (lib.api !== true) libLoad(); else lib.list.length && renderLib(); }
const saveSounds = () => saved.save("sounds", snd.data);
$("#snd-rows").addEventListener("input", e => {
  const k = e.target.dataset.k, row = e.target.closest(".snd-row"); if (!k || !row || e.target.type !== "range") return;
  snd.data.events[row.dataset.e][k] = +e.target.value; rowLabels(row); waveSoon(row); saveSounds();
});
$("#snd-rows").addEventListener("change", e => {   // letting go of a control plays the result once
  const k = e.target.dataset.k, row = e.target.closest(".snd-row"); if (!k || !row) return;
  const id = row.dataset.e, c = snd.data.events[id];
  if (k === "on") c.on = e.target.checked; else if (k === "sound") c.sound = e.target.value; else c[k] = +e.target.value;
  rowLabels(row); waveSoon(row); saveSounds(); if (k === "sound") renderLib();
  if (k !== "on" || c.on) preview(c, id);
});
$("#snd-rows").addEventListener("click", e => {
  const row = e.target.closest(".snd-row"); if (!row) return;
  const id = row.dataset.e;
  if (e.target.closest("[data-play]")) { preview(snd.data.events[id], id); pulse(e.target.closest("[data-play]")); }
  if (e.target.closest("[data-sreset]")) { snd.data.events[id] = evDef(id); saveSounds(); renderSounds(true); preview(snd.data.events[id], id); renderLib(); }
});
function pulse(el) { if (el?.animate && motionOK()) el.animate([{ transform: "scale(.88)" }, { transform: "none" }], { duration: 220, easing: "cubic-bezier(.34,1.56,.64,1)" }); }
$("#snd-mute").onchange = e => toggleMute(e.target.checked);
$("#snd-vol").oninput = e => { snd.data.master.volume = +e.target.value; masterLabels(); saveSounds(); };
$("#snd-vol").onchange = () => preview(snd.data.events.profit, "profit");
$("#snd-gap").oninput = e => { snd.data.master.gap = +e.target.value; masterLabels(); saveSounds(); };
$("#snd-gap").onchange = () => { snd.next = 0; ["profit", "loss"].forEach(id => playSound(snd.data.events[id], { queue: true, vol: snd.data.events[id].volume * snd.data.master.volume, evId: id })); };
$("#snd-quiet").onchange = e => { snd.data.master.quiet.on = e.target.checked; saveSounds(); renderMute(); };
$("#snd-qfrom").onchange = e => { snd.data.master.quiet.from = e.target.value || "23:00"; saveSounds(); renderMute(); };
$("#snd-qto").onchange = e => { snd.data.master.quiet.to = e.target.value || "07:00"; saveSounds(); renderMute(); };
$("#snd-reset").onclick = () => {
  const b = $("#snd-reset");
  if (!b.classList.contains("armed")) { b.classList.add("armed", "danger-outline"); b.textContent = "Click again to reset"; clearTimeout(snd.resetT); snd.resetT = setTimeout(() => { b.classList.remove("armed", "danger-outline"); b.textContent = "Reset all sounds"; }, 4000); return; }
  clearTimeout(snd.resetT); b.classList.remove("armed", "danger-outline"); b.textContent = "Reset all sounds";
  snd.data = snd.normalize({}); saveSounds(); renderSounds(true); toast("Every sound is back to its default. Your own files are still there.");
};
$("#snd-voices").addEventListener("click", e => {
  const v = e.target.closest("[data-voice]"); if (!v) return;
  preview({ ...SOUND_BASE, sound: v.dataset.voice }); v.classList.add("playing"); setTimeout(() => v.classList.remove("playing"), 500);
});
$("#snd-add").onclick = () => $("#snd-file").click();
$("#snd-file").onchange = e => { const fs = [...e.target.files]; e.target.value = ""; if (fs.length) addSounds(fs); };
(() => {                                          // drag files onto the box
  const z = $("#snd-drop"), on = e => { e.preventDefault(); z.classList.add("over"); }, off = () => z.classList.remove("over");
  z.addEventListener("dragenter", on); z.addEventListener("dragover", on); z.addEventListener("dragleave", off);
  z.addEventListener("drop", e => { e.preventDefault(); off(); const fs = [...(e.dataTransfer?.files || [])]; if (fs.length) addSounds(fs); });
})();
$("#snd-lib-list").addEventListener("click", async e => {
  const p = e.target.closest("[data-lplay]"); if (p) { preview({ ...SOUND_BASE, sound: `custom:${p.dataset.lplay}` }); pulse(p); return; }
  const d = e.target.closest("[data-ldel]");
  if (d) {
    if (!d.classList.contains("armed")) { d.classList.add("armed"); d.textContent = "Click again"; setTimeout(() => { d.classList.remove("armed"); d.textContent = "Delete"; }, 4000); return; }
    const id = d.dataset.ldel;
    try { await api(`/api/sounds/${encodeURIComponent(id)}`, { method: "DELETE" }); } catch (err) { toast(err.message, true); return; }
    const back = SOUND_EVENTS.filter(ev => snd.data.events[ev.id].sound === `custom:${id}`);
    back.forEach(ev => { snd.data.events[ev.id].sound = evDef(ev.id).sound; });
    if (back.length) saveSounds();
    lib.bufs.delete(id); toast(`Deleted.${back.length ? ` ${back.map(ev => ev.label).join(", ")} ${back.length > 1 ? "are" : "is"} back to the built-in sound.` : ""}`);
    await libLoad(); renderSounds(true); return;
  }
  const n = e.target.closest("[data-rename]");
  if (n && !n.querySelector("input")) {
    const id = n.dataset.rename, old = n.textContent;
    n.innerHTML = `<input value="${esc(old)}" maxlength="40" aria-label="New name">`; const i = n.querySelector("input"); i.focus(); i.select();
    const done = async ok => {
      i.onblur = null; const name = i.value.trim();
      if (ok && name && name !== old) { try { await api(`/api/sounds/${encodeURIComponent(id)}/rename`, { method: "POST", body: { name } }); await libLoad(); renderSounds(true); return; } catch (err) { toast(err.message, true); } }
      n.textContent = old;
    };
    i.onkeydown = ev => { if (ev.key === "Enter") { ev.preventDefault(); done(true); } if (ev.key === "Escape") { ev.preventDefault(); done(false); } };
    i.onblur = () => done(true);
  }
});
$("#snd-lib-list").addEventListener("change", e => {
  const s = e.target.closest("[data-use]"); if (!s || !s.value) return;
  const ev = s.value, id = s.dataset.use; s.value = "";
  snd.data.events[ev].sound = `custom:${id}`; snd.data.events[ev].on = true; saveSounds(); renderSounds(true);
  preview(snd.data.events[ev], ev); toast(`“${SOUND_EVENTS.find(x => x.id === ev).label}” now plays your sound.`);
});

/* ---------- boot ---------- */
initChart();
moveRailInd(); document.fonts?.ready.then(moveRailInd);
/* polling: while the window is hidden (minimised or behind others), only what feeds alerts and sounds keeps going
   (bot trades, account, positions, events); screens nobody can see wait and catch up the moment you come back */
const seen = () => !document.hidden;
let bgTick = 0;
pollStatus().then(() => { pollAccount(); loadPositions(); brainStatus(); pollBot(); });
setInterval(() => { bgTick++; if (seen() || bgTick % 2 === 0) pollBot(); }, 2000);            // hidden: every 4 s
loadProgress(); setInterval(() => { if (seen() || bgTick % 6 === 0) loadProgress(); }, 5000);   // hidden: stage moves still get noticed
setInterval(() => seen() && pollStatus(), 2000);
setInterval(pollAccount, 2000);
setInterval(() => { if (seen() && state.tab === "dash" && !state.replay.view) loadBars(); loadPositions(); }, 3000);   // positions feed the top bar and alerts
setInterval(() => seen() && state.tab === "dash" && state.replay.view && loadReplay(), 400);
setInterval(() => seen() && state.tab === "agent" && (pollAgentLog(), loadJournal()), 2000);
setInterval(() => seen() && state.tab === "agent" && loadPlan(), 10000);
setInterval(() => seen() && state.tab === "train" && pollTrainLog(), 1500);
setInterval(() => seen() && state.tab === "quiz" && loadQuiz(), 400);
setInterval(() => seen() && brainStatus(), 15000);
document.addEventListener("visibilitychange", () => {   // back in front: everything catches up at once
  if (document.hidden) return;
  pollStatus(); pollAccount(); loadPositions(); pollBot(); loadProgress(); brainStatus(); renderSessions(); renderMute();
  if (state.tab === "dash" && !state.replay.view) loadBars();
  if (state.tab === "manual") openManual();
});

/* ---------- quiz school (reinforcement learning on pro setups) ---------- */
const quiz = { chart: null, series: null, lines: [], labels: null, picked: new Set(), cells: null, streaks: "",
               mistakeAt: -1, mistakeShown: 0, viewing: null, lastPts: null, pps: 0, st: {} };
const ACT = { buy: "BUY", sell: "SELL", wait: "STAY OUT" };
function quizChart() {
  if (quiz.chart || !window.LightweightCharts) return;
  quiz.chart = LightweightCharts.createChart($("#quiz-chart"), {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: "#8c9098", fontFamily: "IBM Plex Mono, monospace", fontSize: 11 },
    grid: { vertLines: { color: "rgba(255,255,255,.035)" }, horzLines: { color: "rgba(255,255,255,.035)" } },
    rightPriceScale: { borderColor: "#262c34" }, timeScale: { borderColor: "#262c34", timeVisible: true, secondsVisible: false },
  });
  quiz.series = quiz.chart.addCandlestickSeries({ upColor: "#3fb68b", downColor: "#e0574f", borderVisible: false, wickUpColor: "#3fb68b", wickDownColor: "#e0574f" });
  $("#quiz-chart").addEventListener("dblclick", () => { quiz.chart.priceScale("right").applyOptions({ autoScale: true }); quiz.chart.timeScale().fitContent(); });
}
function drawQuizBars(q) {
  quizChart(); if (!quiz.series || !q.bars) return;
  const faded = (q.after || []).map(b => ({ ...b, color: "rgba(140,144,152,.35)", wickColor: "rgba(140,144,152,.35)" }));
  quiz.series.setData([...q.bars, ...faded]);
  quiz.lines.forEach(l => quiz.series.removePriceLine(l));
  quiz.lines = q.trade ? [["Entry", q.trade.entry, "#c9a24a"], ["Stop", q.trade.stop, "#e0574f"], ["Target", q.trade.target, "#3fb68b"]]
    .map(([t, p, c]) => quiz.series.createPriceLine({ price: p, color: c, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: t })) : [];
  const now = q.bars[q.bars.length - 1];
  quiz.series.setMarkers(now ? [{ time: now.time, position: "aboveBar", color: "#c9a24a", shape: "arrowDown", text: "now" }] : []);
  quiz.chart.timeScale().fitContent();
}
function probBars(probs, pick) {
  return `<div class="probs">${["buy", "sell", "wait"].map(a => `<span class="${a === pick ? "pick" : ""}">${a === "wait" ? "stay out" : a}</span><div class="bar"><i style="width:${Math.round((probs?.[a] || 0) * 100)}%"></i></div><span class="num">${Math.round((probs?.[a] || 0) * 100)}%</span>`).join("")}</div>`;
}
function showQuestion(q, title, agent) {
  $("#quiz-q-panel").classList.add("has-q");
  $("#quiz-q-title").textContent = title;
  $("#quiz-q-meta").innerHTML = `${q.bot ? `<span class="tag bot" title="Made from your bot's own ${q.bot.mode || ""} trade #${q.bot.trade_id}">your bot's trade</span> ` : ""}Q${q.id}, ${q.time} server time, ${q.setup_name}`;
  drawQuizBars(q);
  $("#quiz-answer").innerHTML = (agent ? `<p class="small" style="margin:0 0 6px">It answered <b>${ACT[agent.action]}</b>, this sure:</p>${probBars(agent.probs, agent.action)}
      <p class="quiz-verdict down">✗ ${agent.verdict[0].toUpperCase() + agent.verdict.slice(1)} · ${agent.points} points</p>` : "")
    + `<p class="small" style="margin:0"><b>Pro answer: ${ACT[q.answer]}.</b> <span class="muted">${q.explanation}</span></p>`
    + (quiz.viewing ? `<p class="small" style="margin:6px 0 0"><a href="#" id="quiz-back">Back to its latest mistake</a></p>` : "");
  const back = $("#quiz-back"); if (back) back.onclick = e => { e.preventDefault(); quiz.viewing = null; quiz.mistakeAt = -1; loadQuiz(); };
}

/* mastery board: one small square per practice question, drawn on a canvas so thousands stay fast */
function boardLayout(n) {
  const cv = $("#quiz-board"), w = cv.clientWidth || 600;
  let cell = Math.floor(Math.sqrt((w * 200) / Math.max(1, n)));
  cell = Math.max(n > 20000 ? 2 : 4, Math.min(12, cell));                 // tiny squares for huge quizzes
  const gap = cell >= 9 ? 2 : cell >= 4 ? 1 : 0, cols = Math.max(1, Math.floor((w + gap) / (cell + gap))), rows = Math.ceil(n / cols);
  return { cell, gap, cols, rows, w, h: rows * (cell + gap) };
}
function drawBoard() {
  const cv = $("#quiz-board"), st = quiz.streaks, n = st.length;
  if (!n) { cv.style.height = "0px"; $("#quiz-board-meta").textContent = ""; return; }
  const L = boardLayout(n), r = window.devicePixelRatio || 1;
  cv.style.height = L.h + "px"; cv.width = Math.round(L.w * r); cv.height = Math.round(L.h * r);
  const g = cv.getContext("2d"); g.setTransform(r, 0, 0, r, 0, 0); g.clearRect(0, 0, L.w, L.h);
  const miss = quiz.st.mistake && quiz.st.running ? quiz.st.mistake.id : null, ids = quiz.labels?.ids;
  const cur = quiz.st.running ? quiz.st.current : null;
  let curXY = null;
  for (let k = 0; k < n; k++) {
    const x = (k % L.cols) * (L.cell + L.gap), y = Math.floor(k / L.cols) * (L.cell + L.gap), c = st[k];
    g.fillStyle = c === "5" ? "#c9a24a" : c === "u" ? "#4a4f58" : c === "0" ? "#232830" : `rgba(201,162,74,${0.12 + 0.12 * +c})`;
    g.fillRect(x, y, L.cell, L.cell);
    const id = ids ? ids[k] : k + 1;
    const mark = (color) => {                  // outline on normal squares, solid fill when squares are tiny
      if (L.cell < 5) { g.fillStyle = color; g.fillRect(x, y, L.cell, L.cell); }
      else { g.strokeStyle = color; g.lineWidth = 1.5; g.strokeRect(x + .75, y + .75, L.cell - 1.5, L.cell - 1.5); }
    };
    if (miss === id) mark("#e0574f");
    if (quiz.picked.has(id)) mark("#e6e2d8");
    if (cur === id) { curXY = [x, y]; }
  }
  if (curXY) {                                   // the question it is working on right now: baby blue, drawn on top
    const [x, y] = curXY, pad = Math.max(2, L.cell / 3);
    g.fillStyle = "#89cff0"; g.fillRect(x, y, L.cell, L.cell);
    g.strokeStyle = "#89cff0"; g.lineWidth = 1.5; g.strokeRect(x - pad + .75, y - pad + .75, L.cell + 2 * pad - 1.5, L.cell + 2 * pad - 1.5);
  }
  quiz.cells = L;
  const done = [...st].filter(c => c === "5").length, stuck = [...st].filter(c => c === "u").length;
  $("#quiz-board-meta").textContent = `${done.toLocaleString()} of ${n.toLocaleString()} finished${stuck ? ` · ${stuck} stuck (looping)` : ""}`;
}
function boardHit(e) {
  const L = quiz.cells; if (!L) return null;
  const rc = $("#quiz-board").getBoundingClientRect(), x = e.clientX - rc.left, y = e.clientY - rc.top;
  const col = Math.floor(x / (L.cell + L.gap)), row = Math.floor(y / (L.cell + L.gap)), k = row * L.cols + col;
  if (col < 0 || col >= L.cols || k < 0 || k >= quiz.streaks.length) return null;
  return { k, id: quiz.labels ? quiz.labels.ids[k] : k + 1, x, y };
}
$("#quiz-board").addEventListener("mousemove", e => {
  const h = boardHit(e), tip = $("#quiz-tip");
  if (!h) { tip.hidden = true; return; }
  const c = quiz.streaks[h.k], lb = quiz.labels;
  const name = lb ? lb.names[lb.setups[h.k]] : "", ans = lb ? ACT[lb.answers[h.k]] : "";
  const lvl = lb?.difficulty?.[h.k];
  tip.textContent = `Q${h.id} · ${name} · ${ans}${lvl ? ` · ${lvl}` : ""} · ${c === "5" ? "finished" : c === "u" ? "stuck, looping" : `streak ${c}/5`}${quiz.st.current === h.id && quiz.st.running ? " · working on it now" : ""}`;
  tip.hidden = false;
  tip.style.left = Math.min(h.x + 12, $("#quiz-board").clientWidth - tip.offsetWidth - 4) + "px"; tip.style.top = (h.y + 14) + "px";
});
$("#quiz-board").addEventListener("mouseleave", () => { $("#quiz-tip").hidden = true; });
$("#quiz-board").addEventListener("click", async e => {
  const h = boardHit(e); if (!h) return;
  if (quiz.streaks[h.k] !== "5") { quiz.picked.has(h.id) ? quiz.picked.delete(h.id) : quiz.picked.add(h.id); updatePicked(); drawBoard(); }
  try { quiz.viewing = h.id; showQuestion(await api(`/api/quiz/question/${h.id}`), `Question ${h.id}`); } catch (err) {}
});
function updatePicked() {
  const n = quiz.picked.size, b = $("#quiz-focus");
  b.textContent = `Work on picked (${n.toLocaleString()})`; b.disabled = !n;
}
$("#quiz-pick-all").onclick = () => { quiz.picked = new Set(); [...quiz.streaks].forEach((c, k) => { if (c !== "5") quiz.picked.add(quiz.labels ? quiz.labels.ids[k] : k + 1); }); updatePicked(); drawBoard(); };
$("#quiz-pick-clear").onclick = () => { quiz.picked.clear(); updatePicked(); drawBoard(); };

function drawCurve(vals, max) {
  const cv = $("#quiz-curve"), none = !vals || vals.length < 2;
  cv.hidden = none; $("#quiz-curve-empty").hidden = !none;       // empty card until two rounds exist
  if (none) return;
  const r = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight || 150;
  cv.width = Math.round(w * r); cv.height = Math.round(h * r);
  const g = cv.getContext("2d"); g.setTransform(r, 0, 0, r, 0, 0); g.clearRect(0, 0, w, h);
  g.font = "10px 'IBM Plex Mono', monospace"; g.fillStyle = "#8c9098";
  const padL = 44, pad = 8, lo = Math.min(0, ...vals), hi = Math.max(max || 0, ...vals);
  const X = i => padL + i / (vals.length - 1) * (w - padL - pad), Y = v => pad + (hi - v) / (hi - lo || 1) * (h - 2 * pad);
  g.strokeStyle = "rgba(255,255,255,.05)";
  [...new Set([lo, 0, hi])].forEach(v => { g.beginPath(); g.moveTo(padL, Y(v)); g.lineTo(w - pad, Y(v)); g.stroke(); g.fillText(Math.round(v).toLocaleString(), 0, Y(v) + 3); });
  const grad = g.createLinearGradient(0, pad, 0, h); grad.addColorStop(0, "rgba(201,162,74,.28)"); grad.addColorStop(1, "rgba(201,162,74,0)");
  g.beginPath(); vals.forEach((v, i) => i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v)));
  g.lineTo(X(vals.length - 1), Y(lo)); g.lineTo(X(0), Y(lo)); g.closePath(); g.fillStyle = grad; g.fill();
  g.beginPath(); vals.forEach((v, i) => i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))); g.strokeStyle = "#c9a24a"; g.lineWidth = 1.5; g.stroke();
  g.fillStyle = "#c9a24a"; g.beginPath(); g.arc(X(vals.length - 1), Y(vals[vals.length - 1]), 3, 0, 7); g.fill();
}

async function loadQuiz() {
  let r; try { r = await api("/api/quiz/state"); } catch (e) { return; }
  const st = r.state || {}, qz = r.quiz, pol = r.policy;
  quiz.st = st;
  if (qz && quiz.labels?.built !== qz.built) { try { quiz.labels = await api("/api/quiz/labels"); quiz.picked.clear(); updatePicked(); } catch (e) {} }
  renderBuild(r.build, r.job_running); renderBank(r.bank);
  const sp = r.control?.speed ?? 0;
  document.querySelectorAll("#quiz-speed button").forEach(b => b.classList.toggle("active", +b.dataset.speed === sp));
  $("#quiz-status").textContent = r.job_running ? (st.round ? (st.focus ? `working on ${st.focus.length.toLocaleString()} picked` : "running") : "working...")
    : st.done ? (st.stopped ? "stopped" : "finished") : qz ? `${qz.count.toLocaleString()} questions ready` : "no quiz yet";
  // the main button follows the state: Build when there is no quiz yet, Continue once there is
  const hasQuiz = !!qz, busy = !!r.job_running;
  $("#quiz-build").classList.toggle("primary", !hasQuiz);
  $("#quiz-resume").classList.toggle("primary", hasQuiz);
  $("#quiz-resume").disabled = $("#quiz-start").disabled = !hasQuiz || busy;
  $("#quiz-stop").disabled = !busy;
  $$("[data-quiz-build]").forEach(b => { b.disabled = busy; b.textContent = busy ? "Building…" : "Build quiz"; });
  // points and rate
  const P = st.points ?? pol?.points ?? 0, now = performance.now();
  if (quiz.lastPts && r.job_running) { const dt = (now - quiz.lastPts.t) / 1000; if (dt > 0.2) quiz.pps = 0.6 * quiz.pps + 0.4 * (P - quiz.lastPts.p) / dt; }
  quiz.lastPts = { p: P, t: now };
  setNum($("#quiz-points"), P, v => `${v >= 0 ? "+" : "−"}${Math.abs(Math.round(v)).toLocaleString()}`, { flashIt: false });
  $("#quiz-pps").textContent = r.job_running && st.note ? st.note : r.job_running ? `${quiz.pps >= 0 ? "+" : "−"}${Math.abs(Math.round(quiz.pps)).toLocaleString()} points a second · ${(st.rate || 0).toLocaleString()} answers a second` : st.reason ? st.reason : " ";
  $("#quiz-round").textContent = st.round ? `round ${st.round.toLocaleString()}` : "";
  const card = (l, v, extra = "") => `<div class="stat"><span>${l}</span><strong>${v}</strong>${extra}</div>`;
  const prac = st.practice ?? qz?.practice ?? 0, mastered = st.mastered ?? pol?.mastered ?? 0;
  $("#quiz-stats").innerHTML = card("Finished", `${mastered.toLocaleString()}/${prac.toLocaleString()}`, `<div class="bar" style="width:100%;margin-top:6px"><i style="width:${prac ? 100 * mastered / prac : 0}%"></i></div>`)
    + card("Answers", (st.asked ?? pol?.asked ?? 0).toLocaleString()) + card("Right, last 1,000", st.recent_pct != null ? `${st.recent_pct}%` : "–")
    + card("Stuck (looping)", (st.stuck ?? 0).toLocaleString());
  // board
  if (typeof st.streaks === "string") quiz.streaks = st.streaks;
  else if (qz && !quiz.streaks) quiz.streaks = "0".repeat(qz.practice);
  const noBoard = !quiz.streaks.length;
  $("#quiz-board-panel").classList.toggle("is-empty", noBoard); $("#quiz-board-empty").hidden = !noBoard;
  drawBoard();
  drawCurve(st.points_by_round, st.max_round_points);
  $("#quiz-curve-meta").textContent = st.max_round_points ? `best possible +${st.max_round_points.toLocaleString()}` : "";
  // latest mistake, held for at least 2 s so it can be read
  const m = st.mistake;
  if (!quiz.viewing && m && m.bars && m.at !== quiz.mistakeAt && now - quiz.mistakeShown > 2000) {
    quiz.mistakeAt = m.at; quiz.mistakeShown = now;
    showQuestion(m, "Latest mistake", m);
  }
  // hardest
  $("#quiz-hard tbody").innerHTML = (st.hardest || []).map(h => `<tr data-id="${h.id}"><td>${h.id}</td><td>${h.setup_name}</td><td>${ACT[h.answer]}</td><td>${h.right}/${h.asked}</td></tr>`).join("")
    || `<tr><td colspan="4" class="muted">Shows up once the quiz runs.</td></tr>`;
  document.querySelectorAll("#quiz-hard tbody tr[data-id]").forEach(tr => tr.onclick = async () => { quiz.viewing = +tr.dataset.id; showQuestion(await api(`/api/quiz/question/${tr.dataset.id}`), `Question ${tr.dataset.id}`); });
  // exam
  const ex = st.exam || (!r.job_running ? pol?.exam : null);
  $("#quiz-exam-panel").hidden = !ex;
  if (ex) $("#quiz-exam").innerHTML = `<div class="panel-head"><h3>Exam</h3><span class="muted small">${ex.total.toLocaleString()} questions it never trained on</span></div>
    <p style="margin:0 0 6px"><b class="num" style="font-size:20px">${ex.right.toLocaleString()}/${ex.total.toLocaleString()}</b> <span class="muted">right (${ex.pct}%) · guessing gets about 33%</span></p>
    ${ex.by_setup ? `<table class="small" style="width:100%">${Object.entries(ex.by_setup).map(([k, [a, t]]) => `<tr><td>${k}</td><td class="num" style="text-align:right">${a}/${t}</td></tr>`).join("")}</table>` : ""}`;
}
async function startQuiz(body, msg) {
  try { await api("/api/quiz/train", { method: "POST", body }); quiz.mistakeAt = -1; quiz.viewing = null; quiz.lastPts = null; toast(msg); loadQuiz(); }
  catch (e) { toast(e.message, true); }
}
$("#quiz-build").onclick = async () => {
  const all = $("#quiz-all").getAttribute("aria-pressed") === "true";      // All = every usable question in the bank
  const n = all ? 0 : Math.max(40, Math.round(+$("#quiz-n").value || 1000));
  if (!all) $("#quiz-n").value = n;
  try {
    await api("/api/quiz/build", { method: "POST", body: { questions: n } });
    quiz.streaks = "";
    toast(!n ? "Building a quiz from every usable question in the bank." : n > 20000 ? `Building ${n.toLocaleString()} questions: a few minutes. Training a quiz this size takes a while per round; Continue picks up where it left off.`
      : `Finding ${n.toLocaleString()} pro setups in your history. This takes a minute.`);
  } catch (e) { toast(e.message, true); }
};
document.addEventListener("click", e => { if (e.target.closest("[data-quiz-build]")) $("#quiz-build").click(); });
$("#quiz-start").onclick = () => startQuiz({}, "Starting over with a fresh agent. Points are its reward.");
$("#quiz-resume").onclick = () => startQuiz({ resume: true }, "Continuing where it left off.");
$("#quiz-focus").onclick = () => startQuiz({ focus: [...quiz.picked] }, `Working on ${quiz.picked.size.toLocaleString()} picked question(s).`);
$("#quiz-focus-hard").onclick = () => { const ids = (quiz.st.hardest || []).map(h => h.id); if (ids.length) startQuiz({ focus: ids }, `Working on the ${ids.length} hardest.`); };
$("#quiz-stop").onclick = () => api("/api/quiz/control", { method: "POST", body: { stop: true } });
document.querySelectorAll("#quiz-speed button").forEach(b => b.onclick = () => api("/api/quiz/control", { method: "POST", body: { speed: +b.dataset.speed } }).then(loadQuiz));
addEventListener("resize", () => state.tab === "quiz" && drawBoard());
$("#quiz-ask").onclick = async () => {
  $("#quiz-live").textContent = "Asking...";
  try {
    const r = await api("/api/quiz/ask", { method: "POST" });
    $("#quiz-live").innerHTML = `<p class="small" style="margin:0 0 6px">At ${fmt(r.price, state.digits)}: the quiz agent would <b>${ACT[r.action]}</b>.</p>${probBars(r.probs, r.action)}
      ${r.setups.length ? `<div class="setups"><span class="muted small">Pro read:</span>${r.setups.map(x => `<span class="setup-chip">${x}</span>`).join("")}</div>` : `<p class="muted small" style="margin:6px 0 0">No pro setup on the current candle.</p>`}`;
  } catch (e) { $("#quiz-live").textContent = e.message; }
};

/* weak-spot report: what the quiz agent gets stuck on. The panel only shows the copy button; the report text itself
   stays hidden and goes straight to the clipboard (the server still writes it every 5 minutes and after every run). */
const report = { data: null, md: "", loaded: 0 };
function renderReport() {
  const b = $("#quiz-report-copy"), r = report.data;
  b.title = r?.generated ? `Copies the weak-spot report from ${r.generated.slice(11, 16)} UTC` : "The report appears after the quiz has run for a few minutes";
}
async function loadReport(force) {
  try {
    const r = force ? await api("/api/quiz/report", { method: "POST" }) : await api("/api/quiz/report");
    report.data = r.report; report.md = r.markdown || ""; report.loaded = Date.now(); renderReport();
    return true;
  } catch (e) { return false; }
}
$("#quiz-report-copy").onclick = async () => {
  const b = $("#quiz-report-copy"), label = b.querySelector("span"); b.disabled = true;
  await loadReport(false);                     // newest saved report, or build one now if there is a quiz but no report
  if (!report.md && quiz.labels) await loadReport(true);
  b.disabled = false;
  if (!report.md) { toast("No weak-spot report yet. It appears after the quiz has run for a few minutes.", true); return; }
  const ta = $("#quiz-report-text");
  try {
    await navigator.clipboard.writeText(report.md); ta.hidden = true;
    label.textContent = "Copied ✓"; b.classList.add("done"); toast("Report copied. Paste it into your chat with Claude.");
    setTimeout(() => { label.textContent = "Copy report for Claude"; b.classList.remove("done"); }, 1800);
  }
  catch (e) { ta.value = report.md; ta.hidden = false; ta.focus(); ta.select(); toast("Press Ctrl+C to copy the selected report, then paste it to Claude."); }
};
setInterval(() => !document.hidden && state.tab === "quiz" && Date.now() - report.loaded > 30000 && loadReport(false), 5000);

/* wipe: two clicks (the first arms it for 4 seconds) so it can't happen by accident */
let wipeTimer = null;
$("#quiz-wipe").onclick = async () => {
  const b = $("#quiz-wipe");
  if (!b.classList.contains("armed")) {
    b.classList.add("armed"); b.textContent = "Click again to wipe";
    wipeTimer = setTimeout(() => { b.classList.remove("armed"); b.textContent = "Wipe"; }, 4000);
    return;
  }
  clearTimeout(wipeTimer); b.classList.remove("armed"); b.textContent = "Wipe";
  try {
    await api("/api/quiz/wipe", { method: "POST" });
    Object.assign(quiz, { labels: null, streaks: "", st: {}, mistakeAt: -1, viewing: null, lastPts: null });
    quiz.picked.clear(); updatePicked();
    if (quiz.series) { quiz.series.setData([]); quiz.lines.forEach(l => quiz.series.removePriceLine(l)); quiz.lines = []; }
    $("#quiz-q-title").textContent = "Latest mistake"; $("#quiz-q-meta").textContent = "none yet"; $("#quiz-q-panel").classList.remove("has-q");
    $("#quiz-answer").innerHTML = `<div class="empty-state compact"><div><b>All questions wiped</b>Build a new quiz to start again. The trained agent is kept.</div></div>`;
    report.data = null; report.md = ""; renderReport();
    toast("All quiz questions and their progress were deleted. The trained agent is kept.");
    loadQuiz();
  } catch (e) { toast(e.message, true); }
};

/* question bank: an always-on creator keeps adding questions (backend by Chat A); one line + half-year bars while it works */
function renderBank(b) {
  const box = $("#quiz-bank"); box.hidden = !b; if (!b) return;
  const good = (b.good ?? 0).toLocaleString(), yrs = (b.history || "").replace(/(\d{4})-\d\d-\d\d to (\d{4})-\d\d-\d\d/, "$1–$2");
  $("#quiz-bank-txt").textContent = `Question bank: ${good} ready${yrs ? ` (${yrs})` : ""} · ${b.running ? b.stage || "adding questions" : b.watcher ? "always adding new ones" : b.stage || "up to date"}`;
  box.querySelector(".live-dot").hidden = !b.running;
  setHTML($("#quiz-bank-bars"), b.running && (b.finders || []).length ? b.finders.map(f =>
    `<div class="finder ${f.pct >= 1 ? "done" : ""}">${f.label}<div class="bar"><i style="width:${Math.round((f.pct || 0) * 100)}%"></i></div></div>`).join("") : "");
}
$("#quiz-all").onclick = () => {
  const b = $("#quiz-all"), on = b.getAttribute("aria-pressed") !== "true";
  b.setAttribute("aria-pressed", String(on)); b.classList.toggle("active", on); $("#quiz-n").disabled = on;
};

/* build progress: several question finders work through slices of history at once */
function renderBuild(b, running) {
  const box = $("#quiz-build-prog");
  const fresh = b && (b.running ? running : b.done && (b.short || Date.now() - (renderBuild.doneAt || (renderBuild.doneAt = Date.now())) < 20000));
  if (!b || !fresh) { box.hidden = true; if (!b?.done) renderBuild.doneAt = 0; return; }
  if (b.running) renderBuild.doneAt = 0;
  box.hidden = false;
  $("#quiz-build-stage").textContent = b.cached && b.running ? `${b.stage} (using saved finder results)` : b.stage;
  $("#quiz-build-time").textContent = `${Math.round(b.elapsed)}s`;
  const note = $("#quiz-build-note");
  note.hidden = !(b.done && b.short);
  note.textContent = b.short || "";
  $("#quiz-build-bar").style.width = `${Math.round((b.pct || 0) * 100)}%`;
  $("#quiz-finders").innerHTML = (b.finders || []).length && b.running
    ? `<div class="finder" style="grid-column:1/-1">${b.workers} finder(s) working at once</div>` + b.finders.map(f =>
        `<div class="finder ${f.pct >= 1 ? "done" : ""}">${f.label}<div class="bar"><i style="width:${Math.round(f.pct * 100)}%"></i></div></div>`).join("")
    : "";
}
