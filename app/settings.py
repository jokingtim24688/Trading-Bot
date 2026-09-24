"""App settings, stored on disk in data/settings.json (nothing important lives only in RAM)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
PATH = DATA / "settings.json"

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
    "use_learned": True,                   # apply the rules the bot learned from its own trades
    "quiz_filter": False,
    "quiz_refresh": True,                  # quiz: silently refresh finished questions so it doesn't forget them                  # only enter when the quiz agent (Quiz tab) picks the same side
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
    # Assistant
    "assistant_backend": "auto",           # auto | hermes_agent | local
    "hermes_url": "http://127.0.0.1:8642",
    "hermes_key": "",
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "hermes3:8b",
    "ollama_keep_alive": "5m",             # unload the model from VRAM after this idle time
    "allow_web": True,
    # MCP bridge for Hermes Agent
    "mcp_http_port": 8765,
    "mcp_autostart": True,
    "settings_version": 4,
}


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
        except json.JSONDecodeError:
            pass
    return s


def save(updates: dict) -> dict:
    s = load()
    s.update({k: v for k, v in updates.items() if k in DEFAULTS})
    PATH.write_text(json.dumps(s, indent=2))
    return s
