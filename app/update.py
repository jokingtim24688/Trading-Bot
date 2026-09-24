"""Bring this copy of the app up to date with GitHub. Run by `Trading Bot.bat` before the app opens:

    .venv\\Scripts\\python.exe -m app.update

Unlike a bare `git pull --ff-only` it copes with the things that silently kept old versions around:
- the folder is on another branch, or its branch doesn't track GitHub's -> it switches to BRANCH;
- local edits to tracked files -> saved with `git stash` (get them back with `git stash pop`);
- local commits GitHub doesn't have -> kept on a `backup/local-<time>` branch, then updated anyway;
- no internet, no git, not a git folder, or GitHub asking you to sign in -> says so and the app opens as it is.

Your data never changes: data/, logs/, models/ and .venv are ignored by git.
What happened goes to logs/update.log and data/update_status.json, which the app shows (Settings, `/api/status`).
"""
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRANCH = "claude/laughing-bell-3vt2c7"          # the branch both chats push to (TWO_CHATS.md)
STATUS = ROOT / "data" / "update_status.json"
LOG = ROOT / "logs" / "update.log"


def _git(*args, timeout=120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _out(*args) -> str:
    r = _git(*args)
    return r.stdout.strip() if r.returncode == 0 else ""


def version() -> dict:
    """The commit this copy runs, for the app to show."""
    if not (ROOT / ".git").exists() or not shutil.which("git"):
        return {"commit": None, "date": None, "branch": None}
    return {"commit": _out("rev-parse", "--short", "HEAD") or None,
            "date": _out("log", "-1", "--format=%cI") or None,
            "branch": _out("rev-parse", "--abbrev-ref", "HEAD") or None}


def update(branch: str = BRANCH) -> dict:
    notes: list[str] = []
    st = {"checked": datetime.now().isoformat(timespec="seconds"), "ok": False, "updated": False,
          "branch": branch, "before": None, "after": None, "message": "", "notes": notes}
    if not (ROOT / ".git").exists():
        st["message"] = ("This folder isn't a git copy (it was probably downloaded as a ZIP), so it can't update "
                         "itself. Re-install it with `git clone` (see README), then it updates on every start.")
        return st
    if not shutil.which("git"):
        st["message"] = "Git isn't installed, so the app can't update itself. Install it from https://git-scm.com."
        return st
    st["before"] = _out("rev-parse", "--short", "HEAD")
    f = _git("fetch", "origin", branch, timeout=180)
    if f.returncode != 0:
        err = (f.stderr or f.stdout).strip().splitlines()[-1:] or ["unknown error"]
        st["message"] = f"Couldn't reach GitHub ({err[0]}). Opening the version you have."
        return st
    target = f"origin/{branch}"
    new = _out("rev-parse", "--short", target)
    if _git("diff", "--quiet").returncode or _git("diff", "--cached", "--quiet").returncode:
        s = _git("stash", "push", "-m", f"auto-saved before update {st['checked']}")
        notes.append("Your local edits were saved with `git stash` (`git stash pop` brings them back)."
                     if s.returncode == 0 else f"Couldn't stash local edits: {s.stderr.strip()}")
    if _git("merge-base", "--is-ancestor", "HEAD", target).returncode != 0:
        keep = f"backup/local-{datetime.now():%Y%m%d-%H%M%S}"
        _git("branch", keep, "HEAD")
        notes.append(f"This copy had commits GitHub doesn't; they're kept on branch {keep}.")
    c = _git("checkout", "-B", branch, target)
    if c.returncode != 0:
        st["message"] = f"Update failed: {c.stderr.strip() or c.stdout.strip()}"
        return st
    _git("branch", "--set-upstream-to", target, branch)
    st.update(ok=True, after=new, updated=new != st["before"])
    st["message"] = (f"Updated {st['before']} -> {new}." if st["updated"] else f"Up to date ({new}).")
    return st


def main():
    t0 = time.time()
    try:
        st = update()
    except Exception as e:                          # noqa: BLE001 - never stop the app from opening
        st = {"checked": datetime.now().isoformat(timespec="seconds"), "ok": False, "updated": False,
              "message": f"Update failed: {type(e).__name__}: {e}", "notes": []}
    st["seconds"] = round(time.time() - t0, 1)
    for p in (STATUS, LOG):
        p.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(st, indent=1), encoding="utf-8")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{st['checked']} {st['message']}" + "".join(f" | {n}" for n in st.get("notes", [])) + "\n")
    print(st["message"], *st.get("notes", []), sep="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
