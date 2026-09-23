"""Runs the agent, training, data fetch and MCP bridge as background processes.

Output goes to log files under logs/ (on disk), and the UI reads the tail of those files.
"""
import os
import subprocess
import sys
import threading
import time

from .settings import ROOT

LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)
FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class Job:
    def __init__(self, name: str):
        self.name = name
        self.proc: subprocess.Popen | None = None
        self.started = None
        self.args: list[str] = []
        self.log_path = LOGS / f"{name}.log"

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, args: list[str]):
        if self.running:
            raise RuntimeError(f"{self.name} is already running")
        self.args = args
        if getattr(self, "_log", None):
            self._log.close()
        log = self._log = open(self.log_path, "w", buffering=1, encoding="utf-8")
        log.write(f"$ {' '.join(args)}\n")
        self.proc = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                     creationflags=FLAGS, env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        self.started = time.time()

    def stop(self, timeout: float = 5):
        if not self.running:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def tail(self, lines: int = 200) -> str:
        if not self.log_path.exists():
            return ""
        with open(self.log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 64_000))
            text = f.read().decode("utf-8", "replace")
        return "\n".join(text.splitlines()[-lines:])

    def status(self) -> dict:
        return {"name": self.name, "running": self.running, "started": self.started,
                "exit_code": None if self.proc is None or self.running else self.proc.returncode,
                "args": self.args[2:] if len(self.args) > 2 else self.args}


class JobManager:
    def __init__(self):
        self.jobs = {n: Job(n) for n in ("agent", "train", "fetch", "mcp")}
        self.lock = threading.Lock()

    def py(self, *args) -> list[str]:
        exe = sys.executable
        if exe.lower().endswith("pythonw.exe"):          # child processes need a console-capable python for logs
            exe = exe[:-5] + ".exe"
        return [exe, *args]

    def start(self, name: str, args: list[str]):
        with self.lock:
            self.jobs[name].start(self.py(*args))

    def stop(self, name: str):
        self.jobs[name].stop()

    def status(self) -> dict:
        return {n: j.status() for n, j in self.jobs.items()}

    def stop_all(self):
        for j in self.jobs.values():
            j.stop()


jobs = JobManager()
