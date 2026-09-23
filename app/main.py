"""Desktop entry point: starts the local server and opens the app window.

Double-click `Trading Bot.bat` (or run `pythonw -m app.main`). Falls back to the default browser if
pywebview isn't installed.
"""
import socket
import threading
import time
import webbrowser

import uvicorn

from .jobs import jobs
from .settings import load

HOST = "127.0.0.1"


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
    try:
        import webview
        webview.create_window("Trading Bot · M1", url, width=1440, height=900, min_size=(1024, 680),
                              background_color="#0E1013")
        webview.start()
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


if __name__ == "__main__":
    main()
