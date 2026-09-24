"""app/update.py against real temporary git repos: every way an old copy used to get stuck."""
import subprocess

import pytest

from app import update

B = "claude/laughing-bell-3vt2c7"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """GitHub (a bare repo) with two commits on B, and the user's copy cloned at the first one."""
    origin, work, pc = tmp_path / "origin.git", tmp_path / "work", tmp_path / "pc"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(tmp_path, "init", "-q", "-b", B, str(work))
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        git(work, "config", k, v)
    (work / "app.txt").write_text("v1\n")
    git(work, "add", ".")
    git(work, "commit", "-qm", "v1")
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "-q", "origin", B)
    git(tmp_path, "clone", "-q", "-b", B, str(origin), str(pc))
    for k, v in (("user.email", "u@u"), ("user.name", "u")):
        git(pc, "config", k, v)
    (work / "app.txt").write_text("v2\n")
    git(work, "commit", "-qam", "v2")
    git(work, "push", "-q", "origin", B)
    monkeypatch.setattr(update, "ROOT", pc)
    return work, pc


def test_updates_an_old_copy(repos):
    work, pc = repos
    st = update.update(B)
    assert st["ok"] and st["updated"] and (pc / "app.txt").read_text() == "v2\n"
    assert update.update(B)["message"].startswith("Up to date")


def test_switches_from_another_branch(repos):
    work, pc = repos
    git(pc, "checkout", "-q", "-b", "claude/keen-planck-wi3cn5")
    st = update.update(B)
    assert st["ok"] and git(pc, "rev-parse", "--abbrev-ref", "HEAD") == B and (pc / "app.txt").read_text() == "v2\n"


def test_local_edits_are_stashed_not_lost(repos):
    work, pc = repos
    (pc / "app.txt").write_text("my edit\n")
    st = update.update(B)
    assert st["ok"] and (pc / "app.txt").read_text() == "v2\n" and "stash" in st["notes"][0]
    assert "auto-saved before update" in git(pc, "stash", "list")


def test_local_commits_are_kept_on_a_backup_branch(repos):
    work, pc = repos
    (pc / "mine.txt").write_text("x")
    git(pc, "add", ".")
    git(pc, "commit", "-qm", "mine")
    st = update.update(B)
    assert st["ok"] and (pc / "app.txt").read_text() == "v2\n"
    assert "backup/local-" in git(pc, "branch", "--list", "backup/*")


def test_offline_or_not_a_git_copy(repos, tmp_path, monkeypatch):
    work, pc = repos
    git(pc, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    st = update.update(B)
    assert not st["ok"] and "Couldn't reach GitHub" in st["message"] and (pc / "app.txt").read_text() == "v1\n"
    monkeypatch.setattr(update, "ROOT", tmp_path / "zip-download")
    (tmp_path / "zip-download").mkdir()
    assert "ZIP" in update.update(B)["message"]


def test_main_writes_status_and_log(repos, tmp_path, monkeypatch):
    work, pc = repos
    monkeypatch.setattr(update, "STATUS", tmp_path / "status.json")
    monkeypatch.setattr(update, "LOG", tmp_path / "update.log")
    monkeypatch.setattr(update, "BRANCH", B)
    assert update.main() == 0
    assert "Updated" in (tmp_path / "update.log").read_text() and (tmp_path / "status.json").exists()


def test_untracked_file_in_the_way_is_moved_aside(repos):
    work, pc = repos
    (work / "new.txt").write_text("from github\n")
    git(work, "add", ".")
    git(work, "commit", "-qm", "v3")
    git(work, "push", "-q", "origin", B)
    (pc / "new.txt").write_text("app wrote this\n")         # untracked on the PC, tracked on GitHub
    st = update.update(B)
    assert st["ok"] and (pc / "new.txt").read_text() == "from github\n"
    assert [p.name for p in pc.glob("new.txt.local-*")] and "Moved aside" in st["notes"][-1]


def test_app_written_skill_file_does_not_block_update(repos):
    """What happened on the user's PC: the quiz rewrote a tracked SKILL.md, and every update failed."""
    work, pc = repos
    (pc / "app.txt").write_text("rewritten by the app\n")
    assert update.update(B)["ok"] and (pc / "app.txt").read_text() == "v2\n"
