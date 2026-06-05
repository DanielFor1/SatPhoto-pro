# -*- coding: utf-8 -*-
"""Task3 适配器 — 核线纠正（路径全部由界面指定）。"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from photogrammetry_suite.config import PROJECT_ROOT, TASK3_SCRIPT, ensure_output_dirs, task_output_dir
from photogrammetry_suite.suite_env import apply_task3_env


def run_task3_epipolar(
    skip_images: bool = False,
    *,
    left: str = "",
    right: str = "",
    ground_csv: str = "",
    ref_dir: str = "",
) -> str:
    """运行核线纠正全流程。"""
    if not left or not right:
        raise FileNotFoundError("请在软件界面指定左、右影像")
    if not ground_csv:
        raise FileNotFoundError("请在软件界面指定地面检核点 CSV")
    for label, path in (("左影像", left), ("右影像", right), ("地面检核点", ground_csv)):
        if not Path(path).is_file():
            raise FileNotFoundError(f"{label} 不存在: {path}")

    ensure_output_dirs()
    out = task_output_dir("task3") / "epipolar_rectification"
    out34 = out / "epipolar_images_and_rpc"
    apply_task3_env(
        left=left,
        right=right,
        ground_csv=ground_csv,
        ref_dir=ref_dir,
        output_dir=str(out),
    )

    if not TASK3_SCRIPT.is_file():
        raise FileNotFoundError(TASK3_SCRIPT)

    spec = importlib.util.spec_from_file_location("run_task3_all", TASK3_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None

    ref_path = Path(ref_dir) if ref_dir else None
    if ref_path is None or not ref_path.is_dir():
        ref_path = out34

    sys.modules["run_task3_all"] = mod
    spec.loader.exec_module(mod)

    mod.ROOT = PROJECT_ROOT
    mod.DATA = Path(left).resolve().parent
    mod.LEFT_NAME = Path(left).stem
    mod.RIGHT_NAME = Path(right).stem
    mod.GROUND_CSV = Path(ground_csv)
    mod.OUT = out
    mod.OUT34 = out34
    mod.REF = ref_path

    print(f"Task3 左 = {left}")
    print(f"Task3 右 = {right}")
    print(f"Task3 OUT = {mod.OUT}")

    argv = ["run_task3_all"]
    if skip_images:
        argv.append("--skip-images")
    old_argv = sys.argv
    sys.argv = argv
    try:
        mod.main()
    finally:
        sys.argv = old_argv

    return f"Task3 核线纠正完成，输出: {out34}"
