"""MT5 from a Mac (or Linux): a small bridge to a MetaTrader 5 terminal running on Windows.

MetaQuotes' MetaTrader5 Python package only exists for Windows. On a Mac, run MT5 on a Windows PC or in a Windows VM
(Parallels, VMware Fusion, UTM) and start this bridge there, next to the logged-in terminal:

    python -m agent.mt5_remote serve --token YOUR-SECRET        (inside the Trading-Bot folder), or
    python mt5_remote.py serve --token YOUR-SECRET              (this file on its own: pip install MetaTrader5 numpy)

It listens on port 18812. In the app on the Mac: Settings > MT5 bridge > http://<windows-ip>:18812 and the same token.
The app, the trading agent and the MCP bridge then use `RemoteMT5`, which has the same functions and constants as the
MetaTrader5 package; every call is forwarded and answered with the terminal's own result and last_error. Only plain
values cross the wire (JSON; bar and tick arrays as raw bytes). Without a token the bridge only answers 127.0.0.1.

This file needs nothing but the standard library (and numpy for bar arrays), so it can be copied to the Windows side.
"""
import argparse
import base64
import collections
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

PORT = 18812
NO_BRIDGE = ("MetaTrader 5 only runs on Windows. To use MT5 from this computer, run MT5 on a Windows PC or in a "
             "Windows VM, start the MT5 bridge there, and enter its address in Settings > MT5 bridge.")
# the constants the app uses, so they work before the bridge answers (the bridge's own table replaces these)
DEFAULTS = {
    "TIMEFRAME_M1": 1, "TIMEFRAME_M5": 5, "TIMEFRAME_M15": 15, "TIMEFRAME_H1": 16385, "TIMEFRAME_D1": 16408,
    "ORDER_TYPE_BUY": 0, "ORDER_TYPE_SELL": 1, "ORDER_TYPE_BUY_LIMIT": 2, "ORDER_TYPE_SELL_LIMIT": 3,
    "ORDER_TYPE_BUY_STOP": 4, "ORDER_TYPE_SELL_STOP": 5, "ORDER_TYPE_BUY_STOP_LIMIT": 6, "ORDER_TYPE_SELL_STOP_LIMIT": 7,
    "POSITION_TYPE_BUY": 0, "POSITION_TYPE_SELL": 1,
    "TRADE_ACTION_DEAL": 1, "TRADE_ACTION_PENDING": 5, "TRADE_ACTION_SLTP": 6, "TRADE_ACTION_MODIFY": 7,
    "TRADE_ACTION_REMOVE": 8, "TRADE_ACTION_CLOSE_BY": 10,
    "ORDER_FILLING_FOK": 0, "ORDER_FILLING_IOC": 1, "ORDER_FILLING_RETURN": 2, "ORDER_FILLING_BOC": 3,
    "ORDER_TIME_GTC": 0, "ORDER_TIME_DAY": 1, "ORDER_TIME_SPECIFIED": 2, "ORDER_TIME_SPECIFIED_DAY": 3,
    "TRADE_RETCODE_PLACED": 10008, "TRADE_RETCODE_DONE": 10009, "TRADE_RETCODE_DONE_PARTIAL": 10010,
    "TRADE_RETCODE_INVALID_STOPS": 10016, "TRADE_RETCODE_MARKET_CLOSED": 10018, "TRADE_RETCODE_NO_MONEY": 10019,
    "ACCOUNT_TRADE_MODE_DEMO": 0, "ACCOUNT_TRADE_MODE_CONTEST": 1, "ACCOUNT_TRADE_MODE_REAL": 2,
    "ACCOUNT_MARGIN_MODE_RETAIL_NETTING": 0, "ACCOUNT_MARGIN_MODE_EXCHANGE": 1, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING": 2,
    "SYMBOL_TRADE_MODE_DISABLED": 0, "SYMBOL_TRADE_MODE_LONGONLY": 1, "SYMBOL_TRADE_MODE_SHORTONLY": 2,
    "SYMBOL_TRADE_MODE_CLOSEONLY": 3, "SYMBOL_TRADE_MODE_FULL": 4,
    "DEAL_TYPE_BUY": 0, "DEAL_TYPE_SELL": 1,
    "DEAL_ENTRY_IN": 0, "DEAL_ENTRY_OUT": 1, "DEAL_ENTRY_INOUT": 2, "DEAL_ENTRY_OUT_BY": 3,
    "DEAL_REASON_CLIENT": 0, "DEAL_REASON_MOBILE": 1, "DEAL_REASON_WEB": 2, "DEAL_REASON_EXPERT": 3,
    "DEAL_REASON_SL": 4, "DEAL_REASON_TP": 5, "DEAL_REASON_SO": 6,
}
_NT = {}


def _nt(name: str, fields):
    key = (name, tuple(fields))
    if key not in _NT:
        _NT[key] = collections.namedtuple(name if name.isidentifier() else "Result", fields)
    return _NT[key]


