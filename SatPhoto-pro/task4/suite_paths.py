# -*- coding: utf-8 -*-
"""Task4 脚本统一路径 — 仅使用 SatPhoto-Pro 注入的环境变量。"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT_ROOT / "suite_outputs" / "task4"
DEFAULT_MODEL = (
    PROJECT_ROOT
    / "ONNX-CREStereo-Depth-Estimation-main"
    / "ONNX-CREStereo-Depth-Estimation-main"
    / "models"
    / "resources_iter20"
    / "crestereo_combined_iter20_480x640.onnx"
)


def _env(key: str) -> str:
    return os.environ.get(key, "").strip()


def _require(key: str, label: str) -> str:
    val = _env(key)
    if not val:
        raise FileNotFoundError(f"请在软件界面指定: {label}")
    if not Path(val).is_file():
        raise FileNotFoundError(f"{label} 不存在: {val}")
    return val


def out_dir() -> str:
    path = _env("SUITE_OUT_DIR") or str(DEFAULT_OUT)
    os.makedirs(path, exist_ok=True)
    return path


def left_epi() -> str:
    return _require("SUITE_LEFT_EPI", "左核线影像")


def right_epi() -> str:
    return _require("SUITE_RIGHT_EPI", "右核线影像")


def gt_disp() -> str:
    val = _env("SUITE_GT_DISP")
    return val if val and Path(val).is_file() else ""


def cres_model() -> str:
    return _env("SUITE_CRES_MODEL") or str(DEFAULT_MODEL)


def gray_disp_in_out(out: str) -> str:
    for name in ("第二题_gray_disparity.tif", "第二题_gray_correlation_disparity.tif"):
        p = os.path.join(out, name)
        if os.path.isfile(p):
            return p
    return os.path.join(out, "第二题_gray_disparity.tif")


def census_disp_path() -> str:
    return _env("SUITE_CENSUS_DISP") or os.path.join(out_dir(), "第一题_census_disparity.tif")


def gray_disp_path() -> str:
    custom = _env("SUITE_GRAY_DISP")
    if custom:
        return custom
    return gray_disp_in_out(out_dir())


def bm_disp_path() -> str:
    return _env("SUITE_BM_DISP") or os.path.join(out_dir(), "第三题_StereoBM_disparity_optimized.tif")


def sgbm_disp_path() -> str:
    return _env("SUITE_SGBM_DISP") or os.path.join(
        out_dir(), "第三题_StereoSGBM_disparity_optimized.tif"
    )
