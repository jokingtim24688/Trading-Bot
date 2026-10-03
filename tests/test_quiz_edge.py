"""Weak-spot report's edge check: what each setup earns on its own, from the question creators' slice cache."""
import numpy as np


def test_edge_check_reads_every_setup_found(tmp_path, monkeypatch):
    from agent import quiz as Q, quiz_report as R
    monkeypatch.setattr(Q, "SLICE_DIR", tmp_path)
    rng = np.random.default_rng(0)
    won = rng.random(2000) < 0.25                                  # a 2R setup hitting 25%: loses ~0.25R a trade
    mins = np.where(won, 50, 30).astype(np.int16)
    np.savez(tmp_path / "2021H1.npz", t=np.zeros(1), avg_reclaim_long__won=won, avg_reclaim_long__mins=mins,
             avg_reclaim_long__mae=np.zeros(2000, np.float32), pdh_test__won=np.array([True, False] * 20),
             pdh_test__mins=np.full(40, 20, np.int16))
    np.savez(tmp_path / "2021H2.tmp.npz", avg_reclaim_long__won=np.ones(5000, bool), avg_reclaim_long__mins=np.ones(5000))
    e = R.edge_check()
    rec = e["avg_reclaim_long"]
    assert rec["n"] == 2000 and abs(rec["hit"] - won.mean()) < 1e-9 and rec["verdict"] == "loses on its own"
    assert rec["trap"] == int((~won).sum()) and rec["clean"] == int(won.sum())
    assert e["pdh_test"]["verdict"] == "too few to judge"
    md = R._markdown({"generated": "2026-10-03T00:00:00", "edge": e, "weak": [], "groups": [],
                      "summary": {"built": "2026-10-03T00:00", "questions": 0, "practice": 0, "finished": 0, "stuck": 0}})
    assert "## Do the setups pay on their own?" in md and "Setups that lose on their own: Reclaimed session average" in md