def encode(v):
    """Python value -> JSON-safe value (MT5's named tuples, numpy arrays and datetimes included)."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, datetime):
        off = v.utcoffset()
        return {"__dt__": [v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond],
                "off": None if off is None else off.total_seconds()}
    if hasattr(v, "_asdict"):                                   # MT5's results are named tuples
        d = v._asdict()
        return {"__nt__": type(v).__name__, "f": list(d), "v": [encode(x) for x in d.values()]}
    try:
        import numpy as np
        if isinstance(v, np.ndarray):
            a = np.ascontiguousarray(v)
            descr = [list(d) for d in a.dtype.descr] if a.dtype.names else a.dtype.str
            return {"__nd__": base64.b64encode(a.tobytes()).decode(), "descr": descr, "shape": list(a.shape)}
        if isinstance(v, np.generic):
            return v.item()
    except ImportError:
        pass
    if isinstance(v, dict):
        return {"__d__": [[encode(k), encode(x)] for k, x in v.items()]}
    if isinstance(v, (list, tuple)):
        return [encode(x) for x in v]
    if isinstance(v, bytes):
        return {"__b__": base64.b64encode(v).decode()}
    if isinstance(v, SimpleNamespace) or hasattr(v, "__dict__"):
        return {"__ns__": {k: encode(x) for k, x in vars(v).items() if not k.startswith("_")}}
    return str(v)


def decode(v):
    if isinstance(v, list):
        return [decode(x) for x in v]
    if not isinstance(v, dict):
        return v
    if "__nt__" in v:
        return _nt(v["__nt__"], v["f"])(*[decode(x) for x in v["v"]])
    if "__nd__" in v:
        import numpy as np
        dt = np.dtype([tuple(d) for d in v["descr"]]) if isinstance(v["descr"], list) else np.dtype(v["descr"])
        return np.frombuffer(base64.b64decode(v["__nd__"]), dtype=dt).reshape(v["shape"]).copy()
    if "__dt__" in v:
        tz = None if v.get("off") is None else timezone(timedelta(seconds=v["off"]))
        return datetime(*v["__dt__"], tzinfo=tz)
    if "__d__" in v:
        return {decode(k): decode(x) for k, x in v["__d__"]}
    if "__b__" in v:
        return base64.b64decode(v["__b__"])
    if "__ns__" in v:
        return SimpleNamespace(**{k: decode(x) for k, x in v["__ns__"].items()})
    return {k: decode(x) for k, x in v.items()}


# ---------- the Mac side ----------
class RemoteMT5:
    """Drop-in for the MetaTrader5 module that forwards every call to the bridge. Functions return what MT5 returns
    (None / False on failure) and last_error() explains, so the app's existing error handling just works."""
    is_remote = True

    def __init__(self, url: str | None = None, token: str | None = None, settings_file: Path | None = None):
        self._url, self._token = url, token
        self._settings = settings_file or Path(__file__).resolve().parent.parent / "data" / "settings.json"
        self._conf_at, self._conf = 0.0, ("", "")
        self._consts: dict | None = None
        self._err = (-1, NO_BRIDGE)
        self.__version__ = "bridge"

    def _config(self) -> tuple[str, str]:
        if self._url is not None:
            return self._url.rstrip("/"), self._token or ""
        if time.time() - self._conf_at > 5:                     # the app may change the setting while running
            url, token = os.environ.get("MT5_BRIDGE_URL", ""), os.environ.get("MT5_BRIDGE_TOKEN", "")
            if not url:
                try:
                    s = json.loads(self._settings.read_text(encoding="utf-8"))
                    url, token = s.get("mt5_bridge_url") or "", s.get("mt5_bridge_token") or ""
                except (OSError, ValueError):
                    pass
            url = url.strip()
            if url and "://" not in url:
                url = "http://" + url
            if url and url.count(":") < 2:                      # no port given: the bridge's default
                url = f"{url.rstrip('/')}:{PORT}"
            self._conf, self._conf_at = (url.rstrip("/"), token.strip()), time.time()
        return self._conf

    def _request(self, path: str, payload=None, timeout: float = 15):
        url, token = self._config()
        if not url:
            raise LookupError(NO_BRIDGE)
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(url + path, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json", "X-Bridge-Token": token})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode()).get("error")
            except (ValueError, OSError):
                msg = None
            raise ConnectionError(msg or f"the MT5 bridge at {url} answered HTTP {e.code}")
        except (urllib.error.URLError, OSError, ValueError) as e:
            reason = getattr(e, "reason", e)
            raise ConnectionError(f"can't reach the MT5 bridge at {url} ({reason}). Is it running on the Windows side, "
                                  f"and is port {PORT} allowed through its firewall?")

    def ping(self) -> dict:
        """What the bridge says about itself and the terminal (Settings > MT5 bridge > Test)."""
        r = self._request("/ping", timeout=6)
        self._consts = {**DEFAULTS, **(r.get("constants") or {})}
        return {k: decode(v) for k, v in r.items() if k != "constants"}

    def _constants(self) -> dict:
        if self._consts is None:
            try:
                self.ping()
            except (LookupError, ConnectionError):
                return DEFAULTS                                  # try again next time
        return self._consts or DEFAULTS

    def _call(self, fn: str, args, kwargs):
        try:
            r = self._request("/call", {"fn": fn, "args": encode(list(args)), "kwargs": encode(kwargs)},
                              timeout=60 if fn.startswith(("copy_", "history_")) else 15)
        except (LookupError, ConnectionError) as e:
            self._err = (-10004 if isinstance(e, ConnectionError) else -1, str(e) if isinstance(e, ConnectionError) else NO_BRIDGE)
            return False if fn == "initialize" else None
        if not r.get("ok"):
            self._err = (-2, r.get("error") or "the MT5 bridge refused the call")
            return False if fn == "initialize" else None
        self._err = tuple(decode(r.get("last_error") or [1, "Success"]))
        return decode(r.get("result"))

    def last_error(self):
        return self._err

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name.isupper():
            consts = self._constants()
            if name in consts:
                return consts[name]
            raise AttributeError(name)
        return lambda *args, **kwargs: self._call(name, args, kwargs)


def load_mt5():
    """The MetaTrader5 package on Windows, the bridge everywhere else."""
    try:
        import MetaTrader5 as mt5
        return mt5
    except ImportError:
        return RemoteMT5()


# ---------- the Windows side ----------
def serve(host: str = "127.0.0.1", port: int = PORT, token: str = "", terminal: str | None = None):
    import MetaTrader5 as mt5
    local = host in ("127.0.0.1", "localhost", "::1")
    if not local and not token:
        raise SystemExit("Give the bridge a --token to listen on the network: anyone who can reach this port could "
                         "trade on your account.")
    lock = threading.Lock()                                  # the MetaTrader5 package isn't thread-safe
    consts = {k: getattr(mt5, k) for k in dir(mt5) if k.isupper() and isinstance(getattr(mt5, k), int)}
    with lock:
        ok = mt5.initialize(path=terminal) if terminal else mt5.initialize()
    print(f"MT5 terminal: {'connected' if ok else 'not connected yet (' + str(mt5.last_error()) + ')'}", flush=True)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self) -> bool:
            if token:
                return hmac.compare_digest(self.headers.get("X-Bridge-Token", ""), token)
            return self.client_address[0] in ("127.0.0.1", "::1")

        def do_GET(self):
            if not self._allowed():
                return self._send(401, {"ok": False, "error": "wrong or missing bridge token"})
            if self.path.rstrip("/") not in ("", "/ping"):
                return self._send(404, {"ok": False, "error": "not found"})
            with lock:
                term = mt5.terminal_info()
                acc = mt5.account_info()
            self._send(200, {"ok": True, "version": getattr(mt5, "__version__", "?"), "constants": consts,
                             "terminal": encode(term), "account": encode(acc) if acc else None})

        def do_POST(self):
            if not self._allowed():
                return self._send(401, {"ok": False, "error": "wrong or missing bridge token"})
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode())
                fn = str(req.get("fn") or "")
                if fn.startswith("_") or not callable(getattr(mt5, fn, None)):
                    return self._send(400, {"ok": False, "error": f"MetaTrader5 has no function {fn!r}"})
                args, kwargs = decode(req.get("args") or []), decode(req.get("kwargs") or {})
                with lock:
                    result = getattr(mt5, fn)(*args, **kwargs)
                    err = mt5.last_error()
                self._send(200, {"ok": True, "result": encode(result), "last_error": encode(err)})
            except Exception as e:                           # noqa: BLE001 - report it, keep serving
                self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"MT5 bridge listening on http://{host}:{port}" + ("" if token else " (this computer only)"), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run on the Windows side, next to the MT5 terminal")
    s.add_argument("--host", default=None, help="0.0.0.0 = the network (needs --token); default 127.0.0.1, or "
                                                "0.0.0.0 when a token is given")
    s.add_argument("--port", type=int, default=PORT)
    s.add_argument("--token", default=os.environ.get("MT5_BRIDGE_TOKEN", ""))
    s.add_argument("--terminal", default=None, help="path to terminal64.exe (optional)")
    t = sub.add_parser("test", help="run on the Mac: can the app reach the bridge?")
    t.add_argument("url")
    t.add_argument("--token", default="")
    a = ap.parse_args()
    if a.cmd == "serve":
        serve(a.host or ("0.0.0.0" if a.token else "127.0.0.1"), a.port, a.token, a.terminal)
    else:
        print(json.dumps(RemoteMT5(a.url, a.token).ping(), indent=1, default=str))


if __name__ == "__main__":
    main()
