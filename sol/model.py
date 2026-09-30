"""The model crew: XGBoost, LightGBM, Random Forest (and CatBoost when installed).

Lifecycle the user asked for: while training, the crew is SPLIT (each model trains on its own, in parallel, and can be
watched separately). When training ends they are MERGED into one bot: a single file (data/sol_models/bot.joblib)
holding every member plus a stacking judge that learned how much to trust each one. Pressing Train again splits
them. predict() on the merged bot is one call and takes well under 5 ms for a token.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from app import settings

from .features import FEATURES

MEMBERS = ("xgb", "lgbm", "rf", "cat")
_lock = threading.Lock()
_bot = {"members": {}, "judge": None, "meta": {}}
state = {"merged": False, "training": False, "progress": 0.0, "stage": "", "error": "", "members": {}}


def model_dir():
    return settings.DATA / "sol_models"


def _make(name):
    if name == "xgb":
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=250, max_depth=5, learning_rate=0.06, subsample=0.9, colsample_bytree=0.9,
                             eval_metric="logloss", n_jobs=2, tree_method="hist", verbosity=0)
    if name == "lgbm":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, subsample=0.9, n_jobs=2, verbose=-1)
    if name == "rf":
        from sklearn.ensemble import RandomForestClassifier
        return RandomForestClassifier(n_estimators=250, min_samples_leaf=3, n_jobs=2, random_state=7)
    if name == "cat":
        from catboost import CatBoostClassifier
        return CatBoostClassifier(iterations=300, depth=6, verbose=False, thread_count=2, allow_writing_files=False)
    raise ValueError(name)


class FastForest:
    """A trained RandomForest flattened into arrays: all trees walked together with numpy. Same answers as
    sklearn's predict_proba, ~0.2 ms for one coin instead of ~75 ms (sklearn pays thread and Python overhead per tree)."""

    def __init__(self, rf):
        trees = [e.tree_ for e in rf.estimators_]
        n = max(t.node_count for t in trees)
        k = len(trees)
        self.left = np.full((k, n), -1, np.int32); self.right = np.full((k, n), -1, np.int32)
        self.feat = np.zeros((k, n), np.int32); self.thr = np.zeros((k, n), np.float64)
        self.p1 = np.zeros((k, n), np.float64)
        pos = list(rf.classes_).index(1)
        for i, t in enumerate(trees):
            c = t.node_count
            self.left[i, :c], self.right[i, :c] = t.children_left, t.children_right
            self.feat[i, :c], self.thr[i, :c] = np.maximum(t.feature, 0), t.threshold
            v = t.value[:, 0, :]
            self.p1[i, :c] = v[:, pos] / np.maximum(v.sum(1), 1e-12)
        self.depth = max(e.get_depth() for e in rf.estimators_)
        self.rows = np.arange(k)
        self.classes_ = rf.classes_

    def predict_proba(self, X):
        X = np.asarray(X, np.float64)
        out = np.empty((len(X), 2))
        for j, x in enumerate(X):
            node = np.zeros(len(self.rows), np.int32)
            for _ in range(self.depth):
                lf = self.left[self.rows, node]
                leaf = lf < 0
                if leaf.all():
                    break
                go_left = x[self.feat[self.rows, node]] <= self.thr[self.rows, node]
                node = np.where(leaf, node, np.where(go_left, lf, self.right[self.rows, node]))
            p = self.p1[self.rows, node].mean()
            out[j] = (1 - p, p)
        return out


def _fast(members: dict) -> dict:
    return {m: FastForest(e) if m == "rf" and not isinstance(e, FastForest) else e for m, e in members.items()}


def available() -> list[str]:
    out = []
    for m in MEMBERS:
        try:
            _make(m)
            out.append(m)
        except Exception:
            pass
    return out


def load() -> bool:
    import joblib
    f = model_dir() / "bot.joblib"
    if not f.exists():
        return False
    try:
        b = joblib.load(f)
    except Exception as e:
        state["error"] = f"couldn't load the bot: {e}"
        return False
    b["members"] = _fast(b["members"])
    with _lock:
        _bot.update(b)
    state["merged"] = True
    return True


def loaded() -> bool:
    return bool(_bot["members"]) and _bot["judge"] is not None


