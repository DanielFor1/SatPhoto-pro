# -*- coding: utf-8 -*-
"""Task2 适配器 — RPC 精化 / 匹配 / DEM / 粗差剔除。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from photogrammetry_suite.config import TASK2_ROOT, ensure_output_dirs, find_python, task_output_dir
from photogrammetry_suite.suite_env import apply_task2_env

SCRIPTS = {
    "q1": TASK2_ROOT / "q1" / "scripts" / "q1_rpc_refine.py",
    "q2": TASK2_ROOT / "q2" / "scripts" / "q2_match_gcps.py",
    "q3": TASK2_ROOT / "q3" / "scripts" / "q3_dem_rpc_refine.py",
    "q4": TASK2_ROOT / "q4" / "scripts" / "q4_egm_rpc_refine.py",
    "q5": TASK2_ROOT / "q5" / "scripts" / "q5_outlier_reject_rpc_refine.py",
    "figures": TASK2_ROOT / "scripts" / "generate_report_figures.py",
}


def _run_script(key: str) -> None:
    path = SCRIPTS[key]
    if not path.is_file():
        raise FileNotFoundError(path)
    py = find_python()
    print(f"执行: {py} {path}")
    import os
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [py, str(path)],
        cwd=str(TASK2_ROOT.parent),
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{path.name} 退出码 {proc.returncode}")


def _sync_results() -> None:
    """将 task2/q*/results 同步到用户配置的 suite_outputs/task2。"""
    dst_root = task_output_dir("task2")
    dst_root.mkdir(parents=True, exist_ok=True)
    for q in ("q1", "q2", "q3", "q4", "q5"):
        src = TASK2_ROOT / q / "results"
        if not src.is_dir():
            continue
        dst = dst_root / q
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            target = dst / item.name
            if item.is_dir():
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)


def run_task2_pipeline(
    steps: list[str] | None = None,
    *,
    image: str = "",
    dom: str = "",
    dem: str = "",
    gcp_ellipsoid: str = "",
    gcp_check: str = "",
    corners: str = "",
    ref_rpc: str = "",
) -> str:
    """按顺序运行 Task2 子题。steps 默认 q1-q5。"""
    ensure_output_dirs()
    apply_task2_env(
        image=image,
        dom=dom,
        dem=dem,
        gcp_ellipsoid=gcp_ellipsoid,
        gcp_check=gcp_check,
        corners=corners,
        ref_rpc=ref_rpc,
    )
    order = steps or ["q1", "q2", "q3", "q4", "q5"]
    for key in order:
        if key not in SCRIPTS:
            raise ValueError(f"未知步骤: {key}")
        print("\n" + "=" * 60)
        print(f">>> Task2 {key}")
        print("=" * 60)
        _run_script(key)
    _sync_results()
    out = task_output_dir("task2")
    return f"Task2 完成，输出: {out}（已同步 q1–q5/results）"


def run_task2_figures() -> str:
    _run_script("figures")
    return f"配图已生成: {TASK2_ROOT / 'figures'}"
