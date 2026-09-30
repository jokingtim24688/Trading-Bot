"""Desktop entry point: starts the local server and opens the app window.

Double-click `Trading Bot.bat` on Windows or `Trading Bot.command` / `Trading Bot.app` on a Mac (or run
`python -m app.main`). Falls back to the default browser if pywebview isn't installed.
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

if sys.platform == "darwin":                     # opened from the Finder / a .app: no Homebrew in PATH otherwise
    _extra = [p for p in ("/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", str(Path.home() / ".local" / "bin"))
              if Path(p).is_dir()]
    os.environ["PATH"] = os.pathsep.join(dict.fromkeys(_extra + os.environ.get("PATH", "").split(os.pathsep)))

import uvicorn

from .jobs import jobs
from .settings import load

HOST = "127.0.0.1"
POP_W = 380                         # width of the pop-up window (CSS pixels)
MAIN_TITLE = "Trading Bot · M1"
POP_TITLE = "Trading Bot alerts"
POP_CFG = Path(__file__).resolve().parent.parent / "data" / "popups.json"


class _Win:
    """The few Win32 calls the pop-up needs: above every other window (full-screen apps included) without ever
    taking focus, no taskbar button or Alt+Tab entry, and placed at the top right of the chosen screen."""
    TOPMOST = -1
    NOSIZE, NOMOVE, NOACTIVATE, FRAMECHANGED, SHOWWINDOW = 0x1, 0x2, 0x10, 0x20, 0x40
    EXSTYLE, TOOLWINDOW, APPWINDOW, NOACTIVATE_EX = -20, 0x80, 0x40000, 0x08000000

    def __init__(self):
        import ctypes
        from ctypes import wintypes as wt
        self.c = ctypes
        u = self.u = ctypes.windll.user32
        u.FindWindowW.restype, u.FindWindowW.argtypes = wt.HWND, [wt.LPCWSTR, wt.LPCWSTR]
        u.GetForegroundWindow.restype = wt.HWND
        u.IsIconic.argtypes = [wt.HWND]
        u.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        self.getl = getattr(u, "GetWindowLongPtrW", None) or u.GetWindowLongW     # 32-bit Python has only the short names
        self.setl = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
        self.getl.restype, self.getl.argtypes = ctypes.c_ssize_t, [wt.HWND, ctypes.c_int]
        self.setl.restype, self.setl.argtypes = ctypes.c_ssize_t, [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
        u.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.c_void_p]
        if hasattr(u, "GetDpiForWindow"):
            u.GetDpiForWindow.restype, u.GetDpiForWindow.argtypes = ctypes.c_uint, [wt.HWND]

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
        self.MonitorInfo = MonitorInfo
        self.EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)

    def find(self, title):
        return self.u.FindWindowW(None, title)

    def in_front(self, hwnd):
        return bool(hwnd) and self.u.GetForegroundWindow() == hwnd and not self.u.IsIconic(hwnd)

    def monitors(self):
        out = []

        def each(hmon, _hdc, _rect, _lparam):
            mi = self.MonitorInfo()
            mi.cbSize = self.c.sizeof(mi)
            if self.u.GetMonitorInfoW(hmon, self.c.byref(mi)):
                m, w = mi.rcMonitor, mi.rcWork
                out.append({"full": (m.left, m.top, m.right, m.bottom), "work": (w.left, w.top, w.right, w.bottom),
                            "primary": bool(mi.dwFlags & 1)})
            return True
        self.u.EnumDisplayMonitors(None, None, self.EnumProc(each), 0)
        out.sort(key=lambda m: (not m["primary"], m["full"][0], m["full"][1]))   # the main screen first, then left to right
        return out

    def prepare(self, hwnd):
        ex = self.getl(hwnd, self.EXSTYLE)
        self.setl(hwnd, self.EXSTYLE, (ex | self.TOOLWINDOW | self.NOACTIVATE_EX) & ~self.APPWINDOW)
        self.u.SetWindowPos(hwnd, self.TOPMOST, 0, 0, 0, 0, self.NOMOVE | self.NOSIZE | self.NOACTIVATE | self.FRAMECHANGED)

    def show_at(self, hwnd, mon, css_w, css_h):
        """Top right of that screen's work area, raised above every other always-on-top window, not activated."""
        s = self.u.GetDpiForWindow(hwnd) / 96 if hasattr(self.u, "GetDpiForWindow") else 1.0
        s = s if s > 0 else 1.0
        w, h, gap = int(css_w * s), int(css_h * s), int(12 * s)
        self.u.SetWindowPos(hwnd, self.TOPMOST, mon["work"][2] - w - gap, mon["work"][1] + gap, w, h,
                            self.NOACTIVATE | self.SHOWWINDOW)

    def hide(self, hwnd):
        self.u.ShowWindow(hwnd, 0)


