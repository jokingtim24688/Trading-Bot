"""Hermes: the Hermes Agent app is started by itself when installed; memory lives in one file."""
import os
import stat
import sys
import time

import pytest

from app import brain, memory, settings

FAKE_HERMES = f"""#!{sys.executable}
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj):
        b = json.dumps(obj).encode(); self.send_response(200); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self): self._send({{"data": []}})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self._send({{"choices": [{{"message": {{"content": "agent: " + body["messages"][-1]["content"]}}}}]}})
if sys.argv[1:] == ["gateway"]:
    HTTPServer(("127.0.0.1", 18642), H).serve_forever()
"""


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shell script as the fake hermes command")
def test_hermes_agent_starts_and_answers(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / "hermes"
    exe.parent.mkdir()
    exe.write_text(FAKE_HERMES)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(brain, "_agent", {"installed": None, "checked": 0.0, "starting": False, "error": "",
                                          "proc": None, "tried": 0.0})
    settings.save({"hermes_url": "http://127.0.0.1:18642", "assistant_backend": "auto"})
    try:
        r = brain.chat("hello")
        assert r["backend"] == "hermes_agent" and r["reply"] == "agent: hello"
    finally:
        if brain._agent["proc"]:
            brain._agent["proc"].kill()
            time.sleep(0.3)


def test_memory_file_survives_reload():
    memory.remember("I trade gold")
    memory.add_message("user", "hi")
    memory._mem = None                                            # as if the app restarted
    assert "I trade gold" in [f["text"] for f in memory.all_facts()]
    assert memory.recent_messages(1)[0]["content"] == "hi"
