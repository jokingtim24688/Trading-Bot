"""App settings, stored on disk in data/settings.json (nothing important lives only in RAM)."""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
PATH = DATA / "settings.json"
BACKUPS = DATA / "backups"

DEFAULTS = {
    "symbol": "XAUUSD",
    "symbols_watch": ["XAUUSD", "EURUSD", "US500", "NAS100"],
    "terminal_path": "",
    "threshold": 0.15,                     # model confidence needed to enter; pick from the Train results
    "risk_pct": 0.5,                       # default risk for YOUR manual trades in the Market-tab sizer
    # Bot money rules (all relative to each trade's stake = its margin)
    "stake_pct": 0.1,                      # % of balance per trade; minimum lot if that's smaller
    "sl_pct_of_stake": 25.0,               # stop when 25% of the stake is lost
    "tp_pct_small": 200.0,                 # take profit at +200% of stake for small stakes...
    "tp_pct_large": 50.0,                  # ...easing to +50% for large stakes
    "small_stake": 0.0,                    # 0 = auto: the minimum lot's stake gets tp_pct_small
    "large_stake": 0.0,                    # 0 = auto: 100x minimum (1.00 lot on XAUUSD) gets tp_pct_large
    "ref_leverage": 100,                   # stop/target distances as if leverage were 1:100 (0 = broker's real)
    "max_open_trades": 10,                  # bot trades open at the same time (not a per-session total)
    "early_exit": True,
    "auto_promote_demo": True,             # move Paper -> Demo by itself once the Paper gate is passed
    "bot_mode": "auto",                    # "auto" = Full Auto (trades on its own) | "copilot" = asks you first
    "copilot_seconds": 30,                 # how long a co-pilot proposal waits for Approve / Skip
    "copilot_auto_execute": False,         # when that time runs out: True = send it anyway, False = skip it
    "display_timezone": "",                # the Bot tab's clock and times (IANA name, e.g. America/New_York; "" = this PC's)
    "trade_hours_start": 0,                # server-time hours new bot entries are allowed [start, end); 0-24 = all day
    "trade_hours_end": 24,                 # (the 23:00-01:00 rollover pause, when spreads blow out, still applies)
    "use_learned": True,                   # apply the rules the bot learned from its own trades
    "quiz_filter": False,
    "quiz_refresh": True,
    "quiz_workers": 0,                     # question creators when Build quiz is pressed (0 = up to 10)
    "quiz_bank_auto": True,                # one question creator keeps the question bank up to date at all times                     # quiz: question finders working at once (0 = automatic: cores and free RAM)                  # quiz: silently refresh finished questions so it doesn't forget them                  # only enter when the quiz agent (Quiz tab) picks the same side
    "quiz_speed": 0,                       # quiz questions per second (0 = max)
    "learn_every": 50,                     # re-learn after this many new closed trades                    # bot may close a trade before its stop when the model turns against it
    "sl_score_mult": 1.5,                  # score: a stop-loss hit counts this many times worse than an early close
    "paper_balance": 10000.0,
    "label_horizon": 1440,                 # bars (1 day) a training label may take to hit its stop/target
    "practice": True,                      # Paper/Replay: trade the model's top-10% setups instead of the threshold
    "replay_speed": 20,                    # candles per second in Replay
    "days_history": 365,
    "alert_sound": True,                   # beep when the bot opens or closes a trade
    "point": 0.01,
    # Manual tab: automatic stop moves for your own trades (points; 0 = off). Applied to new manual orders.
    "manual_be_points": 0,                 # once a trade is this many points up, move its stop to entry + 2 points
    "manual_trail_points": 0,              # the stop follows the price at this distance, only ever tightening
    "desktop_alerts": False,               # also show Windows' own pop-up on a TP/SL hit (the app shows its own at the top right)
    # Pause around big news (economic calendar): the bot opens no new trades this long before/after a release
    "news_pause": True,
    "news_before_min": 15,
    "news_after_min": 15,
    "news_currencies": ["USD"],            # gold moves on US news
    "news_impact": ["High"],               # High / Medium / Low
    # Manual tab: refuse market orders when the spread is wider than this many points (0 = no limit)
    "manual_max_spread": 80,
    # Honest backtest (Agent tab): costs on top of the candles' spread
    "backtest_commission": 7.0,            # round-trip commission per 1.0 lot (set 0 if your broker charges none)
    "backtest_slippage": 10,               # points of slippage on every market fill
    # Daily backup of the app's data (app/backup.py)
    "backup_daily": True,
    "backup_dir": "",                      # "" = data/backups/full; a OneDrive/USB folder survives a dead disk
    "backup_keep": 14,
    # Telegram alerts on your phone (your own bot from @BotFather; see app/telegram.py)
    "telegram_enabled": False,
    "telegram_token": "",
    "telegram_chat_id": "",                # filled in by "Find my chat" after you message your bot
    "telegram_events": ["tp", "sl", "open", "close", "watchdog"],   # also possible: "be", "trail"
    "telegram_commands": True,
    # MT5 from a Mac / Linux: the bridge running next to MT5 on a Windows PC or VM (agent/mt5_remote.py)
    "mt5_bridge_url": "",                  # e.g. http://192.168.1.20:18812 ("" = none; Windows uses MT5 directly)
    "mt5_bridge_token": "",             # answer /prof /loss /total (only from your saved chat)
    # Quiz: which school the Quiz tab trains ("stocks" = MT5 setups, "trenching" = Solana meme coins, "combined")
    "quiz_mode": "trenching",
    "quiz_min_creators": 2,                # question creators kept running while the app is open (per school)
    # Trenching data growth (sol/trench.py): keeps pulling real PumpSwap/new-pool candles while the app is open,
    # and retrains the crew by itself once enough new real data has come in, so improvement is visible without
    # pressing Train every time.
    "trench_download_min": 20,             # minutes between background downloads (the first one runs at once)
    "trench_download_pools": 40,           # fresh pools looked at per download round (was a fixed 24, one-shot)
    "trench_auto_retrain": True,
    "trench_auto_retrain_gap": 400,        # new real labelled moments since the last training before it retrains
    # Solana trenching bot (sol/): paper by default; live needs SOL_PRIVATE_KEY in .env and a typed LIVE
    "sol_trade_size_sol": 0.1,
    "sol_max_open": 3,
    "sol_tp_pct": 30.0,
    "sol_trail_pct": 10.0,
    "sol_timeout_min": 20,
    "sol_buy_threshold": 0.78,
    "sol_model_floor": 0.65,
    "sol_min_liq_usd": 5000,
    "sol_scan_s": 10,
    "sol_paper_start": 10.0,
    # Each agent's own tweet monitor (sol/tweets.py). Off until a key is saved; a find still goes through every
    # filter (rug rules -> model floor -> debate -> subagents), it only decides which coins get looked at first.
    "x_provider": "off",                   # "off" | "twitterapi" (twitterapi.io) | "x" (official X API v2)
    "x_api_key": "",                       # stays on this machine; routes only ever report whether it is set
    "x_scan_s": 300,                       # seconds between rounds (every agent reads its own beat once a round)
    "x_per_beat": 15,                      # posts pulled per agent per round - this is what the provider bills
    "x_min_likes": 4,                      # a post nobody liked is not a signal
    "x_min_followers": 400,                # nor is one from an account nobody follows
    "x_min_account_days": 30,              # brand-new accounts are how coin spam is posted
    "x_max_age_min": 45,                   # older than this and the move already happened
    "x_min_voices": 2,                     # distinct accounts on the same coin before it is worth a look
    "x_big_voice": 25000,                  # unless one account this big posts it alone
    "x_max_per_round": 6,                  # coins actually evaluated per round, best heat first
    "x_accounts": "",                      # extra handles to follow, comma separated, no @
    "x_beats": {},                         # per-agent overrides: {"xgb": {"on": false, "terms": "..."}}
    # Owned by the UI (Keybinds and Sounds pages); the server only stores them so they survive and ride in backups
    "keybinds": {},                        # {"bindings": {"man.buy": "B", ...}, "groups": {"app": true, ...}}
    "sounds": {},                          # {"master": {...}, "events": {"profit": {...}, ...}}
    # Assistant
    "assistant_backend": "auto",           # auto | hermes_agent | local
    "hermes_url": "http://127.0.0.1:8642",
    "hermes_key": "",
    "hermes_agent_autostart": True,        # start the Hermes Agent app (`hermes gateway`, in WSL) when it's installed
    "hermes_agent_cmd": "hermes gateway",  # the command that runs its API server
    "hermes_wsl_distro": "",               # WSL distro Hermes Agent is installed in ("" = the default one)
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "llama3.2:3b",         # small model (~2 GB) for the Hermes chat tab
    "ollama_cpu_only": True,               # run it on the CPU so it never uses the RTX 4060's VRAM
    "ollama_keep_alive": "0",              # unload the model right after each reply (0 = no lingering)
    "assistant_autosetup": True,           # start Ollama and download the model automatically when needed
    "allow_web": True,
    # Hermes may only open pages on these trading/market sites (a site covers its subdomains; "site/path" limits it
    # to that section). Anything else is refused.
    "web_sites": ["federalreserve.gov", "bls.gov", "bea.gov", "treasury.gov", "ecb.europa.eu", "gold.org",
                  "lbma.org.uk", "kitco.com", "cmegroup.com", "fxstreet.com", "forexfactory.com", "investing.com",
                  "tradingeconomics.com", "marketwatch.com", "finance.yahoo.com", "investopedia.com", "babypips.com",
                  "reuters.com/markets", "mql5.com", "metatrader5.com"],
    # MCP bridge for Hermes Agent
    "mcp_http_port": 8765,
    "mcp_autostart": True,
    "settings_version": 8,
}