class _Mac:
    """The same jobs as _Win with AppKit (pywebview's Cocoa backend brings PyObjC): the pop-up floats above full-screen
    apps on every Space, shows without activating the app (so it never takes focus), and sits at the top right of the
    chosen screen. AppKit wants the main thread, so every call is handed to it and waited for. Also keeps macOS' App Nap
    from slowing the app down while it's in the background (alerts would lag)."""
    STATUS_LEVEL = 25                               # NSStatusWindowLevel: above normal and floating windows
    ALL_SPACES, STATIONARY, IGNORES_CYCLE, FULLSCREEN_AUX = 1 << 0, 1 << 4, 1 << 6, 1 << 8

    def __init__(self):
        import AppKit
        from PyObjCTools import AppHelper
        self.ak, self.helper, self._activity = AppKit, AppHelper, None

    def _main(self, fn, timeout=2.0):
        """Run fn on the main thread and return its result (None if it didn't finish in time)."""
        done, box = threading.Event(), {}

        def run():
            try:
                box["v"] = fn()
            except Exception as e:                  # noqa: BLE001
                box["e"] = e
            done.set()
        self.helper.callAfter(run)
        done.wait(timeout)
        return box.get("v")

    def keep_awake(self):
        pi = self.ak.NSProcessInfo.processInfo()
        opts = getattr(self.ak, "NSActivityUserInitiatedAllowingIdleSystemSleep", 0x00EFFFFF)
        self._activity = pi.beginActivityWithOptions_reason_(opts, "Trade alerts and the trading bot")

    def find(self, title):
        return self._main(lambda: next((w for w in self.ak.NSApp.windows() if str(w.title()) == title), None))

    def in_front(self, _handle=None):
        app = self.ak.NSWorkspace.sharedWorkspace().frontmostApplication()
        return bool(app) and app.processIdentifier() == os.getpid()

    def monitors(self):
        def read():
            out = []
            for i, sc in enumerate(self.ak.NSScreen.screens()):
                f, v = sc.frame(), sc.visibleFrame()     # points, origin at the bottom left, y going up
                out.append({"full": (f.origin.x, f.origin.y, f.origin.x + f.size.width, f.origin.y + f.size.height),
                            "work": (v.origin.x, v.origin.y, v.origin.x + v.size.width, v.origin.y + v.size.height),
                            "primary": i == 0})
            return out
        return self._main(read) or []

    def prepare(self, win):
        def run():
            win.setLevel_(self.STATUS_LEVEL)
            win.setCollectionBehavior_(self.ALL_SPACES | self.STATIONARY | self.IGNORES_CYCLE | self.FULLSCREEN_AUX)
            win.setHidesOnDeactivate_(False)
        self._main(run)

    def show_at(self, win, mon, css_w, css_h):
        left, bottom, right, top = mon["work"]
        rect = self.ak.NSMakeRect(right - css_w - 12, top - css_h - 12, css_w, css_h)

        def run():
            win.setFrame_display_(rect, True)
            win.orderFrontRegardless()              # shown, but the app isn't activated
        self.helper.callAfter(run)

    def hide(self, win):
        self.helper.callAfter(lambda: win.orderOut_(None))


