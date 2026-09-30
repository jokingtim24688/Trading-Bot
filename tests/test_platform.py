"""Mac / Linux support: the MT5 bridge (RemoteMT5 <-> serve), value encoding, system notifications, the Mac installer's
detection, platform info and the libomp hint. The bridge runs here against the fake MetaTrader5 package."""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def bridge():
    """The Windows side of the bridge, serving the fake MetaTrader5 package on a free local port."""
    from agent import mt5_remote
    port = _free_port()
    t = threading.Thread(target=mt5_remote.serve, args=("127.0.0.1", port, "s3cret"), daemon=True)
    t.start()
    for _ in range(100):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.02)
    return f"http://127.0.0.1:{port}"


def test_encode_decode_round_trip():
    from agent.mt5_remote import decode, encode
    Req = namedtuple("TradeRequest", "action symbol volume")
    Res = namedtuple("OrderSendResult", "retcode deal request")
    res = Res(10009, 55, Req(1, "XAUUSD", 0.01))
    back = decode(encode(res))
    assert back.retcode == 10009 and back.request.symbol == "XAUUSD" and back._asdict()["deal"] == 55
    rates = np.array([(1700000000, 1.5, 2.5, 1.0, 2.0, 10, 25, 0)],
                     dtype=[("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"),
                            ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")])
    r2 = decode(encode(rates))
    assert r2.dtype == rates.dtype and r2.tolist() == rates.tolist()
    aware, naive = datetime(2026, 9, 30, 12, tzinfo=timezone.utc), datetime(2026, 9, 30, 12)
    assert decode(encode(aware)) == aware and decode(encode(naive)) == naive and decode(encode(naive)).tzinfo is None
    assert decode(encode({1: (2, 3), "a": None})) == {1: [2, 3], "a": None}
    assert decode(encode(np.float64(1.25))) == 1.25


def test_remote_mt5_talks_to_the_bridge(bridge):
    from agent.mt5_remote import RemoteMT5
    m = RemoteMT5(bridge, "s3cret")
    assert m.initialize() is True
    assert m.TIMEFRAME_M1 == 1 and m.ORDER_TYPE_SELL == 1          # constants come from the Windows side
    acc = m.account_info()
    assert acc.login == 1 and acc.currency == "USD"
    assert m.symbol_info("XAUUSD").point == 0.01 and m.symbol_info("NOPE") is None
    r = m.order_send({"action": m.TRADE_ACTION_DEAL, "symbol": "XAUUSD", "volume": 0.01, "type": m.ORDER_TYPE_BUY,
                      "price": 2650.25, "sl": 2640.0, "tp": 2670.0, "magic": 1, "comment": "t"})
    assert r.retcode == m.TRADE_RETCODE_DONE
    assert [p.symbol for p in m.positions_get()] == ["XAUUSD"]
    assert m.last_error() == (1, "ok")
    with pytest.raises(AttributeError):
        m.NOT_A_REAL_CONSTANT
    assert getattr(m, "ORDER_TYPE_BUY_STOP_LIMIT", -1) != -1        # getattr defaults still work for known names


def test_bridge_refuses_wrong_token_and_says_why(bridge):
    from agent.mt5_remote import RemoteMT5
    bad = RemoteMT5(bridge, "wrong")
    assert bad.initialize() is False and "token" in bad.last_error()[1]
    gone = RemoteMT5(f"http://127.0.0.1:{_free_port()}", "x")
    assert gone.account_info() is None and "can't reach the MT5 bridge" in gone.last_error()[1]
    none = RemoteMT5(settings_file=ROOT / "tests" / "no-such-settings.json")
    assert none.initialize() is False and "only runs on Windows" in none.last_error()[1]
    assert none.TIMEFRAME_M1 == 1                                      # built-in constants before any bridge


def test_bridge_needs_a_token_to_listen_on_the_network():
    from agent import mt5_remote
    with pytest.raises(SystemExit):
        mt5_remote.serve("0.0.0.0", _free_port(), "")


def test_app_uses_the_bridge_message_when_mt5_is_remote(monkeypatch, tmp_path):
    from agent.mt5_remote import RemoteMT5
    from app import mt5_service
    monkeypatch.setattr(mt5_service, "mt5", RemoteMT5(settings_file=tmp_path / "missing.json"))
    with pytest.raises(mt5_service.MT5Unavailable, match="Settings > MT5 bridge"):
        mt5_service.account()


def test_status_platform_and_bridge_test_route(bridge):
    from fastapi.testclient import TestClient
    from app import server
    c = TestClient(server.app)
    pf = c.get("/api/status").json()["platform"]
    assert pf["os"] in ("mac", "windows", "linux") and "mt5_native" in pf
    assert c.post("/api/mt5/bridge/test", json={"url": "", "token": ""}).json()["ok"] is False
    r = c.post("/api/mt5/bridge/test", json={"url": bridge, "token": "s3cret"}).json()
    assert r["ok"] and r["account"]["login"] == 1 and r["account"]["demo"] is True
    assert c.post("/api/mt5/bridge/test", json={"url": bridge, "token": "nope"}).json()["ok"] is False


def test_mac_notification_escapes_quotes():
    from app.notify import mac_command
    cmd = mac_command('Take profit "hit"', 'XAUUSD closed at "2650" \\ done')
    assert cmd[:2] == ["osascript", "-e"]
    assert '\\"2650\\"' in cmd[2] and 'Take profit \\"hit\\"' in cmd[2] and "\\\\ done" in cmd[2]


def test_libomp_hint_on_a_mac(monkeypatch):
    from sol import model
    def fake_make(m):
        if m == "xgb":
            raise OSError("dlopen(libxgboost.dylib): Library not loaded: @rpath/libomp.dylib")
        if m == "cat":
            raise ImportError("No module named 'catboost'")
        return object()
    monkeypatch.setattr(model, "_make", fake_make)
    monkeypatch.setattr(model.sys, "platform", "darwin")
    monkeypatch.setitem(model._avail, "at", 0.0)
    assert model.available() == ["lgbm", "rf"]
    p = model.problems()
    assert "brew install libomp" in p["xgb"] and p["cat"] == "not installed (optional)"
    monkeypatch.setitem(model._avail, "at", 0.0)


needs_bash = pytest.mark.skipif(not shutil.which("bash") or os.name == "nt", reason="needs bash")


@needs_bash
def test_installer_script_parses_and_detects_this_system():
    script = ROOT / "Trading Bot.command"
    assert os.access(script, os.X_OK), "Trading Bot.command must stay executable (git mode 100755)"
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    out = subprocess.run(["bash", str(script), "--check"], capture_output=True, text=True, timeout=60).stdout
    assert out.startswith("Detected: ") and "MetaTrader 5:" in out


@needs_bash
def test_installer_detects_a_mac(tmp_path):
    """Stand-ins for uname, sw_vers, xcode-select, sysctl and brew make the script believe it's on an Apple silicon Mac."""
    b = tmp_path / "bin"
    b.mkdir()
    prefix = tmp_path / "brew"
    (prefix / "opt" / "libomp" / "lib").mkdir(parents=True)
    (prefix / "opt" / "libomp" / "lib" / "libomp.dylib").write_text("")
    stubs = {"uname": 'case "$1" in -s) echo Darwin;; -m) echo arm64;; *) echo Darwin;; esac',
             "sw_vers": "echo 14.5", "xcode-select": "echo /Library/Developer/CommandLineTools", "sysctl": "echo 0",
             "brew": f'[ "$1" = "--prefix" ] && echo {prefix}'}
    for name, body in stubs.items():
        (b / name).write_text(f"#!/bin/bash\n{body}\n")
        (b / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{b}:/usr/bin:/bin"}
    out = subprocess.run(["bash", str(ROOT / "Trading Bot.command"), "--check"], capture_output=True, text=True,
                         timeout=60, env=env).stdout
    assert "macOS 14.5 on Apple silicon (arm64)" in out
    assert "libomp:              installed" in out and "Command Line Tools:  installed" in out
    assert "runs on Windows only" in out