SECRETS = ("x_api_key",)        # never returned by a route: the app only learns whether one is set


def load() -> dict:
    s = dict(DEFAULTS)
    if PATH.exists():
        try:
            saved = json.loads(PATH.read_text())
            s.update(saved)
            if saved.get("settings_version", 1) < 2:          # v2: training look-ahead 240 -> 1440 candles
                if s.get("label_horizon") == 240:
                    s["label_horizon"] = 1440
                s["settings_version"] = 2
                PATH.write_text(json.dumps(s, indent=2))
            if s.get("settings_version", 1) < 4:          # v4: quiz runs at max speed by default
                s["quiz_speed"] = 0
                s["settings_version"] = 4
                PATH.write_text(json.dumps(s, indent=2))
            if s.get("settings_version", 1) < 5:          # v5: Hermes's model doesn't linger in memory after a reply
                if s.get("ollama_keep_alive") == "5m":
                    s["ollama_keep_alive"] = "0"
                s["settings_version"] = 5
                PATH.write_text(json.dumps(s, indent=2))
            if s.get("settings_version", 1) < 6:          # v6: chat on a small CPU-only model, no VRAM
                if s.get("ollama_model") == "hermes3:8b":
                    s["ollama_model"] = "llama3.2:3b"
                s["ollama_cpu_only"] = True
                s["settings_version"] = 6
                PATH.write_text(json.dumps(s, indent=2))
            if s.get("settings_version", 1) < 7:          # v7: the app shows its own TP/SL pop-ups; Windows' are extra
                s["desktop_alerts"] = False
                s["settings_version"] = 7
                PATH.write_text(json.dumps(s, indent=2))
            if s.get("settings_version", 1) < 8:          # v8: watchdog alerts go to Telegram too
                if "watchdog" not in (s.get("telegram_events") or []):
                    s["telegram_events"] = list(s.get("telegram_events") or []) + ["watchdog"]
                s["settings_version"] = 8
                PATH.write_text(json.dumps(s, indent=2))
        except json.JSONDecodeError:
            pass
    return s