class Popups:
    """Custom pop-ups at the top right of the screen while the app isn't in front: minimised, behind other windows or
    under a full-screen app (Windows' own toasts can't be moved or styled, and Focus Assist hides them during
    full-screen apps). Take profit / stop loss alerts come straight from the server's events feed here, so they don't
    depend on the minimised window's page; everything else (bot paper trades, orders, Hermes) is sent by the page.
    pywebview exposes the public methods to both pages' JavaScript; internals start with "_" so it leaves them alone."""

    def __init__(self, port: int):
        self._port, self._win, self._handle, self._main, self._native = port, None, None, None, None   # native: _Win / _Mac
        self._height, self._shown, self._ready, self._pending, self._trail = 110, False, False, [], set()
        self._cfg = {"secs": 2, "screen": True, "tpsl": True, "monitor": 0}
        try:
            self._cfg.update(json.loads(POP_CFG.read_text()))
        except (OSError, ValueError):
            pass
        if self._cfg.get("secs") == 1.2:          # the old default; the user asked for 2 s
            self._cfg["secs"] = 2

    # --- called from the main window's page
    def notify(self, payload):
        if not self._win:
            return False
        if not self._ready:                       # the pop-up page is still loading: it takes these when it's up
            self._pending.append(payload)
            self._show(1)
            return True
        try:
            self._win.evaluate_js(f"window.addNote({json.dumps(payload)})")
        except Exception:
            return False
        self._show()
        return True

    def configure(self, cfg):
        self._cfg.update({k: cfg[k] for k in ("secs", "screen", "tpsl", "monitor") if k in cfg})
        try:
            POP_CFG.parent.mkdir(parents=True, exist_ok=True)
            POP_CFG.write_text(json.dumps(self._cfg))
        except OSError:
            pass
        return self._cfg

    def feed(self):
        """True when TP/SL alerts reach the screen from here (so the page doesn't send them twice)."""
        return bool(self._native and self._handle)

    def screens(self):
        if not self._native:
            return []
        try:
            return [{"i": i, "label": f"{'Main screen' if m['primary'] else f'Screen {i + 1}'} "
                                      f"({m['full'][2] - m['full'][0]}×{m['full'][3] - m['full'][1]})"}
                    for i, m in enumerate(self._native.monitors())]
        except Exception:
            return []

    # --- called from the pop-up page
    def ready(self):
        self._ready = True
        pending, self._pending = self._pending, []
        for p in pending:
            self.notify(p)
        if not pending and self._shown:
            self.idle()

    def fit(self, height):
        self._height = max(40, min(int(height) + 2, 900))
        if self._shown:
            self._show()

    def idle(self):
        self._shown = False
        if self._native and self._handle:
            self._native.hide(self._handle)
        elif self._win:
            self._win.hide()

    # --- internals
    def _show(self, height=None):
        self._shown = True
        h = height or self._height
        if self._native and not self._handle:
            self._handle = self._native.find(POP_TITLE)
            if self._handle:
                self._native.prepare(self._handle)
        if self._native and self._handle:
            mons = self._native.monitors()
            i = int(self._cfg.get("monitor") or 0)
            mon = mons[i] if 0 <= i < len(mons) else (mons[0] if mons else None)
            if mon:
                self._native.show_at(self._handle, mon, POP_W, h)
                return
        self._win.resize(POP_W, h)                # other systems: pywebview's own calls
        self._win.show()

    def _in_front(self):
        if not self._native:
            return True
        self._main = self._main or self._native.find(MAIN_TITLE)
        return self._native.in_front(self._main)

    _WATCHDOG = {"agent_restart": ("Bot restarted", "info"), "agent_failed": ("Bot stopped", "err"),
                "agent_stuck": ("Bot looks stuck", "err"), "mt5_down": ("MT5 is down", "err"), "mt5_up": ("MT5 is back", "ok")}

    def _payload(self, ev: dict):
        kind, profit = ev.get("kind"), ev.get("profit")
        if kind in self._WATCHDOG:                  # about the bot itself: a ready sentence from the watchdog
            title, k = self._WATCHDOG[kind]
            return {"title": title, "body": ev.get("message") or "", "kind": k, "amount": None, "secs": self._cfg.get("secs", 2)}
        who = {"bot": "Bot", "hermes": "Hermes"}.get(ev.get("owner"), "You")
        body = " ".join(str(x) for x in (ev.get("side"), ev.get("volume"), ev.get("symbol")) if x not in (None, ""))
        body += (f" at {ev['price']}" if ev.get("price") else "") + f" ({who})"
        out = {"body": body, "amount": None if profit is None else f"{profit:+,.2f}", "secs": self._cfg.get("secs", 2)}
        if kind == "tp":
            return {**out, "title": "Take profit hit", "kind": "tp"}
        if kind == "sl":
            won = (profit or 0) > 0                 # a trailed or break-even stop can close in profit
            return {**out, "title": "Stop hit, in profit" if won else "Stop loss hit", "kind": "tp" if won else "sl"}
        if kind == "close" and profit is not None:
            return {**out, "title": f"{'Your' if who == 'You' else who + chr(39) + 's'} trade closed",
                    "kind": "tp" if profit >= 0 else "sl"}
        if kind == "be":
            return {**out, "title": "Stop moved to break-even", "kind": "info", "amount": None}
        if kind == "trail" and ev.get("ticket") not in self._trail:
            self._trail.add(ev.get("ticket"))
            return {**out, "title": "Trailing stop moved", "kind": "info", "amount": None}
        return None

    def _watch(self):
        """The events feed, read here every 0.7 s: TP/SL alerts pop up even while the main window is minimised."""
        import urllib.request
        since = None
        while True:
            try:
                url = f"http://{HOST}:{self._port}/api/events" + (f"?since={since}" if since is not None else "")
                with urllib.request.urlopen(url, timeout=5) as r:
                    d = json.loads(r.read().decode())
                if since is not None and self._cfg.get("screen", True) and not self._in_front():
                    for ev in d.get("events") or []:
                        p = self._payload(ev)       # trade alerts follow the TP/SL switch; watchdog alerts always show
                        if p and (ev.get("kind") in self._WATCHDOG or self._cfg.get("tpsl", True)):
                            self.notify(p)
                since = d.get("last_id", since)
            except Exception:
                pass
            time.sleep(0.7)


