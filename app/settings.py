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
    "threshold": 0.55,
    "risk_pct": 0.5,
    "days_history": 365,
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
