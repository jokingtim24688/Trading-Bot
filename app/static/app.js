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
  state.tab = name;
  $$(".rail-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach(t => t.classList.toggle("active", t.id === `tab-${name}`));
  moveRailInd();
  if (name === "dash" && state.chart && state.chartAuto && !state.autoT) realignChart(true);
  if (name === "chat") { loadHistory(); loadFacts(); }
  if (name === "agent") { pollAgentLog(); loadJournal(); renderBotTable(); loadPlan(); loadProgress(); loadCalendar(); }
  if (name === "train") pollTrainLog();
  if (name === "quiz") { loadQuiz(); loadReport(false); }
}
$$(".rail-btn").forEach(b => b.onclick = () => showTab(b.dataset.tab));
document.addEventListener("click", e => { const g = e.target.closest("[data-goto]"); if (g) showTab(g.dataset.goto); });

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
    const s = await api("/api/status");
    if (!state.settings) { state.settings = s.settings; initFromSettings(); }
    state.settings = { ...state.settings, ...s.settings };
    const r = s.resources || {};
    if (r.ram_total_gb) { $("#ram-bar").style.width = `${(r.ram_used_gb / r.ram_total_gb) * 100}%`; $("#ram-txt").textContent = `${r.ram_used_gb}/${r.ram_total_gb} GB · app ${r.app_ram_mb} MB`; }
    if (r.vram_total_gb) { $("#vram-bar").style.width = `${(r.vram_used_gb / r.vram_total_gb) * 100}%`; $("#vram-txt").textContent = `${r.vram_used_gb}/${r.vram_total_gb} GB`; }
    else $("#vram-txt").textContent = "n/a";
    const a = s.jobs.agent, pill = $("#agent-pill");
    setHTML(pill, a.running ? `<span class="live-dot"></span>agent running · ${a.args.includes("--live") ? (a.args.includes("--allow-real") ? "REAL" : "demo") : "paper"}` : "agent idle");
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
    const a = await api("/api/account");
    const badge = $("#acct-mode");
    badge.textContent = a.demo ? "demo" : "real"; badge.className = "badge " + (a.demo ? "demo" : "real");
    const eq = $("#equity");
    if (!state.equityShown) { countUp(eq, a.equity); Object.assign(eq, { _v: a.equity, _set: true }); state.equityShown = true; }
    else setNum(eq, a.equity, v => fmt(v));
    const f = $("#floating"); setNum(f, a.profit, v => (v >= 0 ? "+" : "") + fmt(v)); f.style.color = a.profit > 0 ? "var(--up)" : a.profit < 0 ? "var(--down)" : "";
    setNum($("#free-margin"), a.margin_free, v => fmt(v), { flashIt: false });
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
  el.addEventListener("pointermove", e => { if (start && e.buttons && Math.hypot(e.clientX - start[0], e.clientY - start[1]) > 3) chartTouched(); });
  addEventListener("pointerup", () => { start = null; });
  el.addEventListener("dblclick", () => realignChart());
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { moveRailInd(); if (state.chartAuto && !state.autoT && state.tab === "dash") realignChart(true); }, 200); });
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
  state.realignNext = true; state.lastBidShown = null; state.win = newWin();
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
  showQuote(d); applyWindow();
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
    drawBotOverlay();
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
function onChartRange(r) {                       // called while scrolling; loads are single-flight
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
function beep(notes) {
  if (!state.settings?.alert_sound) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    let t = audioCtx.currentTime;
    notes.forEach(f => {
      const o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.type = "sine"; o.frequency.value = f; o.connect(g); g.connect(audioCtx.destination);
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.18, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.22);
      o.start(t); o.stop(t + 0.24); t += 0.16;
    });
  } catch (e) {}
}
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
        toast(`Bot ${t.side.toUpperCase()} ${t.symbol} ${t.lots} @ ${px(t.entry, t.symbol)} · SL ${px(t.sl, t.symbol)} · TP ${px(t.tp, t.symbol)} (${t.mode})`);
        beep([660, 880]);
        $("#bot-card").classList.remove("live"); void $("#bot-card").offsetWidth; $("#bot-card").classList.add("live");
        tradeMoment();
      } else if (before === "open" && t.status === "closed") {
        toast(`Bot closed #${t.id} ${t.symbol} · ${t.exit_reason} · ${signed(t.pnl)}${t.score != null ? ` · ${pts(t.score)} pts` : ""}`, t.pnl < 0);
        beep(t.pnl >= 0 ? [700, 940, 1180] : [520, 390]);
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
  const today = Object.entries(d.stats).filter(([, s]) => s.closed || s.open).map(([m, s]) => `${m} ${signed(s.today_pnl)} · ${pts(s.today_score)} pts`).join(" · ");
  $("#bot-today").textContent = today ? `today: ${today}` : "";
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
    return `<div class="bt${!firstCard && t.id > cardMax ? " enter" : ""}">
      <div class="bt-head"><span class="bt-side ${t.side}">${t.side.toUpperCase()}</span><strong>${t.symbol}</strong><span class="muted small">${t.lots} lots · ${t.mode}${t.prob ? ` · conf ${Math.round(t.prob * 100)}%` : ""}${t.setup ? ` · ${d.setup_names?.[t.setup] || t.setup}` : ""}</span></div>
      <div class="bt-levels"><div><span>Entry</span><strong>${px(t.entry, t.symbol)}</strong></div><div class="sl"><span>Stop</span><strong>${px(t.sl, t.symbol)}</strong></div><div class="tp"><span>Target</span><strong>${px(t.tp, t.symbol)}</strong></div></div>
      <div class="bt-foot"><span class="num flashable ${cls(t.pnl)}" data-pl="${t.id}">${signed(t.pnl)}${rNow != null ? ` <span class="muted">(${rNow >= 0 ? "+" : ""}${rNow.toFixed(2)}R)</span>` : ""}</span>
        <span class="row gap"><button class="btn xs" data-follow="${t.id}" title="Put the bot's stop into the sizer to size your own copy">Size mine</button><button class="btn xs" data-copy="${t.id}">Copy levels</button></span></div>
      <p class="muted small" style="margin:6px 0 0">opened ${(t.open_utc || "").replace("T", " ").slice(0, 16)} UTC · #${t.id}</p></div>`;
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
    mk(t.entry, "#c9a24a", `bot ${t.side}`, 2); mk(t.sl, "#e0574f", "bot SL", 0); mk(t.tp, "#3fb68b", "bot TP", 0);
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
    <td>${(t.open_utc || "").replace("T", " ").slice(0, 16)}</td><td>${t.symbol}</td><td class="${t.side === "buy" ? "up" : "down"}">${t.side}</td><td>${t.lots}</td>
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
    const ps = await api("/api/positions"), box = $("#positions");
    $("#pos-count").textContent = ps.length ? `${ps.length} open` : "";
    const seen = state.posSeen; state.posSeen = new Set(ps.map(p => p.ticket));
    if (!ps.length) { setHTML(box, `<div class="empty-state compact">${ICON.list}<div><b>Nothing open</b>Positions from the bot, Hermes or your own MT5 trades show up here.</div></div>`); return; }
    setHTML(box, ps.map(p => `<div class="pos ${p.side}${seen && !seen.has(p.ticket) ? " enter" : ""}">
      <span><strong>${p.symbol}</strong><span class="tag ${p.owner}">${{ bot: "Bot", hermes: "Hermes", you: "You" }[p.owner] || "You"}</span> <span class="muted">${p.side} ${p.volume}</span></span>
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
  if (p.event?.type === "promoted") { toast(`The bot moved up to ${p.event.to}.`); beep([660, 880, 1100]); }
  if (p.event?.type === "demoted") { toast(`Drawdown limit hit. The bot moved back to ${p.event.to}.`, true); beep([520, 390]); }
  if (prevStage && prevStage !== p.stage.id) loadPlan();
  const idx = p.stages.findIndex(x => x.id === p.stage.id);
  $("#ladder").innerHTML = p.stages.map((x, i) => `<li class="${i < idx ? "done" : i === idx ? "current" : ""} ${x.mode === "real" ? "real" : ""}" title="${x.note}"><b>${x.label}</b>${i < idx ? "passed" : i === idx ? "now" : ""}</li>`).join("");
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
  $("#gate").innerHTML = `<h4>${p.stage.label} <span class="muted small">· ${p.stage.note} · since ${p.since.replace("T", " ").slice(0, 16)} UTC</span></h4>${rows}
    <div class="actions">${action}${idx > 0 ? `<button class="btn xs" id="demote">Move back a stage</button>` : ""}</div>`;
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
  if (!r || !r.generated) return;
  const chips = [...(r.blocked_hours || []).map(h => `skip ${String(h).padStart(2, "0")}:00 UTC`),
    ...(r.min_confidence ? [`confidence ≥ ${r.min_confidence}`] : []), ...(r.disabled_side ? [`no ${r.disabled_side} trades`] : []),
    ...(r.blocked_setups || []).map(k => `skip ${state.bot.data?.setup_names?.[k] || k}`)];
  $("#learned").innerHTML = `<div class="learned-rules">${chips.length ? chips.map(c => `<span class="rule-chip">${c}</span>`).join("") : `<span class="muted small">No filters yet. Nothing has lost consistently enough to block.</span>`}</div>
    <p class="muted small" style="margin:0">From ${r.trades_analyzed} closed trades · updated ${r.generated.replace("T", " ")} UTC · ${state.settings?.use_learned ? "applied to new entries" : "not applied (Settings)"} · saved to <code>.claude/skills/m1-bot-lessons/</code></p>
    ${(r.reasons || []).length ? `<ul class="small muted" style="margin:6px 0 0;padding-left:18px">${r.reasons.map(x => `<li>${x}</li>`).join("")}</ul>` : ""}`;
}
$("#learn-now").onclick = async () => { try { const r = await api("/api/learn", { method: "POST" }); renderLearned(r.rules); toast("Lessons updated from the bot's trades."); } catch (e) { toast(e.message, true); } };

async function loadPlan() {
  const box = $("#plan");
  let p;
  try { p = await api(`/api/plan?mode=${state.mode === "paper" ? "paper" : state.mode}`); }
  catch (e) { box.innerHTML = `<p class="empty">${e.status === 503 ? "Open MT5 to see the per-trade plan." : e.message}</p>`; return; }
  const c = p.currency || "", d = p.digits ?? 2, money = v => `${fmt(v)} ${c}`;
  const cell = (label, val, wide) => `<div class="${wide ? "wide" : ""}"><span>${label}</span><strong>${val}</strong></div>`;
  box.innerHTML = `<h3>Each ${p.symbol} trade right now (${p.mode})</h3><div class="plan-grid">
    ${cell("Balance", money(p.balance))}${cell("Leverage", p.ref_leverage ? `1:${p.leverage} real · exits at 1:${p.ref_leverage}` : `1:${p.leverage}`)}
    ${cell("Stake (margin)", money(p.stake))}${cell("Lots", p.lots)}
    ${cell(`Stop: −${p.sl_pct}% of stake`, `−${money(p.sl_money)}<small>${Number(p.sl_dist).toFixed(d)} from entry</small>`)}
    ${cell(`Target: +${p.tp_pct}% of stake`, `+${money(p.tp_money)}<small>${Number(p.tp_dist).toFixed(d)} from entry</small>`)}
    ${cell("Reward : risk", `${p.reward_risk} : 1`)}${cell("TP scale (200% → 50%)", `${money(p.tp_scale[0])} → ${money(p.tp_scale[1])} stake`)}${cell("Spread now", Number(p.spread_px).toFixed(d))}${cell("Margin for 1.00 lot", money(p.margin_per_lot))}
    ${cell(`If all ${state.settings.max_open_trades} open trades stop out`, `−${money(p.worst_case_all_open)} (${p.worst_case_pct}% of balance)`, true)}</div>
    ${p.forced_min ? `<p class="plan-note warn">${state.settings.stake_pct}% of balance is ${money(p.stake_target)}, below the ${p.volume_min}-lot minimum, so each trade uses the minimum lot (stake ${money(p.stake)}).</p>` : ""}
    ${p.worst_case_pct > 5 ? `<p class="plan-note warn">That worst case is more than 5% of the balance. Consider fewer open trades or a larger balance.</p>` : ""}
    ${p.spread_px > p.sl_dist * 0.35 ? `<p class="plan-note warn">The spread is over 35% of the stop distance right now, so the bot will skip entries until it narrows.</p>` : ""}`;
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
  try { await api("/api/agent/start", { method: "POST", body: {} }); msg.textContent = `Started at the ${state.progress?.stage?.label || state.mode} stage. It acts when the next M1 candle closes.`; pollStatus(); pollAgentLog(); }
  catch (e) { msg.textContent = e.message; msg.className = "note err"; }
};
$("#agent-stop").onclick = async () => { await api("/api/agent/stop", { method: "POST" }); $("#agent-msg").textContent = "Stopped. Any open position keeps its server-side stop loss and take profit."; pollStatus(); };
// console panels show a small "nothing yet" card until their job has written something
function showLog(which, log, stickToEnd) {
  if (!log || !log.trim()) return;
  const pre = $(`#${which}-log`); $(`#${which}-empty`).hidden = true; pre.hidden = false;
  if (pre.textContent === log) return;
  const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
  pre.textContent = log;
  if (!stickToEnd || atEnd) pre.scrollTop = pre.scrollHeight;
}
async function pollAgentLog() {
  try { const r = await api("/api/jobs/agent/log?lines=300"); showLog("agent", r.log, true); } catch (e) {}
}
async function loadJournal() {
  try {
    const rows = await api("/api/journal?limit=200"), last = state.journalLast;
    state.journalLast = rows.reduce((mx, r) => (r.time_utc || "") > mx ? r.time_utc : mx, last || "");
    setHTML($("#journal tbody"), rows.reverse().map(r => `<tr${last != null && (r.time_utc || "") > last ? ` class="enter"` : ""}><td>${(r.time_utc || "").replace("T", " ").slice(0, 19)}</td><td>${r.mode}</td>
      <td class="ev-${r.event}">${r.event}</td><td>${r.side || ""}</td><td>${r.lots || ""}</td><td>${r.price ? Number(r.price).toFixed(state.digits) : ""}</td>
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
function addMsg(role, text, tools, animate = false) {
  const d = document.createElement("div"); d.className = `msg ${role}${animate ? " enter" : ""}`; d.textContent = text;
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
  $("#suggest").classList.add("hidden"); $("#chat-intro").classList.add("hidden"); addMsg("user", text, null, true);
  const pending = addMsg("assistant pending", "Thinking", null, true);
  try {
    const r = await api("/api/chat", { method: "POST", body: { text } }); pending.remove(); addMsg("assistant", r.reply, r.tools, true); loadFacts();
    if ((r.reply || "").startsWith("⚠")) brainStatus();       // set-up messages: refresh the status line
  }
  catch (e) { pending.remove(); addMsg("assistant", `Couldn't reach the assistant: ${e.message}`, null, true); }
}
$("#chat-form").onsubmit = e => { e.preventDefault(); const i = $("#chat-input"); const t = i.value; i.value = ""; i.style.height = ""; send(t); };
$("#chat-input").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chat-form").requestSubmit(); } });
$("#chat-input").addEventListener("input", e => { e.target.style.height = "auto"; e.target.style.height = e.target.scrollHeight + "px"; });
$$("#suggest button").forEach(b => b.onclick = () => send(b.textContent));
// status pill + next step + Set up button; the local model can install/start/download itself (backend by Chat A)
const LOCAL_TEXT = { not_installed: "Ollama not installed", stopped: "Ollama not running", no_model: "Model not downloaded", error: "Set-up problem", starting: "Starting Ollama…" };
async function brainStatus() {
  let s; try { s = await api("/api/assistant/status"); } catch (e) { return; }
  const el = $("#brain-state"), next = $("#brain-next"), setup = $("#brain-setup");
  const useAgent = s.backend_setting === "hermes_agent" || (s.backend_setting === "auto" && s.hermes_agent);
  const localReady = s.local ? s.local === "ready" : s.ollama;
  let text, live = false;
  if (useAgent && s.hermes_agent) { text = "Hermes Agent · connected"; live = true; }
  else if (useAgent) text = "Hermes Agent not running";
  else if (localReady) { text = `${s.model} on RTX 4060`; live = true; }
  else if (s.installing) text = "Installing Ollama…";
  else if (s.local === "downloading") text = `Downloading ${Math.round((s.download_pct || 0) * 100)}%`;
  else text = LOCAL_TEXT[s.local] || "Ollama not running";
  setHTML(el, live ? `<span class="live-dot"></span>${text}` : text);
  el.className = "pill " + (live ? "live" : "warn");
  const step = !live && s.next_step ? s.next_step : "";
  if (next.textContent !== step) next.textContent = step;
  next.hidden = !step;
  setup.hidden = useAgent || s.installing || !["not_installed", "stopped", "no_model", "error"].includes(s.local);
  const dl = s.local === "downloading" && !useAgent;
  $("#brain-dl").hidden = !dl; if (dl) $("#brain-bar").style.width = `${Math.round((s.download_pct || 0) * 100)}%`;
  clearTimeout(state.brainT);                    // poll faster while it is busy setting itself up
  if (!useAgent && (s.installing || ["downloading", "starting"].includes(s.local))) state.brainT = setTimeout(brainStatus, 2000);
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
  const msg = $("#settings-msg");
  try { state.settings = await api("/api/settings", { method: "POST", body }); msg.textContent = "Saved to data/settings.json"; initFromSettings(true); brainStatus(); loadPlan(); }
  catch (err) { msg.textContent = err.message; }
  if (msg.animate && motionOK()) msg.animate([{ opacity: 0, transform: "translateX(-4px)" }, { opacity: 1, transform: "none" }], { duration: 260, easing: "cubic-bezier(.22,1,.36,1)" });
};
// Settings > Display: reduce animations on this PC only (kept in the window's local storage, never sent to the server)
(() => {
  const el = $("#pref-motion"); el.checked = document.documentElement.classList.contains("reduce-motion");
  el.onchange = () => { document.documentElement.classList.toggle("reduce-motion", el.checked); try { localStorage.setItem("reduceMotion", el.checked ? "1" : "0"); } catch (e) {} };
})();


function initFromSettings(keepSymbol = false) {
  const s = state.settings;
  if (!keepSymbol || !(s.symbols_watch || []).includes(state.symbol)) state.symbol = s.symbols_watch?.[0] || s.symbol;
  renderChips(); fillSettings();
  bindSlider("#thr", "threshold", "", 2); bindSlider("#stake", "stake_pct", "% of balance", 2);
  $("#stake").addEventListener("change", () => setTimeout(loadPlan, 300));
  $$(".sym-txt").forEach(x => x.textContent = s.symbol); $("#days-txt").textContent = s.days_history;
  loadBars();
}

/* ---------- boot ---------- */
initChart();
moveRailInd(); document.fonts?.ready.then(moveRailInd);
pollStatus().then(() => { pollAccount(); loadPositions(); brainStatus(); pollBot(); });
setInterval(pollBot, 2000);
loadProgress(); setInterval(loadProgress, 5000);
setInterval(pollStatus, 2000);
setInterval(pollAccount, 2000);
setInterval(() => state.tab === "dash" && !state.replay.view && (loadBars(), loadPositions()), 3000);
setInterval(() => state.tab === "dash" && state.replay.view && loadReplay(), 400);
setInterval(() => state.tab === "agent" && (pollAgentLog(), loadJournal()), 2000);
setInterval(() => state.tab === "agent" && loadPlan(), 10000);
setInterval(() => state.tab === "train" && pollTrainLog(), 1500);
setInterval(() => state.tab === "quiz" && loadQuiz(), 400);
setInterval(brainStatus, 15000);

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
  $("#quiz-q-meta").textContent = `Q${q.id} · ${q.time} server time · ${q.setup_name}`;
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
  renderBuild(r.build, r.job_running);
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
  const n = Math.max(40, Math.min(100000, Math.round(+$("#quiz-n").value || 1000)));
  $("#quiz-n").value = n;
  try {
    await api("/api/quiz/build", { method: "POST", body: { questions: n } });
    quiz.streaks = "";
    toast(n > 20000 ? `Building ${n.toLocaleString()} questions: a few minutes. Training a quiz this size takes a while per round; Continue picks up where it left off.`
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
setInterval(() => state.tab === "quiz" && Date.now() - report.loaded > 30000 && loadReport(false), 5000);

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
