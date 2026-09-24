"""The MT5 MCP bridge (mcp_server/mt5_mcp.py --http) that gives Hermes Agent its MT5 tools, on 127.0.0.1:<port>/mcp.

Whether it's running is asked of the port itself, not of the app's own process list: a bridge left over from an
earlier session (after an update, a crash, or an old copy still open) holds the port, so a new one exits at once while
the old one keeps working. `start()` reuses a bridge that already answers, and when a new one dies it returns the
reason from logs/mcp.log instead of failing silently.
"""
import time

import httpx

from .jobs import jobs

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "trading-bot", "version": "1"}}}


def probe(port: int) -> str:
    """"bridge" if our MCP bridge answers on the port, "other" if something else holds it, "" if nothing listens."""
    try:
        r = httpx.post(f"http://127.0.0.1:{port}/mcp", json=INIT, timeout=2,
                       headers={"Accept": "application/json, text/event-stream"})
    except httpx.HTTPError:
        return ""
    return "bridge" if "mt5_mcp" in r.text else "other"


def _why(job) -> str:
    lines = [x for x in job.tail(40).splitlines() if x.strip()]
    for x in reversed(lines):                         # the most telling line: the exception, else the last line
        if "Error" in x or "error" in x or "address already in use" in x.lower() or "10048" in x:
            return x.strip()[:300]
    return lines[-1].strip()[:300] if lines else "it stopped without a message (see logs/mcp.log)"


def status(port: int) -> dict:
    p = probe(port)
    job = jobs.jobs["mcp"]
    out = {"running": p == "bridge", "port": port, "ours": job.running and p == "bridge"}
    if p == "other":
        out["error"] = f"Another program is using port {port}. Pick another port in Settings -> Hermes, or close it."
    elif not p and job.proc is not None and not job.running:
        out["error"] = _why(job)
    return out


def _stop_leftover(port: int) -> bool:
    """Stop a bridge from an earlier session that still holds the port (it runs the old code). True if stopped."""
    try:
        import psutil
        for c in psutil.net_connections(kind="tcp"):
            if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN and c.pid:
                p = psutil.Process(c.pid)
                if "mt5_mcp" in " ".join(p.cmdline()):
                    p.terminate()
                    p.wait(5)
                    return True
    except Exception:                                 # noqa: BLE001 - no rights to see it: just reuse it
        pass
    return False


def start(port: int, wait: float = 8) -> dict:
    """Start the bridge unless ours already answers (a leftover one is replaced); wait until it answers or dies."""
    st = status(port)
    if st["running"] and not st["ours"] and _stop_leftover(port):
        st = status(port)
    if st["running"] or st.get("error", "").startswith("Another program"):
        return {**st, "note": "already running" if st["running"] else ""}
    job = jobs.jobs["mcp"]
    if not job.running:
        jobs.start("mcp", ["mcp_server/mt5_mcp.py", "--http", "--port", str(port)])
    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(0.4)
        if probe(port) == "bridge":
            return status(port)
        if not job.running:
            break
    st = status(port)
    if not st["running"] and "error" not in st:
        st["error"] = _why(job) if not job.running else f"started, but port {port} isn't answering yet"
    return st
