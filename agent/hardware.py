"""Thread and GPU setup for a Ryzen 5 7600 (6C/12T) + RTX 4060 (8 GB).

Import and call `apply()` before importing numpy-heavy code so the thread env vars take effect.
Run `python -m agent.hardware` to print the detected plan.
"""
import os

from .config import HardwareConfig


def apply(hw: HardwareConfig = HardwareConfig()) -> dict:
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(var, str(hw.physical_cores))

    plan = {
        "cpu_threads_math": hw.physical_cores,
        "cpu_threads_xgb_cpu": hw.logical_threads,
        "live_predict_threads": hw.live_predict_threads,
        "xgb_cuda": False,
        "torch_cuda": False,
        "gpu": None,
    }

    if hw.train_on_gpu:
        plan["xgb_cuda"] = xgb_cuda_available()

    try:
        import torch
        if torch.cuda.is_available():
            torch.backends.cudnn.benchmark = True
            torch.set_float32_matmul_precision("high")   # TF32 on Ada tensor cores
            plan["torch_cuda"] = True
            plan["gpu"] = torch.cuda.get_device_name(0)
        torch.set_num_threads(hw.physical_cores)
    except ImportError:
        pass
    return plan


def xgb_cuda_available() -> bool:
    """True only if XGBoost really trains on the GPU (it silently falls back to CPU with a warning otherwise)."""
    import warnings
    try:
        import numpy as np
        import xgboost as xgb
        if not xgb.build_info().get("USE_CUDA"):
            return False
        d = xgb.DMatrix(np.random.rand(64, 4), label=np.random.randint(0, 2, 64))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            xgb.train({"device": "cuda", "tree_method": "hist", "verbosity": 1}, d, num_boost_round=1)
        return not any("GPU" in str(w.message) for w in caught)
    except Exception:
        return False


if __name__ == "__main__":
    for k, v in apply().items():
        print(f"{k:24s} {v}")
