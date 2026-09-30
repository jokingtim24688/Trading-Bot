"""Market data for the trenches: GeckoTerminal (new pools, prices, 1-minute candles) and RugCheck (authorities,
locked liquidity, holders). Every call is short-timeout and returns None/[] on failure so the bot fails closed."""
import time
from datetime import datetime, timezone

import httpx

GT = "https://api.geckoterminal.com/api/v2/networks/solana"
RUGCHECK = "https://api.rugcheck.xyz/v1/tokens/{mint}/report"
HEAD = {"accept": "application/json", "user-agent": "TradingBot/1.0"}
status = {"geckoterminal": None, "rugcheck": None, "jupiter": None}     # True ok / False failing / None untried
_last_call = [0.0]


def _get(url, api, params=None, timeout=8.0):
    wait = 2.1 - (time.time() - _last_call[0])          # GeckoTerminal free tier: ~30 calls a minute
    if api == "geckoterminal" and wait > 0:
        time.sleep(wait)
    try:
        if api == "geckoterminal":
            _last_call[0] = time.time()
        r = httpx.get(url, params=params, headers=HEAD, timeout=timeout)
        r.raise_for_status()
        status[api] = True
        return r.json()
    except (httpx.HTTPError, ValueError):
        status[api] = False
        return None


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def pool_snapshot(p: dict) -> dict:
    """GeckoTerminal pool JSON -> the snapshot the bot uses."""
    a = p.get("attributes", {})
    base = (p.get("relationships", {}).get("base_token", {}).get("data", {}).get("id") or "").replace("solana_", "")
    tx = (a.get("transactions") or {}).get("m5") or {}
    created = a.get("pool_created_at")
    age = None
    if created:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(created.replace("Z", "+00:00"))).total_seconds() / 60
    return {"mint": base, "pool": a.get("address"), "symbol": (a.get("name") or "?").split(" / ")[0][:16],
            "name": a.get("name"), "price_usd": _f(a.get("base_token_price_usd")), "liq_usd": _f(a.get("reserve_in_usd")),
            "fdv_usd": _f(a.get("fdv_usd")), "age_min": age, "buys_5m": int(tx.get("buys") or 0),
            "sells_5m": int(tx.get("sells") or 0), "vol_5m": _f((a.get("volume_usd") or {}).get("m5")),
            "chg_5m": _f((a.get("price_change_percentage") or {}).get("m5"))}


def new_pools(pages=1) -> list[dict]:
    out = []
    for page in range(1, pages + 1):
        js = _get(f"{GT}/new_pools", "geckoterminal", {"page": page})
        if not js:
            break
        out += [pool_snapshot(p) for p in js.get("data", [])]
    return [s for s in out if s["mint"]]


def trending_pools(pages=1, dex=None) -> list[dict]:
    out = []
    for page in range(1, pages + 1):
        url = f"{GT}/dexes/{dex}/pools" if dex else f"{GT}/trending_pools"
        js = _get(url, "geckoterminal", {"page": page})
        if not js:
            break
        out += [pool_snapshot(p) for p in js.get("data", [])]
    return [s for s in out if s["mint"]]


def candles(pool: str, limit=300) -> list[list[float]]:
    """1-minute candles, oldest first: [t, open, high, low, close, volume_usd]."""
    js = _get(f"{GT}/pools/{pool}/ohlcv/minute", "geckoterminal", {"aggregate": 1, "limit": limit, "currency": "usd"})
    rows = (((js or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    return sorted(([float(x) for x in r[:6]] for r in rows), key=lambda r: r[0])


def prices(mints: list[str]) -> dict[str, float]:
    if not mints:
        return {}
    js = _get(f"{GT}/simple/token_price/{','.join(mints[:30])}", "geckoterminal")
    got = (((js or {}).get("data") or {}).get("attributes") or {}).get("token_prices") or {}
    return {m: _f(v) for m, v in got.items() if _f(v) > 0}


def rug_facts(mint: str) -> dict:
    """Authorities, locked LP %, top-10 % (pools and AMMs excluded) and the creator's share, from RugCheck."""
    js = _get(RUGCHECK.format(mint=mint), "rugcheck", timeout=6)
    if not js:
        return {}
    markets = js.get("markets") or []
    lp = max((_f((m.get("lp") or {}).get("lpLockedPct")) for m in markets), default=None) if markets else None
    pools = {m.get("pubkey") for m in markets} | {(m.get("lp") or {}).get("lpMint") for m in markets}
    holders = [h for h in (js.get("topHolders") or []) if h.get("owner") not in pools and h.get("address") not in pools]
    creator = js.get("creator")
    dev = sum(_f(h.get("pct")) for h in holders if creator and h.get("owner") == creator)
    return {"mint_authority": js.get("mintAuthority") or "", "freeze_authority": js.get("freezeAuthority") or "",
            "lp_locked_pct": lp, "top10_pct": sum(_f(h.get("pct")) for h in holders[:10]) if holders else None,
            "dev_pct": dev, "rug_score": js.get("score_normalised") or js.get("score")}
