"""Every agent's own tweet monitor: each one reads a different part of X and brings back coins to look at.

The desk has four beats. One agent watches brand-new launches, one watches coins already running, one watches what
the crowd keeps repeating, and one follows the callers with a name to lose. They are separate on purpose: four
monitors on the same search would keep finding the same coin, while four angles cover the timeline between them.

What a monitor can and cannot do:

* it can decide **which coins get looked at first** — that is the whole point, the good ones are posted before they
  are indexed anywhere, and a round only has time for a handful;
* it can **not** get a coin bought. A find is a candidate, nothing more. Everything it brings back goes through the
  same gates as a coin found by the scanner: the six rug rules, the model floor, the debate and the subagents' veto.
  A post with a million likes and a mint authority still alive is thrown out by `rug.check` like any other.

Before any of that a find has to get past the monitor's own filters (a post nobody liked, an account nobody follows,
an account made this week, a coin only one voice is saying anything about), because paying a provider to read spam
and then paying GeckoTerminal and RugCheck to check it is the expensive way to find nothing.
"""
import math
import re
import threading
import time
from datetime import datetime, timezone

import httpx

from app import settings

from . import engine, feeds, ranks, store

# A Solana mint is base58: no 0, O, I or l. 32-44 characters.
MINT_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
CASHTAG_RE = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,9})\b")
# Where a mint hides in a link people paste.
LINK_RE = re.compile(r"(?:pump\.fun/(?:coin/)?|dexscreener\.com/solana/|birdeye\.so/token/|solscan\.io/token/"
                     r"|photon-sol\.tinyastro\.io/en/lp/|gmgn\.ai/sol/token/|axiom\.trade/meme/"
                     r"|neo\.bullx\.io/terminal\?chainId=1399811149&address=)([1-9A-HJ-NP-Za-km-z]{32,44})")
# Nothing about a coin, everything about your wallet.
SPAM = ("airdrop", "giveaway", "claim your", "claim now", "connect wallet", "free mint", "dm me", "dm for",
        "1000x guaranteed", "presale", "whitelist", "follow + like", "rt + like", "tag 3")