def _start_popups(popups):
    """Runs once the window loop is up: make the pop-up a non-activating, always-on-top window (Windows: Win32, Mac:
    AppKit) and start reading the events feed; elsewhere pywebview moves it to the top right of the main screen."""
    if sys.platform in ("win32", "darwin"):
        try:
            popups._native = _Win() if sys.platform == "win32" else _Mac()
            if sys.platform == "darwin":
                popups._native.keep_awake()
            for _ in range(50):                    # the native windows appear a moment after start
                popups._handle = popups._native.find(POP_TITLE)
                if popups._handle:
                    break
                time.sleep(0.1)
            if popups._handle:
                popups._native.prepare(popups._handle)
            threading.Thread(target=popups._watch, daemon=True).start()
        except Exception:
            popups._native = popups._handle = None
    if not popups._native:
        try:
            import webview
            s = webview.screens[0]
            popups._win.move(int(getattr(s, "x", 0) + s.width - POP_W - 12), int(getattr(s, "y", 0) + 12))
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

    if load().get("mcp_autostart"):             # MCP bridge (only needed for Hermes Agent): a leftover one from an
        from app import bridge                  # earlier session is replaced; failures show in the setup checklist
        threading.Thread(target=lambda: bridge.start(int(load()["mcp_http_port"])), daemon=True).start()

    url = f"http://{HOST}:{port}/"
    # keep timers at full speed while the window is minimised or covered, so alerts, sounds and the events feed
    # don't lag (WebView2 slows hidden pages down to about one wake-up a minute otherwise)
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = " ".join(filter(None, [
        os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", ""), "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling"]))
    if sys.platform == "darwin":                  # the menu bar says "Trading Bot", not "Python"
        try:
            from Foundation import NSBundle
            b = NSBundle.mainBundle()
            (b.localizedInfoDictionary() or b.infoDictionary())["CFBundleName"] = "Trading Bot"
        except Exception:                         # noqa: BLE001 - cosmetic
            pass
    try:
        import webview
        popups = Popups(port)
        main_win = webview.create_window(MAIN_TITLE, url, width=1440, height=900, min_size=(1024, 680),
                                         background_color="#0E1013", js_api=popups)
        # the pop-up never takes focus from what you're doing, and closes with the main window; if this pywebview can't
        # do either, there's no pop-up window at all (in-app notifications still work)
        if hasattr(getattr(main_win, "events", None), "closed"):
            try:
                popups._win = webview.create_window(POP_TITLE, url + "static/notify.html", width=POP_W, height=110,
                                                    frameless=True, on_top=True, hidden=True, resizable=False,
                                                    focus=False, easy_drag=False, background_color="#0E1013",
                                                    js_api=popups)
                main_win.events.closed += lambda: popups._win and popups._win.destroy()
            except Exception:
                popups._win = None
        # pywebview's default private mode wipes what the window stores (one-click, TP/SL points, keybinds, sounds
        # you added before the server kept them, ...) every time it closes; keep it in data/webview instead
        store = Path(__file__).resolve().parent.parent / "data" / "webview"
        store.mkdir(parents=True, exist_ok=True)
        webview.start(_start_popups if popups._win else None, (popups,) if popups._win else None,
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
    elif sys.platform == "darwin":
        import subprocess
        msg = f"{exc}\n\nDetails: {LOG}".replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'display alert "Trading Bot couldn\'t start" message "{msg}" as critical'],
                       capture_output=True, timeout=120)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:           # noqa: BLE001
        _fatal(e)
        raise
