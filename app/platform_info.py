"""Which computer the app runs on, for the UI and the setup checklist (Mac, Windows or Linux; chip; native MT5 or not)."""
import functools
import platform
import sys


@functools.lru_cache(maxsize=1)
def info() -> dict:
    mac, win = sys.platform == "darwin", sys.platform == "win32"
    arch = platform.machine().lower()
    try:
        import MetaTrader5  # noqa: F401
        native = True
    except ImportError:
        native = False
    return {"os": "mac" if mac else "windows" if win else "linux", "arch": arch,
            "apple_silicon": mac and arch == "arm64", "mac_version": (platform.mac_ver()[0] or None) if mac else None,
            "python": platform.python_version(), "mt5_native": native,
            "mt5_how": "direct" if native else "bridge"}
