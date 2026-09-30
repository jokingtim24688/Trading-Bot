"""Live trading plumbing: the wallet key (from .env, never returned by any route), balances and Jupiter swaps.

Only used in live mode, which needs SOL_PRIVATE_KEY in .env plus a typed LIVE in the app. SOL_RPC_URL (e.g. your
Helius URL) is used for balances and sending; the public mainnet RPC is the fallback.
"""
import base64
import os

import httpx

from app import settings

SOL_MINT = "So11111111111111111111111111111111111111112"
JUP = ("https://lite-api.jup.ag/swap/v1", "https://quote-api.jup.ag/v6")
LAMPORTS = 1_000_000_000


def _env():
    env = dict(os.environ)
    f = settings.ROOT / ".env"
    try:
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass
    return env


def rpc_url():
    return _env().get("SOL_RPC_URL") or "https://api.mainnet-beta.solana.com"


def _keypair():
    key = _env().get("SOL_PRIVATE_KEY", "").strip()
    if not key:
        return None
    from solders.keypair import Keypair
    if key.startswith("["):
        import json
        return Keypair.from_bytes(bytes(json.loads(key)))
    return Keypair.from_base58_string(key)


def info() -> dict:
    """Public facts only: is a key loaded, its public address, SOL balance."""
    try:
        kp = _keypair()
    except Exception:                                   # noqa: BLE001 - a bad key reads as "not loaded"
        return {"key_loaded": False, "pubkey": None, "sol_balance": None, "error": "SOL_PRIVATE_KEY in .env is not valid"}
    if kp is None:
        return {"key_loaded": False, "pubkey": None, "sol_balance": None}
    pub = str(kp.pubkey())
    return {"key_loaded": True, "pubkey": pub, "sol_balance": balance(pub)}


def _rpc(method, params):
    r = httpx.post(rpc_url(), json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=10)
    js = r.json()
    if "error" in js:
        raise RuntimeError(js["error"].get("message", "RPC error"))
    return js["result"]


def balance(pub: str) -> float | None:
    try:
        return _rpc("getBalance", [pub])["value"] / LAMPORTS
    except Exception:                                   # noqa: BLE001
        return None


def token_amount(pub: str, mint: str) -> int:
    res = _rpc("getTokenAccountsByOwner", [pub, {"mint": mint}, {"encoding": "jsonParsed"}])
    return sum(int(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]) for a in res["value"])


def swap(input_mint: str, output_mint: str, amount: int, slippage_bps=300) -> str:
    """Quote + swap through Jupiter, sign locally, send. Returns the signature. Raises on any failure (fail closed)."""
    from solders.transaction import VersionedTransaction
    kp = _keypair()
    if kp is None:
        raise RuntimeError("No wallet key: put SOL_PRIVATE_KEY in .env to trade live.")
    last = None
    for base_url in JUP:
        try:
            q = httpx.get(f"{base_url}/quote", params={"inputMint": input_mint, "outputMint": output_mint,
                                                        "amount": amount, "slippageBps": slippage_bps}, timeout=8)
            q.raise_for_status()
            s = httpx.post(f"{base_url}/swap", json={"quoteResponse": q.json(), "userPublicKey": str(kp.pubkey()),
                                                     "wrapAndUnwrapSol": True, "dynamicComputeUnitLimit": True,
                                                     "prioritizationFeeLamports": "auto"}, timeout=10)
            s.raise_for_status()
            raw = VersionedTransaction.from_bytes(base64.b64decode(s.json()["swapTransaction"]))
            signed = VersionedTransaction(raw.message, [kp])
            return _rpc("sendTransaction", [base64.b64encode(bytes(signed)).decode(),
                                            {"encoding": "base64", "skipPreflight": False, "maxRetries": 3}])
        except Exception as e:                          # noqa: BLE001 - try the other Jupiter host once
            last = e
    raise RuntimeError(f"Jupiter swap failed: {last}")


def buy(mint: str, sol: float) -> str:
    return swap(SOL_MINT, mint, int(sol * LAMPORTS))


def sell_all(mint: str) -> str:
    kp = _keypair()
    amt = token_amount(str(kp.pubkey()), mint)
    if amt <= 0:
        raise RuntimeError("Wallet holds none of this token.")
    return swap(mint, SOL_MINT, amt)
