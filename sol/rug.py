"""Rug filter: six rules a token must pass before any model looks at it. Missing data fails closed."""

RULES = (
    ("mint_revoked", "mint authority still active (dev can print more)"),
    ("freeze_revoked", "freeze authority still active (dev can freeze your coins)"),
    ("lp_locked", "liquidity not burned/locked (dev can pull it)"),
    ("top10_ok", "top 10 holders own too much (excluding the pool)"),
    ("liq_ok", "liquidity too thin"),
    ("dev_ok", "dev wallet holds too much"),
)


UNCHECKED = "couldn't check it: RugCheck had no answer (blocked to be safe)"


def need_liq(snap: dict, min_liq_usd: float) -> bool:
    return snap.get("liq_usd") is not None and snap["liq_usd"] >= min_liq_usd


def check(snap: dict, min_liq_usd: float = 5000) -> dict:
    """snap keys used: mint_authority, freeze_authority (None/"" = revoked), lp_locked_pct, top10_pct, liq_usd,
    dev_pct. A key that is missing counts as a fail (we don't buy what we can't check)."""
    why = []
    if not any(k in snap for k in ("mint_authority", "freeze_authority", "lp_locked_pct", "top10_pct", "dev_pct")):
        # RugCheck gave nothing back (offline, rate-limited or the coin is seconds old): say so, instead of listing
        # five rules as if the coin had broken them
        why.append(UNCHECKED)
        if not need_liq(snap, min_liq_usd):
            why.append(RULES[4][1])
        return {"passed": False, "why": why}

    def need(key):
        return key in snap and snap[key] is not None

    if not ("mint_authority" in snap) or snap.get("mint_authority"):
        why.append(RULES[0][1])
    if not ("freeze_authority" in snap) or snap.get("freeze_authority"):
        why.append(RULES[1][1])
    if not need("lp_locked_pct") or snap["lp_locked_pct"] < 90:
        why.append(RULES[2][1])
    if not need("top10_pct") or snap["top10_pct"] > 30:
        why.append(RULES[3][1])
    if not need("liq_usd") or snap["liq_usd"] < min_liq_usd:
        why.append(RULES[4][1])
    if not need("dev_pct") or snap["dev_pct"] > 5:
        why.append(RULES[5][1])
    return {"passed": not why, "why": why}
