# -*- coding: utf-8 -*-
"""Task1 路径 — 仅使用 SatPhoto-Pro 界面注入的环境变量。"""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FALLBACK_OUT = HERE / "results"


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


def out_dir() -> str:
    path = _env("SUITE_T1_OUT") or str(FALLBACK_OUT)
    os.makedirs(path, exist_ok=True)
    return path


def images() -> list[str]:
    custom = _env("SUITE_T1_IMAGES")
    if custom:
        return [s.strip() for s in custom.split(",") if s.strip()]
    raise FileNotFoundError("请在软件界面指定待纠正影像")


def dom_spec_csv_optional() -> Path | None:
    val = _env("SUITE_T1_DOM_SPEC")
    if not val:
        return None
    p = Path(val)
    return p if p.is_file() else None


def reference_dom() -> Path:
    for key in ("SUITE_T1_REF_DOM", "SUITE_T1_DOM"):
        val = _env(key)
        if val and Path(val).is_file():
            return Path(val)
    raise FileNotFoundError("请在软件界面指定参考底图 DOM")


def dem_path() -> Path:
    return _require_file("SUITE_T1_DEM", "DEM")


def ground_points_csv() -> Path | None:
    val = _env("SUITE_T1_GROUND_POINTS")
    if not val:
        return None
    p = Path(val)
    return p if p.is_file() else None


def ref_compare_dir() -> Path | None:
    val = _env("SUITE_T1_REF_DOM") or _env("SUITE_T1_DOM")
    if not val:
        return None
    p = Path(val)
    if p.is_file():
        return p.parent
    if p.is_dir():
        return p
    return None


def image_paths(stem: str) -> tuple[Path, Path]:
    explicit = _env("SUITE_T1_IMAGE")
    if not explicit:
        raise FileNotFoundError("请在软件界面指定待纠正影像")
    tif = Path(explicit)
    if tif.stem != stem:
        raise FileNotFoundError(f"影像名与当前任务不一致: 需要 {stem}, 实际 {tif.stem}")
    rpc = Path(_env("SUITE_T1_RPC") or tif.with_suffix(".rpb"))
    if not rpc.is_file():
        raise FileNotFoundError(f"未找到 RPC: {rpc}")
    return rpc, tif
