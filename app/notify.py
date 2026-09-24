"""Windows pop-up notifications (toasts) for take-profit and stop-loss hits, so you see them with the app minimised or
behind other windows. Setting `desktop_alerts` (default off since the window shows its own custom pop-ups at the top
right; this adds Windows' own on top). Uses `winotify` when installed, otherwise PowerShell's own
toast API; does nothing on other systems. Shown from a background thread, so a slow toast never holds up the app.
"""
import os
import subprocess
import threading

from .settings import load

APP_ID = "Trading Bot"
_PS_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"   # a registered sender


def _winotify(title: str, msg: str) -> bool:
    try:
        from winotify import Notification, audio
    except ImportError:
        return False
    n = Notification(app_id=APP_ID, title=title, msg=msg, duration="short")
    n.set_audio(audio.Silent, loop=False)          # the app plays its own bell
    n.show()
    return True


def _powershell(title: str, msg: str):
    def esc(t: str) -> str:                         # XML text inside a PowerShell single-quoted string
        return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
                .replace("'", "''"))
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null;"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>{esc(title)}</text><text>{esc(msg)}</text>"
        "</binding></visual><audio silent=\"true\"/></toast>');"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_PS_APP_ID}')"
        ".Show([Windows.UI.Notifications.ToastNotification]::new($x))")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
                   capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def show(title: str, msg: str):
    """Pop up a Windows notification (if on Windows and `desktop_alerts` is on)."""
    if os.name != "nt" or not load().get("desktop_alerts", False):
        return

    def run():
        try:
            if not _winotify(title, msg):
                _powershell(title, msg)
        except Exception as e:                      # noqa: BLE001 - a missing toast must never break the watcher
            print(f"(desktop alert skipped: {e})", flush=True)
    threading.Thread(target=run, name="toast", daemon=True).start()


def for_event(ev: dict):
    """A toast for a TP or SL hit from the events feed."""
    if ev.get("kind") not in ("tp", "sl"):
        return
    who = {"you": "Your", "bot": "Bot's", "hermes": "Hermes's"}.get(ev.get("owner") or "", "A")
    what = "take profit" if ev["kind"] == "tp" else "stop loss"
    profit = ev.get("profit")
    money = f"{'+' if profit >= 0 else '-'}${abs(profit):,.2f}" if profit is not None else ""
    title = f"{'✅' if ev['kind'] == 'tp' else '🛑'} {who} {what} hit {money}".strip()
    vol = f"{ev['volume']:g} lot" if ev.get("volume") else ""
    msg = " ".join(x for x in (ev.get("symbol") or "", (ev.get("side") or "").upper(), vol,
                               f"closed at {ev['price']}" if ev.get("price") else "") if x)
    show(title, msg)