KEPT = "__saved__"      # what the app is shown instead of a secret, and what it may send back unchanged


def public(s: dict | None = None) -> dict:
    """Settings as the window may see them: a saved secret becomes a placeholder, so it never rides in a poll."""
    s = dict(s if s is not None else load())
    for k in SECRETS:
        s[k] = KEPT if s.get(k) else ""
    return s


def save(updates: dict) -> dict:
    s = load()
    s.update({k: v for k, v in updates.items() if k in DEFAULTS and not (k in SECRETS and v == KEPT)})
    PATH.write_text(json.dumps(s, indent=2))
    return s


def check(updates: dict) -> tuple[dict, list[str]]:
    """Keep only known settings whose type matches the default (ints and floats mix). Returns (good, ignored keys)."""
    good, ignored = {}, []
    for k, v in updates.items():
        d = DEFAULTS.get(k)
        if k == "settings_version":                    # the file's own version: not a setting to restore
            continue
        if k not in DEFAULTS:
            ignored.append(k)
        elif isinstance(d, bool) != isinstance(v, bool) or (
                not isinstance(d, bool) and isinstance(d, (int, float)) and not isinstance(v, (int, float))) or (
                isinstance(d, (str, list, dict)) and not isinstance(v, type(d))):
            ignored.append(k)
        else:
            good[k] = v
    return good, ignored


def backup() -> dict:
    """Copy the current settings to data/backups/settings-YYYYMMDD-HHMM.json (a -2, -3... suffix if taken)."""
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stem = f"settings-{datetime.now():%Y%m%d-%H%M}"
    name, n = f"{stem}.json", 2
    while (BACKUPS / name).exists():
        name, n = f"{stem}-{n}.json", n + 1
    (BACKUPS / name).write_text(json.dumps(load(), indent=2))
    return {"name": name, "path": str(BACKUPS / name)}


def backups() -> list[dict]:
    if not BACKUPS.exists():
        return []
    rows = [{"name": p.name, "time": int(p.stat().st_mtime), "size": p.stat().st_size}
            for p in BACKUPS.glob("settings-*.json")]
    return sorted(rows, key=lambda r: (r["time"], r["name"]), reverse=True)


def restore(name: str | None = None, values: dict | None = None) -> dict:
    """Restore a backup by name, or settings from a file the user picked. The current settings are backed up first."""
    if name:
        p = BACKUPS / Path(name).name                      # a bare file name only: no paths outside backups/
        if not p.exists():
            raise ValueError(f"No backup called {name}.")
        try:
            values = json.loads(p.read_text())
        except ValueError:
            raise ValueError(f"{name} isn't a valid settings file.")
    if not isinstance(values, dict):
        raise ValueError("Send a backup name or a settings object.")
    before = load()
    saved = backup()["name"]
    good, ignored = check(values)
    after = save(good)
    return {"ok": True, "changed": sorted(k for k in good if before.get(k) != after.get(k)), "ignored": sorted(ignored),
            "backup": saved}
