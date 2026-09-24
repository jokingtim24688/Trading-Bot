"""Manual tab: quotes, orders (SL/TP anchored to the fill), spread limit, real-account guard, notes, history."""
import pytest

from app import manual, settings, watch


def slipping(mt5, points):
    """Make market fills slip `points` against the order, moving the quote with them (as a real market does)."""
    orig = mt5.order_send

    def send(r):
        if r["action"] == mt5.TRADE_ACTION_DEAL and not r.get("position"):
            d = points * 0.01 * (1 if r["type"] == mt5.ORDER_TYPE_BUY else -1)
            mt5.S["bid"] += d
            mt5.S["ask"] += d
            r = dict(r, price=round(r["price"] + d, 2))
        return orig(r)
    return send


def test_quote_has_connection_status(client):
    q = client.get("/api/manual/quote", params={"symbol": "XAUUSD"}).json()
    assert q["connected"] is True and q["market_open"] is True and q["tick_age"] < 5
    assert q["spread"] == 25 and q["spread_ok"] is True


def test_market_order_anchors_sl_tp_to_the_fill(mt5, monkeypatch):
    monkeypatch.setattr(mt5, "order_send", slipping(mt5, 30))
    o = manual.order("XAUUSD", "buy", volume=0.1, sl_points=80, tp_points=160)
    p = mt5.POS[o["ticket"]]
    assert (p.price_open, p.sl, p.tp) == (2650.55, 2649.75, 2652.15)
    assert o["anchored"] and "note" not in o


def test_sell_and_pending_orders_use_points(mt5):
    o = manual.order("XAUUSD", "sell", volume=0.1, sl_points=80, tp_points=160)
    assert (mt5.POS[o["ticket"]].sl, mt5.POS[o["ticket"]].tp) == (2650.80, 2648.40)
    o = manual.order("XAUUSD", "buy", "limit", 0.1, price=2640, sl=1, tp=9999, sl_points=80, tp_points=160)
    assert (mt5.ORD[o["ticket"]].sl, mt5.ORD[o["ticket"]].tp) == (2639.20, 2641.60)


def test_price_running_past_the_new_stop_keeps_the_quote_levels(mt5, monkeypatch):
    base = slipping(mt5, 30)

    def crash(r):
        res = base(r)
        if r["action"] == mt5.TRADE_ACTION_DEAL and not r.get("position"):
            mt5.S["bid"], mt5.S["ask"] = 2649.60, 2649.85
        return res
    monkeypatch.setattr(mt5, "order_send", crash)
    o = manual.order("XAUUSD", "buy", volume=0.1, sl_points=80, tp_points=160)
    assert "note" in o and mt5.POS[o["ticket"]].sl == 2649.45


def test_bad_input_is_refused(mt5):
    with pytest.raises(ValueError):
        manual.order("XAUUSD", "buy", volume=0.1, sl_points=-1)
    with pytest.raises(ValueError):
        manual.order("XAUUSD", "buy", volume=0.1, sl=2651)            # stop above a buy
    mt5.S["trade_mode"] = mt5.ACCOUNT_TRADE_MODE_REAL
    with pytest.raises(ValueError, match="real-money"):
        manual.order("XAUUSD", "buy", volume=0.1)
    assert manual.order("XAUUSD", "buy", volume=0.1, confirm_real=True)["ok"]


def test_spread_limit(client):
    settings.save({"manual_max_spread": 20})
    assert client.get("/api/manual/quote", params={"symbol": "XAUUSD"}).json()["spread_ok"] is False
    r = client.post("/api/manual/order", json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1})
    assert r.status_code == 400 and "spread" in r.json()["error"]
    assert client.post("/api/manual/order", json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1,
                                                  "ignore_spread": True}).json()["ok"]
    assert client.post("/api/manual/order", json={"symbol": "XAUUSD", "side": "buy", "type": "limit", "price": 2640,
                                                  "volume": 0.1}).json()["ok"]


def test_notes_and_history(client, mt5):
    watch.tick()
    o = client.post("/api/manual/order", json={"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "sl_points": 80,
                                               "tp_points": 160, "note": "Asian high break", "tags": ["Breakout"]}).json()
    watch.tick()
    mt5.trigger(o["ticket"], mt5.DEAL_REASON_TP, 2651.85)
    watch.tick()
    row = next(r for r in client.get("/api/manual/history", params={"days": 1}).json() if r["ticket"] == o["ticket"])
    assert row["reason"] == "tp" and row["note"] == "Asian high break" and row["tags"] == ["breakout"]
    assert (row["sl"], row["tp"]) == (2649.45, 2651.85) and row["duration_s"] is not None
    client.post("/api/manual/notes", json={"ticket": o["ticket"]})
    assert client.get("/api/manual/notes").json() == {}
