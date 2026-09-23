"""XGBoost 3-class model (short / flat / long). Trains on the RTX 4060, predicts on the CPU."""
import json
from pathlib import Path

import numpy as np
import xgboost as xgb

from .config import HardwareConfig

PARAMS = {
    "objective": "multi:softprob",
    "num_class": 3,
    "tree_method": "hist",
    "max_bin": 256,
    "max_depth": 6,
    "learning_rate": 0.03,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 20,
    "reg_lambda": 2.0,
    "eval_metric": "mlogloss",
    "verbosity": 0,
}


class SignalModel:
    def __init__(self, booster: xgb.Booster | None = None, features: list[str] | None = None, meta: dict | None = None):
        self.booster = booster
        self.features = features or []
        self.meta = meta or {}

    @classmethod
    def train(cls, X_tr, y_tr, X_va, y_va, use_gpu: bool, hw: HardwareConfig = HardwareConfig(), rounds: int = 2000):
        params = dict(PARAMS)
        params["device"] = "cuda" if use_gpu else "cpu"
        if not use_gpu:
            params["nthread"] = hw.logical_threads
        dtr = xgb.DMatrix(X_tr, label=y_tr, feature_names=list(X_tr.columns))
        dva = xgb.DMatrix(X_va, label=y_va, feature_names=list(X_va.columns))
        booster = xgb.train(params, dtr, rounds, evals=[(dva, "valid")], early_stopping_rounds=100, verbose_eval=200)
        booster.set_param({"device": "cpu", "nthread": hw.live_predict_threads})   # live inference on CPU
        return cls(booster, list(X_tr.columns), {"device_trained": params["device"], "best_iteration": booster.best_iteration})

    def predict_proba(self, X) -> np.ndarray:
        d = xgb.DMatrix(X[self.features], feature_names=self.features)
        best = self.meta.get("best_iteration")
        return self.booster.predict(d, iteration_range=(0, best + 1) if best is not None else (0, 0))

    def save(self, directory: str, symbol: str):
        p = Path(directory)
        p.mkdir(parents=True, exist_ok=True)
        self.booster.save_model(p / f"{symbol}_M1.json")
        (p / f"{symbol}_M1.meta.json").write_text(json.dumps({"features": self.features, **self.meta}, indent=2))

    @classmethod
    def load(cls, directory: str, symbol: str, hw: HardwareConfig = HardwareConfig()):
        p = Path(directory)
        booster = xgb.Booster()
        booster.load_model(p / f"{symbol}_M1.json")
        booster.set_param({"device": "cpu", "nthread": hw.live_predict_threads})
        meta = json.loads((p / f"{symbol}_M1.meta.json").read_text())
        m = cls(booster, meta.pop("features"), meta)
        return m
