"""The MCP bridge status and start, without a real bridge (probe and the process are stood in for)."""
from app import bridge, jobs


def test_running_bridge_from_an_earlier_session_counts(monkeypatch, client):
    monkeypatch.setattr(bridge, "probe", lambda port: "bridge")
    monkeypatch.setattr(bridge, "_stop_leftover", lambda port: False)      # can't stop it: reuse it
    item = next(i for i in client.get("/api/setup/checklist").json()["items"] if i["id"] == "mcp")
    assert item["ok"]
    r = client.post("/api/mcp/start").json()
    assert r["running"] and r["note"] == "already running"


def test_bridge_that_dies_says_why(monkeypatch, client):
    monkeypatch.setattr(bridge, "probe", lambda port: "")
    monkeypatch.setattr(jobs.jobs, "py", lambda *a: ["python", "-c", "import sys; print('OSError: [Errno 98] address already in use'); sys.exit(1)"])
    r = client.post("/api/mcp/start")
    assert r.status_code == 500 and "address already in use" in r.json()["detail"]
    item = next(i for i in client.get("/api/setup/checklist").json()["items"] if i["id"] == "mcp")
    assert not item["ok"] and "address already in use" in item["detail"]


def test_port_taken_by_another_program(monkeypatch, client):
    monkeypatch.setattr(bridge, "probe", lambda port: "other")
    r = client.post("/api/mcp/start")
    assert r.status_code == 500 and "Another program" in r.json()["detail"]
