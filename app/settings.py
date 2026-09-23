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
    "max_open_trades": 25,
    "paper_balance": 10000.0,
    "label_horizon": 240,                  # bars a training label may take to hit its stop/target
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
}


def load() -> dict:
    s = dict(DEFAULTS)
    if PATH.exists():
        try:
            s.update(json.loads(PATH.read_text()))
        except json.JSONDecodeError:
            pass
    return s


def save(updates: dict) -> dict:
    s = load()
    s.update({k: v for k, v in updates.items() if k in DEFAULTS})
    PATH.write_text(json.dumps(s, indent=2))
    return s
