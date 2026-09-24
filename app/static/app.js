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
  if (name === "agent") { pollAgentLog(); loadJournal(); renderBotTable(); loadPlan(); loadProgress(); }
  if (name === "train") pollTrainLog();
  if (name === "quiz") loadQuiz();
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
async function loadBars() {
  if (state.replay?.view) return loadReplay();
  if (!state.series || !state.symbol) return;
  try {
    const d = await api(`/api/bars?symbol=${encodeURIComponent(state.symbol)}&count=300`);
    state.digits = d.digits; state.lastBid = d.bid;
    state.series.applyOptions({ priceFormat: { type: "price", precision: d.digits, minMove: d.point } });
    state.series.setData(d.bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
    $("#q-sym").textContent = d.symbol; $("#q-bid").textContent = fmt(d.bid, d.digits);
    $("#q-spr").textContent = Math.round((d.ask - d.bid) / d.point);
    $("#chart-msg").classList.add("hidden");
    state.barRange = d.bars.length ? [d.bars[0].time, d.bars[d.bars.length - 1].time] : null;
    drawBotOverlay();
    if (!$("#sz-entry").value) $("#sz-entry").placeholder = fmt(d.bid, d.digits).replace(/,/g, "");
  } catch (e) {
    const m = $("#chart-msg"); m.textContent = e.message; m.classList.remove("hidden");
  }
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
  state.symbol = sym; renderChips(); state.series && state.series.setData([]); loadBars(); sizeTrade();
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
      } else if (before === "open" && t.status === "closed") {
        toast(`Bot closed #${t.id} ${t.symbol} · ${t.exit_reason} · ${signed(t.pnl)}${t.score != null ? ` · ${pts(t.score)} pts` : ""}`, t.pnl < 0);
        beep(t.pnl >= 0 ? [700, 940, 1180] : [520, 390]);
      }
    }
  }
  state.bot.known = now;
  renderBotCard(); drawBotOverlay();
  if (state.tab === "agent") renderBotTable();
}