SKIP_MINTS = {"So11111111111111111111111111111111111111112",          # wrapped SOL
              "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",         # USDC
              "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}         # USDT

BEATS = [
    {"id": "launches", "name": "New launches", "model_note": "reads the launch feed",
     "what": "brand-new mints, the minute someone posts them",
     "terms": '("just launched" OR "just deployed" OR "new pair" OR "fresh mint") (pump.fun OR solana)',
     "age_min": 25, "likes": 0.5, "weight": 12},
    {"id": "runners", "name": "Runners", "model_note": "reads the movers",
     "what": "coins already moving, before the move is over",
     "terms": '(sending OR "up 100" OR "up 200" OR breaking OR "ath" OR "chart looks") (solana OR sol)',
     "age_min": 40, "likes": 1.5, "weight": 8},
    {"id": "crowd", "name": "Crowd", "model_note": "counts the voices",
     "what": "what a lot of different accounts keep repeating",
     "terms": '(solana OR sol) (buying OR bought OR "aping" OR "loaded") -"not financial advice"',
     "age_min": 60, "likes": 2.0, "weight": 6},
    {"id": "callers", "name": "Callers", "model_note": "follows the callers",
     "what": "the accounts with a name to lose, and the ones you added yourself",
     "terms": '("new call" OR "calling it" OR "my bag" OR "entry at") solana',
     "age_min": 60, "likes": 1.0, "weight": 10},
]
PRICE = {"twitterapi": 0.00015, "x": 0.005}     # dollars per post read, published by each provider
state = {"running": False, "last_round": None, "error": "", "ms": None, "provider": "off", "reads": 0,
         "per_agent": {}}
_thread: threading.Thread | None = None
_stop = threading.Event()
api_status = {"ok": None, "said": ""}


# ---------- config ----------
def cfg() -> dict:
    s = settings.load()
    return {"provider": s["x_provider"], "key": s["x_api_key"], "scan_s": max(30.0, float(s["x_scan_s"])),
            "per_beat": max(10, min(100, int(s["x_per_beat"]))), "min_likes": int(s["x_min_likes"]),
            "min_followers": int(s["x_min_followers"]), "min_account_days": float(s["x_min_account_days"]),
            "max_age_min": float(s["x_max_age_min"]), "min_voices": max(1, int(s["x_min_voices"])),
            "big_voice": int(s["x_big_voice"]), "max_per_round": max(1, int(s["x_max_per_round"])),
            "accounts": [a.strip().lstrip("@") for a in (s["x_accounts"] or "").split(",") if a.strip()],
            "over": s["x_beats"] or {}}


def crew() -> list[str]:
    from . import model
    return list(model.meta().get("metrics", {}).get("members", {}) or {}) or model.available()


def beats(c=None) -> list[dict]:
    """One beat per agent, in crew order. Overrides from settings; extra handles go to whoever reads the callers."""
    c = c or cfg()
    out = []
    for i, m in enumerate(crew()):
        b = dict(BEATS[i % len(BEATS)])
        o = (c["over"].get(m) or {}) if isinstance(c["over"], dict) else {}
        b.update(model=m, on=bool(o.get("on", True)), extra=(o.get("terms") or "").strip())
        b["query"] = _query(b, c)
        out.append(b)
    return out


def _query(b: dict, c: dict) -> str:
    q = b["extra"] or b["terms"]
    if b["id"] == "callers" and c["accounts"]:
        q = "(" + " OR ".join(f"from:{a}" for a in c["accounts"][:20]) + ") OR (" + q + ")"
    return q


# ---------- the two providers ----------
def _tw_time(v) -> float | None:
    if not v:
        return None
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            d = datetime.strptime(v, fmt)
            return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
        except (ValueError, TypeError):
            continue
    return None


def _ask(url, headers, params, timeout=12.0):
    try:
        r = httpx.get(url, headers=headers, params=params, timeout=timeout)
        if r.status_code in (401, 403):
            api_status.update(ok=False, said="the key was refused (401/403) — check it, or the plan behind it")
            return None
        if r.status_code == 429:
            api_status.update(ok=False, said="rate limited (429) — the round will be shorter or slower")
            return None
        r.raise_for_status()
        api_status.update(ok=True, said="")
        return r.json()
    except httpx.HTTPError as e:
        api_status.update(ok=False, said=f"{type(e).__name__}: no answer from the provider")
        return None


def _pull_twitterapi(query: str, n: int, key: str) -> list[dict]:
    js = _ask("https://api.twitterapi.io/twitter/tweet/advanced_search", {"X-API-Key": key},
              {"query": f"{query} -filter:retweets -filter:replies lang:en", "queryType": "Latest"})
    out = []
    for t in (js or {}).get("tweets", [])[:n]:
        a = t.get("author") or {}
        out.append({"id": str(t.get("id") or ""), "text": t.get("text") or "", "t": _tw_time(t.get("createdAt")),
                    "url": t.get("url") or f"https://x.com/i/status/{t.get('id')}",
                    "author": a.get("userName") or "?", "followers": int(a.get("followers") or 0),
                    "account_t": _tw_time(a.get("createdAt")), "verified": bool(a.get("isBlueVerified")),
                    "likes": int(t.get("likeCount") or 0), "rts": int(t.get("retweetCount") or 0),
                    "views": int(t.get("viewCount") or 0),
                    "links": [u.get("expanded_url") or "" for u in ((t.get("entities") or {}).get("urls") or [])],
                    "tags": [s.get("text") or "" for s in ((t.get("entities") or {}).get("symbols") or [])]})
    return out


def _pull_x(query: str, n: int, key: str) -> list[dict]:
    js = _ask("https://api.x.com/2/tweets/search/recent", {"Authorization": f"Bearer {key}"},
              {"query": f"{query} -is:retweet -is:reply lang:en", "max_results": max(10, min(100, n)),
               "tweet.fields": "created_at,public_metrics,entities", "expansions": "author_id",
               "user.fields": "public_metrics,created_at,verified"})
    users = {u["id"]: u for u in (((js or {}).get("includes") or {}).get("users") or [])}
    out = []
    for t in (js or {}).get("data", [])[:n]:
        a = users.get(t.get("author_id"), {})
        pm, am = t.get("public_metrics") or {}, a.get("public_metrics") or {}
        ent = t.get("entities") or {}
        out.append({"id": str(t.get("id") or ""), "text": t.get("text") or "", "t": _tw_time(t.get("created_at")),
                    "url": f"https://x.com/{a.get('username', 'i')}/status/{t.get('id')}",
                    "author": a.get("username") or "?", "followers": int(am.get("followers_count") or 0),
                    "account_t": _tw_time(a.get("created_at")), "verified": bool(a.get("verified")),
                    "likes": int(pm.get("like_count") or 0), "rts": int(pm.get("retweet_count") or 0),
                    "views": int(pm.get("impression_count") or 0),
                    "links": [u.get("expanded_url") or "" for u in (ent.get("urls") or [])],
                    "tags": [s.get("tag") or "" for s in (ent.get("cashtags") or [])]})
    return out


def pull(query: str, n: int, c: dict) -> list[dict]:
    if c["provider"] == "twitterapi" and c["key"]:
        return _pull_twitterapi(query, n, c["key"])
    if c["provider"] == "x" and c["key"]:
        return _pull_x(query, n, c["key"])
    return []


# ---------- reading a post ----------
def candidates(post: dict) -> tuple[list[str], list[str]]:
    """Mints named outright or hidden in a link, and the cashtags left to look up."""
    blob = post["text"] + " " + " ".join(post.get("links") or [])
    mints = [m for m in LINK_RE.findall(blob)]
    mints += [m for m in MINT_RE.findall(post["text"]) if m not in mints]
    tags = [t.upper() for t in (post.get("tags") or [])] or [t.upper() for t in CASHTAG_RE.findall(post["text"])]
    return [m for m in dict.fromkeys(mints) if m not in SKIP_MINTS], list(dict.fromkeys(tags))[:2]


def grade(post: dict, c: dict, beat: dict) -> str:
    """'' if the post is worth the lookup, otherwise why it isn't."""
    low = post["text"].lower()
    if any(w in low for w in SPAM):
        return "reads like coin spam"
    if post["likes"] < max(1, round(c["min_likes"] * beat["likes"])):
        return f"only {post['likes']} likes"
    if post["followers"] < c["min_followers"]:
        return f"{post['author']} has {post['followers']} followers"
    if post["account_t"] and (time.time() - post["account_t"]) / 86400 < c["min_account_days"]:
        return f"@{post['author']} is {int((time.time() - post['account_t']) / 86400)} days old"
    age = (time.time() - post["t"]) / 60 if post["t"] else 0
    if post["t"] and age > min(c["max_age_min"], beat["age_min"]):
        return f"posted {int(age)} min ago"
    return ""


def heat(post: dict, beat: dict, voices: int, weight=1.0, seconds=1) -> float:
    """0-100. Loud, fresh, well-followed and repeated by several accounts scores high; a coin two different beats
    turned up scores higher still; and the rank of the agent that found it tips the scale, the same way rank tips
    its vote in the debate."""
    age = (time.time() - post["t"]) / 60 if post["t"] else 30
    s = (beat["weight"]
         + 22 * min(1.0, math.log10(1 + post["likes"]) / 3)
         + 14 * min(1.0, math.log10(1 + post["followers"]) / 6)
         + 10 * min(1.0, math.log10(1 + post["views"]) / 6)
         + 18 * max(0.0, 1 - age / 60)
         + 16 * min(1.0, (voices - 1) / 3)
         + (6 if post["verified"] else 0)
         + 8 * min(2, max(0, seconds - 1)))          # another agent's beat found it too
    return round(min(100.0, s * weight), 1)


# ---------- one round ----------
def round_once(c=None, trade=True) -> dict:
    """Every agent reads its own beat, the finds are pooled, and the best few go through the whole pipeline."""
    t0 = time.perf_counter()
    c = c or cfg()
    if c["provider"] == "off" or not c["key"]:
        state["error"] = "no X key saved — the monitors are off"
        return {"reads": 0, "found": [], "checked": 0}
    w = ranks.weights()
    since = time.time() - 3600
    old = store.tweet_ids(since)
    pool, reads = {}, 0
    for b in beats(c):
        if not b["on"]:
            continue
        engine.state["doing"][b["model"]] = f"reading X · {b['name'].lower()}"
        posts = pull(b["query"], c["per_beat"], c)
        reads += len(posts)
        kept = 0
        for p in posts:
            if not p["id"] or p["id"] in old:
                continue
            old.add(p["id"])
            why = grade(p, c, b)
            mints, tags = candidates(p)
            if not mints and not tags:
                continue
            for m in mints or [("$" + t) for t in tags]:
                row = pool.setdefault(m, {"mint": m, "tag": m.startswith("$"), "posts": [], "models": [],
                                          "authors": set(), "why": why})
                row["posts"].append(p)
                row["authors"].add(p["author"])
                if b["model"] not in row["models"]:
                    row["models"].append(b["model"])
                row.setdefault("beat", b)           # the agent that saw it first owns the find
                if not why:
                    row["why"] = ""
                    kept += 1
        state["per_agent"][b["model"]] = {"beat": b["id"], "read": len(posts), "kept": kept, "t": time.time()}
    state["reads"] += reads

    found = []
    for row in pool.values():
        p = max(row["posts"], key=lambda x: x["likes"])
        voices = len(row["authors"]) + (store.tweet_voices(row["mint"], since) if not row["tag"] else 0)
        row.update(post=p, voices=voices,
                   heat=heat(p, row["beat"], voices, w.get(row["beat"]["model"], 1.0), len(row["models"])))
        if not row["why"] and voices < c["min_voices"] and p["followers"] < c["big_voice"]:
            row["why"] = f"only {voices} account{'' if voices == 1 else 's'} talking about it"
        found.append(row)
    found.sort(key=lambda r: -r["heat"])

    checked = 0
    for row in found:
        blocked = row["why"] or ("" if checked < c["max_per_round"] else "further down the list than this round got")
        rid = store.record_tweet({"mint": None if row["tag"] else row["mint"],
                                  "symbol": row["mint"].lstrip("$") if row["tag"] else None,
                                  "model": row["beat"]["model"], "beat": row["beat"]["id"],
                                  "tweet_id": row["post"]["id"], "author": row["post"]["author"],
                                  "followers": row["post"]["followers"], "likes": row["post"]["likes"],
                                  "url": row["post"]["url"], "text": row["post"]["text"][:280],
                                  "tweet_t": row["post"]["t"], "heat": row["heat"], "voices": row["voices"],
                                  "status": "filtered" if blocked else "checking", "why": blocked,
                                  "also": ",".join(row["models"][1:]) or None})
        row["id"] = rid
        if blocked:
            continue
        checked += 1
        _check(row, rid, trade)
    state.update(last_round=time.time(), error="", ms=round((time.perf_counter() - t0) * 1000))
    return {"reads": reads, "found": found, "checked": checked}


def _check(row: dict, rid: int, trade: bool):
    """A find joins the ordinary pipeline here. Nothing below this line knows it came from a post."""
    try:
        snaps = feeds.search_pools(row["mint"].lstrip("$")) if row["tag"] else feeds.token_pools(row["mint"])
        snap = snaps[0] if snaps else None
        if not snap:
            store.tweet_verdict(rid, "filtered", why="no Solana pool for it yet")
            return
        if store.seen_before(snap["mint"]):
            store.tweet_verdict(rid, "filtered", why="the scanner already checked this one")
            return
        snap = {**snap, "found_via": "x", "found_by": row["post"]["author"], "found_url": row["post"]["url"],
                "found_heat": row["heat"], "found_model": row["beat"]["model"]}
        out = engine.evaluate(snap, trade=trade)              # rug rules -> model -> debate -> subagents
        gate = out.get("gate") or {}
        store.tweet_verdict(rid, "traded" if out["verdict"] == "BUY" else "blocked", verdict=out["verdict"],
                            why="" if gate.get("passed") else (gate.get("why") or ["blocked"])[0])
    except Exception as e:                                    # noqa: BLE001 - one bad find never stops the round
        store.tweet_verdict(rid, "error", why=str(e)[:120])


# ---------- the thread ----------
def _loop():
    while state["running"] and not _stop.is_set():
        c = cfg()
        try:
            round_once(c)
        except Exception as e:                                # noqa: BLE001
            state["error"] = str(e)
        _stop.wait(c["scan_s"])


def set_monitor(on: bool) -> bool:
    global _thread
    c = cfg()
    if on and (c["provider"] == "off" or not c["key"]):
        raise ValueError("Save an X API key first — the monitors have nothing to read without one.")
    state["running"] = bool(on)
    _stop.clear() if on else None
    if on and (_thread is None or not _thread.is_alive()):
        _thread = threading.Thread(target=_loop, name="sol-tweets", daemon=True)
        _thread.start()
    return state["running"]


def stop():
    state["running"] = False
    _stop.set()


# ---------- what the app shows ----------
def save_key(provider: str, key: str | None):
    if provider not in ("off", "twitterapi", "x"):
        raise ValueError("provider must be off, twitterapi or x")
    patch = {"x_provider": provider}
    if key is not None and key.strip():
        patch["x_api_key"] = key.strip()                      # stays in data/settings.json, no route reads it back
    if provider == "off":
        stop()
    settings.save(patch)
    api_status.update(ok=None, said="")
    return provider


def set_beat(model: str, on: bool | None = None, terms: str | None = None) -> dict:
    s = settings.load()
    over = dict(s["x_beats"] or {})
    b = dict(over.get(model) or {})
    if on is not None:
        b["on"] = bool(on)
    if terms is not None:
        b["terms"] = terms.strip()[:400]
    over[model] = b
    settings.save({"x_beats": over})
    return b


def cost(c=None) -> dict:
    """What the monitors cost to run, in the provider's own published price per post read."""
    c = c or cfg()
    live = [b for b in beats(c) if b["on"]]
    per_day = len(live) * c["per_beat"] * (86400 / c["scan_s"])
    rate = PRICE.get(c["provider"], 0)
    return {"posts_per_day": int(per_day), "usd_per_day": round(per_day * rate, 2), "rate": rate,
            "monitors": len(live)}


def view() -> dict:
    c = cfg()
    rows = store.tweet_finds(40)
    return {"provider": c["provider"], "key_set": bool(c["key"]), "running": state["running"],
            "last_round": state["last_round"], "ms": state["ms"], "error": state["error"],
            "api": dict(api_status), "cost": cost(c), "reads": state["reads"],
            "config": {k: c[k] for k in ("scan_s", "per_beat", "min_likes", "min_followers", "min_account_days",
                                         "max_age_min", "min_voices", "big_voice", "max_per_round")},
            "accounts": c["accounts"],
            "beats": [{**{k: b[k] for k in ("id", "name", "what", "model", "on", "query", "model_note")},
                       "live": state["per_agent"].get(b["model"], {}),
                       "stats": store.tweet_stats(b["model"])} for b in beats(c)],
            "finds": rows, "stats": store.tweet_stats()}


def agent_view(model: str) -> dict:
    c = cfg()
    b = next((x for x in beats(c) if x["model"] == model), None)
    return {"on": bool(b and b["on"]) and state["running"], "beat": b and {k: b[k] for k in
            ("id", "name", "what", "query", "model_note", "on")},
            "stats": store.tweet_stats(model), "finds": store.tweet_finds(8, model),
            "live": state["per_agent"].get(model, {})}