def meta() -> dict:
    return dict(_bot["meta"])


def predict(x: np.ndarray) -> dict:
    """Each member's probability that this token is a good buy, plus the merged bot's own answer."""
    with _lock:
        members, judge = dict(_bot["members"]), _bot["judge"]
    if not members:
        return {}
    x = np.asarray(x, dtype=np.float32).reshape(1, -1)
    probs = {m: float(est.predict_proba(x)[0, 1]) for m, est in members.items()}
    stack = np.array([[probs[m] for m in members]], dtype=np.float32)
    probs["bot"] = float(judge.predict_proba(stack)[0, 1]) if judge is not None else float(np.mean(list(probs.values())))
    return probs


def train(X: np.ndarray, y: np.ndarray, synthetic_share: float = 0.0, on_progress=None) -> dict:
    """Split -> each member trains in parallel -> out-of-fold answers teach the judge -> merge into one bot file."""
    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import precision_score, roc_auc_score
    from sklearn.model_selection import StratifiedKFold, train_test_split

    if state["training"]:
        raise RuntimeError("Training is already running.")
    X, y = np.asarray(X, dtype=np.float32), np.asarray(y, dtype=int)
    if len(y) < 60 or len(set(y.tolist())) < 2:
        raise ValueError("Need at least 60 answered questions with both good and bad buys to train.")
    names = available()
    if len(names) < 2:
        raise RuntimeError("Install at least two of xgboost, lightgbm, scikit-learn (pip install -r requirements.txt).")
    state.update(training=True, merged=False, progress=0.0, stage="splitting the bot into its models", error="",
                 members={m: {"stage": "waiting", "auc": None} for m in names})
    t0 = time.time()
    try:
        Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, stratify=y, random_state=7)
        folds = list(StratifiedKFold(5, shuffle=True, random_state=7).split(Xtr, ytr))
        oof = {m: np.zeros(len(ytr), dtype=np.float32) for m in names}
        done = [0]
        total = len(names) * (len(folds) + 1)

        def work(m):
            state["members"][m]["stage"] = "training"
            for tr, va in folds:
                est = _make(m).fit(Xtr[tr], ytr[tr])
                oof[m][va] = est.predict_proba(Xtr[va])[:, 1]
                done[0] += 1
                state["progress"] = done[0] / total
            est = _make(m).fit(Xtr, ytr)
            done[0] += 1
            state["progress"] = done[0] / total
            p = est.predict_proba(Xte)[:, 1]
            state["members"][m].update(stage="done", auc=round(float(roc_auc_score(yte, p)), 3))
            return m, est

        with ThreadPoolExecutor(max_workers=len(names)) as ex:
            fitted = dict(ex.map(work, names))
        state["stage"] = "merging the models into one bot"
        judge = LogisticRegression(C=1.0).fit(np.column_stack([oof[m] for m in names]), ytr)
        test_stack = np.column_stack([fitted[m].predict_proba(Xte)[:, 1] for m in names])
        pt = judge.predict_proba(test_stack)[:, 1]
        thr = float(settings.load().get("sol_buy_threshold", 0.78))
        buys = pt >= thr
        metrics = {"auc": round(float(roc_auc_score(yte, pt)), 3), "n_test": int(len(yte)),
                   "precision_at_buy": round(float(precision_score(yte, buys, zero_division=0)), 3) if buys.any() else None,
                   "members": {m: state["members"][m]["auc"] for m in names},
                   "weights": dict(zip(names, [round(float(w), 3) for w in judge.coef_[0]]))}
        b = {"members": fitted, "judge": judge,
             "meta": {"trained_at": time.time(), "n_samples": int(len(y)), "synthetic": round(synthetic_share, 3),
                      "features": FEATURES, "metrics": metrics, "seconds": round(time.time() - t0, 1)}}
        model_dir().mkdir(parents=True, exist_ok=True)
        joblib.dump(b, model_dir() / "bot.joblib")
        b = {**b, "members": _fast(fitted)}
        with _lock:
            _bot.update(b)
        state.update(merged=True, progress=1.0, stage="merged into one bot")
        return b["meta"]
    except Exception as e:
        state.update(error=str(e), stage="failed")
        load()                                            # fall back to the last merged bot, if any
        raise
    finally:
        state["training"] = False