function renderBotCard() {
  const d = state.bot.data; if (!d) return;
  const box = $("#bot-now"), open = d.open.filter(t => (t.mode === "replay") === !!state.replay?.view);
  const today = Object.entries(d.stats).filter(([, s]) => s.closed || s.open).map(([m, s]) => `${m} ${signed(s.today_pnl)} · ${pts(s.today_score)} pts`).join(" · ");
  $("#bot-today").textContent = today ? `today: ${today}` : "";
  if (!open.length) {
    $("#bot-card").classList.remove("live");
    const rp = state.replay?.view && state.replay.last?.total ? state.replay.last : null;
    const a = rp ? { ...rp, mode: "replay", bar: (rp.bar_time_utc || "").slice(11, 16) } : d.agent;
    const pct = v => v == null ? "–" : `${v < 0.1 ? (v * 100).toFixed(1) : Math.round(v * 100)}%`;
    const need = a ? (a.need ?? a.threshold) : 1;
    box.innerHTML = a ? `<div class="watch">
        <div class="watch-head"><span class="live-dot"></span><strong>Watching ${state.settings?.symbol || ""} · ${a.mode || ""}</strong><span class="muted small">${a.bar ? "candle " + a.bar : ""}</span></div>
        ${a.p_buy != null ? `<div class="conf"><span>Buy</span><div class="bar"><i style="width:${Math.min(100, a.p_buy / Math.max(need, .001) * 100)}%"></i></div><span class="num">${pct(a.p_buy)}</span></div>
        <div class="conf"><span>Sell</span><div class="bar"><i style="width:${Math.min(100, a.p_sell / Math.max(need, .001) * 100)}%"></i></div><span class="num">${pct(a.p_sell)}</span></div>
        <p class="muted small" style="margin:4px 0 0">Needs ${pct(need)} to enter${a.practice ? " (practice: its best ~10% of readings)" : ""} · ${a.open ?? 0}/${a.max_open ?? "–"} open</p>` : ""}
        ${a.setups?.length ? `<div class="setups"><span class="muted small">Pro read:</span>${a.setups.map(x => `<span class="setup-chip">${x}</span>`).join("")}</div>` : ""}
        <p class="small" style="margin:8px 0 0"><b>${a.decision}</b>${a.reason ? ` · <span class="muted">${a.reason}</span>` : ""}</p></div>`
      : `<p class="empty">The bot isn't running. Start it on the Agent tab. When it enters you'll get an alert, and its entry, stop and target are drawn on the chart.</p>`;
    return;
  }
  $("#bot-card").classList.add("live");
  const now = state.replay?.view ? state.replay.last : d.agent;
  const proRead = now?.setups?.length ? `<div class="setups" style="margin:0 0 8px"><span class="muted small">Pro read:</span>${now.setups.map(x => `<span class="setup-chip">${x}</span>`).join("")}</div>` : "";
  box.innerHTML = proRead + open.slice().reverse().map(t => {
    const risk = Math.abs(t.entry - t.sl0), rNow = t.price != null && risk ? ((t.side === "buy" ? t.price - t.entry : t.entry - t.price) / risk) : null;
    return `<div class="bt">
      <div class="bt-head"><span class="bt-side ${t.side}">${t.side.toUpperCase()}</span><strong>${t.symbol}</strong><span class="muted small">${t.lots} lots · ${t.mode}${t.prob ? ` · conf ${Math.round(t.prob * 100)}%` : ""}${t.setup ? ` · ${d.setup_names?.[t.setup] || t.setup}` : ""}</span></div>
      <div class="bt-levels"><div><span>Entry</span><strong>${px(t.entry, t.symbol)}</strong></div><div class="sl"><span>Stop</span><strong>${px(t.sl, t.symbol)}</strong></div><div class="tp"><span>Target</span><strong>${px(t.tp, t.symbol)}</strong></div></div>
      <div class="bt-foot"><span class="num ${cls(t.pnl)}">${signed(t.pnl)}${rNow != null ? ` <span class="muted">(${rNow >= 0 ? "+" : ""}${rNow.toFixed(2)}R)</span>` : ""}</span>
        <span class="row gap"><button class="btn xs" data-follow="${t.id}" title="Put the bot's stop into the sizer to size your own copy">Size mine</button><button class="btn xs" data-copy="${t.id}">Copy levels</button></span></div>
      <p class="muted small" style="margin:6px 0 0">opened ${(t.open_utc || "").replace("T", " ").slice(0, 16)} UTC · #${t.id}</p></div>`;
  }).join("");
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
  const m = state.bot.filter, rows = d.recent.filter(t => !m || t.mode === m);
  const S = m ? d.stats[m] : Object.values(d.stats).reduce((a, s) => ({ closed: a.closed + s.closed, open: a.open + s.open,
    net_pnl: a.net_pnl + s.net_pnl, today_pnl: a.today_pnl + s.today_pnl, total_r: a.total_r + s.total_r,
    wins: a.wins + (s.win_pct || 0) * s.closed / 100, score: a.score + (s.score || 0), today_score: a.today_score + (s.today_score || 0),
    sl_hits: a.sl_hits + (s.sl_hits || 0), early_exits: a.early_exits + (s.early_exits || 0) }),
    { closed: 0, open: 0, net_pnl: 0, today_pnl: 0, total_r: 0, wins: 0, score: 0, today_score: 0, sl_hits: 0, early_exits: 0 });
  const win = m ? S.win_pct : (S.closed ? (100 * S.wins / S.closed).toFixed(1) : null);
  const avgR = m ? S.avg_r : (S.closed ? (S.total_r / S.closed).toFixed(2) : null);
  const card = (label, val, c = "") => `<div class="stat"><span>${label}</span><strong class="${c}">${val ?? "—"}</strong></div>`;
  const avgScore = S.closed ? (S.score / S.closed).toFixed(1) : "—";
  $("#bt-stats").innerHTML = card("Score", pts(S.score), cls(S.score)) + card("Today's score", pts(S.today_score), cls(S.today_score))
    + card("Avg points / trade", avgScore) + card("Stops hit / early exits", `${S.sl_hits} / ${S.early_exits}`)
    + card("Closed trades", S.closed) + card("Open", S.open) + card("Win rate", win != null ? `${win}%` : "—")
    + card("Net P/L", signed(S.net_pnl), cls(S.net_pnl)) + card("Today", signed(S.today_pnl), cls(S.today_pnl))
    + card("Total R", S.total_r != null ? `${S.total_r >= 0 ? "+" : ""}${Number(S.total_r).toFixed(2)}` : "—", cls(S.total_r))
    + card("Avg R / trade", avgR) + (m ? card("Profit factor", S.profit_factor) : "");
  $("#bt-table tbody").innerHTML = rows.map(t => `<tr class="${t.status === "open" ? "open-row" : ""}"><td>${t.id}</td><td>${t.mode}</td>
    <td>${(t.open_utc || "").replace("T", " ").slice(0, 16)}</td><td>${t.symbol}</td><td class="${t.side === "buy" ? "up" : "down"}">${t.side}</td><td>${t.lots}</td>
    <td>${px(t.entry, t.symbol)}</td><td>${px(t.sl, t.symbol)}</td><td>${px(t.tp, t.symbol)}</td>
    <td>${t.status === "open" ? "open" : px(t.exit, t.symbol)}</td><td>${t.exit_reason || ""}</td>
    <td class="${cls(t.pnl)}">${t.status === "open" ? "" : signed(t.pnl)}</td><td class="${cls(t.r_multiple)}">${t.r_multiple ?? ""}</td><td class="${cls(t.score)}">${t.status === "open" ? "" : pts(t.score)}</td><td>${t.prob ? Math.round(t.prob * 100) + "%" : ""}</td><td class="small">${t.setup ? (d.setup_names?.[t.setup] || t.setup) : ""}</td></tr>`).join("")
    || `<tr><td colspan="16" class="muted">No bot trades yet${m ? ` in ${m} mode` : ""}. Start the agent and every trade it takes is recorded here, including ones that hit stop or target while the app was closed.</td></tr>`;
}
$("#bt-filter").addEventListener("click", e => {
  const b = e.target.closest("[data-m]"); if (!b) return;
  state.bot.filter = b.dataset.m; $$("#bt-filter .chip").forEach(x => x.classList.toggle("active", x === b)); renderBotTable();
});

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
      <span><strong>${p.symbol}</strong><span class="tag ${p.owner}">${{ bot: "Bot", hermes: "Hermes", you: "You" }[p.owner] || "You"}</span> <span class="muted">${p.side} ${p.volume}</span></span>
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
$("#btn-history").onclick = async () => { try { await api("/api/history/download", { method: "POST", body: JSON.stringify({ years: +$("#hist-years").value }) }); lastTrainJob = "history"; pollTrainLog(); pollStatus(); } catch (e) { toast(e.message, true); } };
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
  try { state.settings = await api("/api/settings", { method: "POST", body }); $("#settings-msg").textContent = "Saved to data/settings.json"; initFromSettings(true); brainStatus(); loadPlan(); }
  catch (err) { $("#settings-msg").textContent = err.message; }
};


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
  cell = Math.max(4, Math.min(12, cell));
  const gap = cell >= 9 ? 2 : 1, cols = Math.max(1, Math.floor((w + gap) / (cell + gap))), rows = Math.ceil(n / cols);
  return { cell, gap, cols, rows, w, h: rows * (cell + gap) };
}
function drawBoard() {
  const cv = $("#quiz-board"), st = quiz.streaks, n = st.length;
  if (!n) { cv.style.height = "0px"; $("#quiz-board-meta").textContent = ""; return; }
  const L = boardLayout(n), r = window.devicePixelRatio || 1;
  cv.style.height = L.h + "px"; cv.width = Math.round(L.w * r); cv.height = Math.round(L.h * r);
  const g = cv.getContext("2d"); g.setTransform(r, 0, 0, r, 0, 0); g.clearRect(0, 0, L.w, L.h);
  const miss = quiz.st.mistake && quiz.st.running ? quiz.st.mistake.id : null, ids = quiz.labels?.ids;
  for (let k = 0; k < n; k++) {
    const x = (k % L.cols) * (L.cell + L.gap), y = Math.floor(k / L.cols) * (L.cell + L.gap), c = st[k];
    g.fillStyle = c === "5" ? "#c9a24a" : c === "u" ? "#4a4f58" : c === "0" ? "#232830" : `rgba(201,162,74,${0.12 + 0.12 * +c})`;
    g.fillRect(x, y, L.cell, L.cell);
    const id = ids ? ids[k] : k + 1;
    if (miss === id) { g.strokeStyle = "#e0574f"; g.lineWidth = 1.5; g.strokeRect(x + .75, y + .75, L.cell - 1.5, L.cell - 1.5); }
    if (quiz.picked.has(id)) { g.strokeStyle = "#e6e2d8"; g.lineWidth = 1.5; g.strokeRect(x + .75, y + .75, L.cell - 1.5, L.cell - 1.5); }
  }
  quiz.cells = L;
  const done = [...st].filter(c => c === "5").length, unclear = [...st].filter(c => c === "u").length;
  $("#quiz-board-meta").textContent = `${done.toLocaleString()} of ${n.toLocaleString()} finished${unclear ? ` · ${unclear} unclear` : ""}`;
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
  tip.textContent = `Q${h.id} · ${name} · ${ans} · ${c === "5" ? "finished" : c === "u" ? "unclear" : `streak ${c}/5`}`;
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
  const cv = $("#quiz-curve"), r = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight || 150;
  cv.width = Math.round(w * r); cv.height = Math.round(h * r);
  const g = cv.getContext("2d"); g.setTransform(r, 0, 0, r, 0, 0); g.clearRect(0, 0, w, h);
  g.font = "10px 'IBM Plex Mono', monospace"; g.fillStyle = "#8c9098";
  if (!vals || vals.length < 2) { g.fillText("Fills in as rounds finish.", 4, h / 2); return; }
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
  const sp = r.control?.speed ?? 0;
  document.querySelectorAll("#quiz-speed button").forEach(b => b.classList.toggle("active", +b.dataset.speed === sp));
  $("#quiz-status").textContent = r.job_running ? (st.round ? (st.focus ? `working on ${st.focus.length.toLocaleString()} picked` : "running") : "working...")
    : st.done ? (st.stopped ? "stopped" : "finished") : qz ? `${qz.count.toLocaleString()} questions ready` : "no quiz yet";
  // points and rate
  const P = st.points ?? pol?.points ?? 0, now = performance.now();
  if (quiz.lastPts && r.job_running) { const dt = (now - quiz.lastPts.t) / 1000; if (dt > 0.2) quiz.pps = 0.6 * quiz.pps + 0.4 * (P - quiz.lastPts.p) / dt; }
  quiz.lastPts = { p: P, t: now };
  $("#quiz-points").textContent = `${P >= 0 ? "+" : "−"}${Math.abs(P).toLocaleString()}`;
  $("#quiz-pps").textContent = r.job_running ? `${quiz.pps >= 0 ? "+" : "−"}${Math.abs(Math.round(quiz.pps)).toLocaleString()} points a second · ${(st.rate || 0).toLocaleString()} answers a second` : st.reason ? st.reason : " ";
  $("#quiz-round").textContent = st.round ? `round ${st.round.toLocaleString()}` : "";
  const card = (l, v, extra = "") => `<div class="stat"><span>${l}</span><strong>${v}</strong>${extra}</div>`;
  const prac = st.practice ?? qz?.practice ?? 0, mastered = st.mastered ?? pol?.mastered ?? 0;
  $("#quiz-stats").innerHTML = card("Finished", `${mastered.toLocaleString()}/${prac.toLocaleString()}`, `<div class="bar" style="width:100%;margin-top:6px"><i style="width:${prac ? 100 * mastered / prac : 0}%"></i></div>`)
    + card("Answers", (st.asked ?? pol?.asked ?? 0).toLocaleString()) + card("Right, last 1,000", st.recent_pct != null ? `${st.recent_pct}%` : "–")
    + card("Unclear", (st.unclear ?? 0).toLocaleString());
  // board
  if (typeof st.streaks === "string") quiz.streaks = st.streaks;
  else if (qz && !quiz.streaks) quiz.streaks = "0".repeat(qz.practice);
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
$("#quiz-build").onclick = async () => { try { await api("/api/quiz/build", { method: "POST", body: { questions: +$("#quiz-n").value } }); quiz.streaks = ""; toast("Finding pro setups in your history. This takes a minute."); } catch (e) { toast(e.message, true); } };
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
