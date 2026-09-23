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
  if (name === "agent") { pollAgentLog(); loadJournal(); renderBotTable(); loadPlan(); }
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
        toast(`Bot closed #${t.id} ${t.symbol} · ${t.exit_reason} · ${signed(t.pnl)}${t.r_multiple != null ? ` (${t.r_multiple >= 0 ? "+" : ""}${t.r_multiple}R)` : ""}`, t.pnl < 0);
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
  const box = $("#bot-now"), open = d.open;
  const running = [...document.querySelectorAll("#agent-pill")].some(p => p.classList.contains("live"));
  const today = Object.entries(d.stats).filter(([, s]) => s.closed || s.open).map(([m, s]) => `${m} ${signed(s.today_pnl)}`).join(" · ");
  $("#bot-today").textContent = today ? `today: ${today}` : "";
  if (!open.length) {
    $("#bot-card").classList.remove("live");
    box.innerHTML = `<p class="empty">${running ? "The bot is watching and currently flat." : "The bot isn't running."} When it enters you'll get an alert, and its entry, stop and target are drawn on the chart.</p>`;
    return;
  }
  $("#bot-card").classList.add("live");
  box.innerHTML = open.slice().reverse().map(t => {
    const risk = Math.abs(t.entry - t.sl0), rNow = t.price != null && risk ? ((t.side === "buy" ? t.price - t.entry : t.entry - t.price) / risk) : null;
    return `<div class="bt">
      <div class="bt-head"><span class="bt-side ${t.side}">${t.side.toUpperCase()}</span><strong>${t.symbol}</strong><span class="muted small">${t.lots} lots · ${t.mode}${t.prob ? ` · conf ${Math.round(t.prob * 100)}%` : ""}</span></div>
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
  d.open.filter(t => t.symbol === state.symbol).forEach(t => {
    const mk = (price, color, title, style) => price && state.bot.lines.push(state.series.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }));
    mk(t.entry, "#c9a24a", `bot ${t.side}`, 2); mk(t.sl, "#e0574f", "bot SL", 0); mk(t.tp, "#3fb68b", "bot TP", 0);
  });
  const r = state.barRange; if (!r) { state.series.setMarkers([]); return; }
  const snap = t => t - (t % 60), inRange = t => t && t >= r[0] && t <= r[1] + 60;
  const marks = [];
  d.recent.filter(t => t.symbol === state.symbol).forEach(t => {
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
    wins: a.wins + (s.win_pct || 0) * s.closed / 100 }), { closed: 0, open: 0, net_pnl: 0, today_pnl: 0, total_r: 0, wins: 0 });
  const win = m ? S.win_pct : (S.closed ? (100 * S.wins / S.closed).toFixed(1) : null);
  const avgR = m ? S.avg_r : (S.closed ? (S.total_r / S.closed).toFixed(2) : null);
  const card = (label, val, c = "") => `<div class="stat"><span>${label}</span><strong class="${c}">${val ?? "—"}</strong></div>`;
  $("#bt-stats").innerHTML = card("Closed trades", S.closed) + card("Open", S.open) + card("Win rate", win != null ? `${win}%` : "—")
    + card("Net P/L", signed(S.net_pnl), cls(S.net_pnl)) + card("Today", signed(S.today_pnl), cls(S.today_pnl))
    + card("Total R", S.total_r != null ? `${S.total_r >= 0 ? "+" : ""}${Number(S.total_r).toFixed(2)}` : "—", cls(S.total_r))
    + card("Avg R / trade", avgR) + (m ? card("Profit factor", S.profit_factor) : "");
  $("#bt-table tbody").innerHTML = rows.map(t => `<tr class="${t.status === "open" ? "open-row" : ""}"><td>${t.id}</td><td>${t.mode}</td>
    <td>${(t.open_utc || "").replace("T", " ").slice(0, 16)}</td><td>${t.symbol}</td><td class="${t.side === "buy" ? "up" : "down"}">${t.side}</td><td>${t.lots}</td>
    <td>${px(t.entry, t.symbol)}</td><td>${px(t.sl, t.symbol)}</td><td>${px(t.tp, t.symbol)}</td>
    <td>${t.status === "open" ? "open" : px(t.exit, t.symbol)}</td><td>${t.exit_reason || ""}</td>
    <td class="${cls(t.pnl)}">${t.status === "open" ? "" : signed(t.pnl)}</td><td class="${cls(t.r_multiple)}">${t.r_multiple ?? ""}</td><td>${t.prob ? Math.round(t.prob * 100) + "%" : ""}</td></tr>`).join("")
    || `<tr><td colspan="14" class="muted">No bot trades yet${m ? ` in ${m} mode` : ""}. Start the agent and every trade it takes is recorded here, including ones that hit stop or target while the app was closed.</td></tr>`;
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
$$(".seg-btn").forEach(b => b.onclick = () => { if (b.disabled) return; state.mode = b.dataset.mode; $$(".seg-btn").forEach(x => x.classList.toggle("active", x === b)); loadPlan(); });

async function loadPlan() {
  const box = $("#plan");
  let p;
  try { p = await api(`/api/plan?mode=${state.mode === "paper" ? "paper" : state.mode}`); }
  catch (e) { box.innerHTML = `<p class="empty">${e.status === 503 ? "Open MT5 to see the per-trade plan." : e.message}</p>`; return; }
  const c = p.currency || "", d = p.digits ?? 2, money = v => `${fmt(v)} ${c}`;
  const cell = (label, val, wide) => `<div class="${wide ? "wide" : ""}"><span>${label}</span><strong>${val}</strong></div>`;
  box.innerHTML = `<h3>Each ${p.symbol} trade right now (${p.mode})</h3><div class="plan-grid">
    ${cell("Balance", money(p.balance))}${cell("Leverage", `1:${p.leverage}`)}
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
  try { state.settings = await api("/api/settings", { method: "POST", body }); $("#settings-msg").textContent = "Saved to data/settings.json"; initFromSettings(true); brainStatus(); loadPlan(); }
  catch (err) { $("#settings-msg").textContent = err.message; }
};
$("#unlock-real").onchange = e => {
  const b = $('.seg-btn[data-mode="real"]'); b.disabled = !e.target.checked;
  b.querySelector("small").textContent = e.target.checked ? "real money" : "locked";
  $("#real-hint").textContent = e.target.checked ? "Real mode is unlocked for this session. Starting it still asks you to confirm." : "Real money is locked so a stray click can't start it. Unlock it in Settings → Trading when you're ready.";
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
setInterval(pollStatus, 2000);
setInterval(pollAccount, 2000);
setInterval(() => state.tab === "dash" && (loadBars(), loadPositions()), 3000);
setInterval(() => state.tab === "agent" && (pollAgentLog(), loadJournal()), 2000);
setInterval(() => state.tab === "agent" && loadPlan(), 10000);
setInterval(() => state.tab === "train" && pollTrainLog(), 1500);
setInterval(brainStatus, 15000);
