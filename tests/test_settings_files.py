"""Settings backups/migrations, sound files, data backup."""
import base64
import io
import json
import wave
import zipfile

from app import backup, settings


def test_backup_and_restore(client):
    kb = {"bindings": {"man.buy": "B"}}
    client.post("/api/settings", json={"threshold": 0.3, "keybinds": kb})
    b = client.post("/api/settings/backup").json()
    client.post("/api/settings", json={"threshold": 0.5, "keybinds": {}})
    r = client.post("/api/settings/restore", json={"name": b["name"]}).json()
    assert set(r["changed"]) == {"threshold", "keybinds"} and settings.load()["keybinds"] == kb
    r = client.post("/api/settings/restore", json={"settings": {"threshold": 0.2, "bogus": 1, "early_exit": "yes",
                                                                 "keybinds": "B"}}).json()
    assert r["ignored"] == ["bogus", "early_exit", "keybinds"] and settings.load()["threshold"] == 0.2
    assert client.post("/api/settings/restore", json={"name": "../settings.json"}).status_code == 400


def test_migrations_switch_desktop_alerts_off_and_add_watchdog(sandbox):
    (sandbox / "settings.json").write_text(json.dumps({"settings_version": 6, "desktop_alerts": True,
                                                       "telegram_events": ["tp"]}))
    s = settings.load()
    assert s["desktop_alerts"] is False and s["telegram_events"] == ["tp", "watchdog"]
    assert s["settings_version"] == settings.DEFAULTS["settings_version"]


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 800)
    return buf.getvalue()


def test_sound_files(client):
    wav = _wav()
    b64 = base64.b64encode(wav).decode()
    row = client.post("/api/sounds", json={"name": "My Bell", "type": "audio/wav", "data": b64}).json()
    got = client.get(row["url"])
    assert got.headers["content-type"] == "audio/wav" and got.content == wav
    assert client.post(f"/api/sounds/{row['id']}/rename", json={"name": "Loud"}).json()["name"] == "Loud"
    exe = base64.b64encode(b"MZ\x90\x00 not audio at all").decode()
    assert client.post("/api/sounds", json={"name": "x", "type": "audio/wav", "data": exe}).status_code == 415
    big = base64.b64encode(b"RIFF" + b"\0" * (5 * 1024 * 1024 + 10)).decode()
    assert client.post("/api/sounds", json={"name": "x", "type": "audio/wav", "data": big}).status_code == 413
    assert client.delete(f"/api/sounds/{row['id']}").json() == {"ok": True}
    assert client.get(row["url"]).status_code == 404


def test_data_backup_zip_and_pruning(sandbox):
    (sandbox / "trades.db").write_bytes(b"")
    from agent import ledger
    ledger.open_trade("paper", "XAUUSD", "buy", 0.1, 2650, 2649, 2652)
    (sandbox / "hermes_memory.json").write_text("{}")
    settings.save({"backup_keep": 2})
    names = [backup.make()["name"] for _ in range(3)]
    kept = [r["name"] for r in backup.listing()]
    assert kept == names[:0:-1]                       # the two newest, newest first
    z = zipfile.ZipFile(backup.listing()[0]["path"]).namelist()
    assert "data/trades.db" in z and "data/settings.json" in z and "data/hermes_memory.json" in z
