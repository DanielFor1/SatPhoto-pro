# -*- coding: utf-8 -*-
"""Task2 路径 — 仅使用 SatPhoto-Pro 界面注入的环境变量。"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(key: str) -> str:
    return os.environ.get(key, "").strip()


def _require_file(key: str, label: str) -> Path:
    val = _env(key)
    if not val:
        raise FileNotFoundError(f"请在软件界面指定: {label}")
    p = Path(val)
    if not p.is_file():
        raise FileNotFoundError(f"{label} 不存在: {p}")
    return p


def image_stem() -> str:
    custom = _env("SUITE_T2_STEM")
    if custom:
        return custom
    img = _env("SUITE_T2_IMAGE")
    if img:
        return Path(img).stem
    raise FileNotFoundError("请在软件界面指定待纠正影像")


def image_tif() -> Path:
    return _require_file("SUITE_T2_IMAGE", "待纠正影像")


def dom_tif() -> Path:
    return _require_file("SUITE_T2_DOM", "参考底图 DOM")


def init_rpb() -> Path:
    custom = _env("SUITE_T2_INIT_RPC")
    if custom:
        return _require_file("SUITE_T2_INIT_RPC", "初始 RPC")
    return image_tif().with_suffix(".rpb")


def ref_rpb() -> Path | None:
    custom = _env("SUITE_T2_REF_RPC")
    if not custom:
        return None
    p = Path(custom)
    return p if p.is_file() else None


def gcp_ellipsoid_csv() -> Path:
    return _require_file("SUITE_T2_GCP_ELLIPSOID", "椭球高控制点 CSV")


def gcp_check_csv() -> Path:
    return _require_file("SUITE_T2_GCP_CHECK", "检查点 CSV")


def corners_csv() -> Path:
    return _require_file("SUITE_T2_CORNERS", "四角点 CSV")


def dem_tif() -> Path:
    return _require_file("SUITE_T2_DEM", "DEM")


def q1_refined_rpb() -> Path:
    stem = image_stem()
    cand = ROOT / "task2" / "q1" / "results" / f"{stem}_refined.rpb"
    if cand.is_file():
        return cand
    raise FileNotFoundError(f"请先运行 Task2 Q1，未找到: {cand}")
