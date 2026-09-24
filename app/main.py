"""Desktop entry point: starts the local server and opens the app window.

Double-click `Trading Bot.bat` (or run `pythonw -m app.main`). Falls back to the default browser if
pywebview isn't installed.
"""
import json
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "logs" / "app.log"
if sys.stdout is None or sys.stderr is None:      # pythonw.exe (no console window): send output to logs/app.log
    LOG.parent.mkdir(exist_ok=True)
    sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)

import uvicorn

from .jobs import jobs
from .settings import load

HOST = "127.0.0.1"
POP_W = 380          # width of the pop-up window at the top right of the screen


class Popups:
    """Custom pop-ups at the top right of the screen while the app isn't in front (Windows' own toasts can't be moved
    or styled). The main window's page calls notify(); the pop-up page calls fit() and idle(). pywebview runs these
    on its own thread, and window methods are safe to call from there."""

    def __init__(self):
        self.win = None

    def notify(self, payload):
        if not self.win:
            return False
        try:
            self.win.evaluate_js(f"window.addNote({json.dumps(payload)})")
            self.win.show()
            return True
        except Exception:
            return False

    def fit(self, height):
        if self.win:
            self.win.resize(POP_W, max(60, min(int(height) + 2, 900)))

    def idle(self):
        if self.win:
            self.win.hide()


def _place(popups):
    """After the window loop starts: put the pop-up window at the top right of the main screen."""
    try:
        import webview
        s = webview.screens[0]
        popups.win.move(int(getattr(s, "x", 0) + s.width - POP_W - 12), int(getattr(s, "y", 0) + 12))
    except Exception:
        pass


def _free_port(preferred: int = 8420) -> int:
    with socket.socket() as s:
        if s.connect_ex((HOST, preferred)) != 0:
            return preferred
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def main():
    port = _free_port()
    config = uvicorn.Config("app.server:app", host=HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)

    if load().get("mcp_autostart"):
        try:
            jobs.start("mcp", ["mcp_server/mt5_mcp.py", "--http", "--port", str(load()["mcp_http_port"])])
        except Exception:
            pass   # MCP bridge is optional (only needed for Hermes Agent)

    url = f"http://{HOST}:{port}/"
    # keep timers at full speed while the window is minimised or covered, so alerts, sounds and the events feed
    # don't lag (WebView2 slows hidden pages down to about one wake-up a minute otherwise)
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = " ".join(filter(None, [
        os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", ""), "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows"]))
    try:
        import webview
        popups = Popups()
        main_win = webview.create_window("Trading Bot · M1", url, width=1440, height=900, min_size=(1024, 680),
                                         background_color="#0E1013", js_api=popups)
        # the pop-up never takes focus from what you're doing, and closes with the main window; if this pywebview can't
        # do either, there's no pop-up window at all (in-app notifications still work)
        if hasattr(getattr(main_win, "events", None), "closed"):
            try:
                popups.win = webview.create_window("Trading Bot alerts", url + "static/notify.html", width=POP_W,
                                                   height=110, frameless=True, on_top=True, hidden=True, resizable=False,
                                                   focus=False, easy_drag=False, background_color="#0E1013", js_api=popups)
                main_win.events.closed += lambda: popups.win and popups.win.destroy()
            except Exception:
                popups.win = None
        # pywebview's default private mode wipes what the window stores (one-click, TP/SL points, keybinds, sounds
        # you added before the server kept them, ...) every time it closes; keep it in data/webview instead
        store = Path(__file__).resolve().parent.parent / "data" / "webview"
        store.mkdir(parents=True, exist_ok=True)
        webview.start(_place if popups.win else None, (popups,) if popups.win else None,
                      private_mode=False, storage_path=str(store))
    except ImportError:
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    finally:
        # stop the background helpers but leave the trading agent alone only if the user wants it; default: stop all
        jobs.stop_all()
        server.should_exit = True


def _fatal(exc: BaseException):
    """Without a console nobody sees a traceback, so log it and say so in a message box."""
    traceback.print_exception(exc)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, f"Trading Bot couldn't start:\n\n{exc}\n\nDetails: {LOG}",
                                         "Trading Bot", 0x10)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:           # noqa: BLE001
        _fatal(e)
        raise
