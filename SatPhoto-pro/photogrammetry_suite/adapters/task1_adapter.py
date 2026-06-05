# -*- coding: utf-8 -*-
"""Task1 适配器 — RPC 正射纠正全流程。"""

from __future__ import annotations

import os
import runpy
import shutil
import sys
from pathlib import Path

from photogrammetry_suite.config import TASK1_CODE, ensure_output_dirs, task_output_dir
from photogrammetry_suite.suite_env import apply_task1_env


STEPS = [
    ("第1题 RPC 正解", "q1_project.py"),
    ("第2题 0高程面正射", "q2_ortho_zero.py"),
    ("第3题 水准高 DEM 正射", "q3_ortho_dem.py"),
    ("第4题 椭球高 DEM 正射", "q4_ortho_ellip.py"),
    ("第5题 平行投影加速", "q5_parallel.py"),
    ("与参考结果对比", "compare.py"),
    ("跨视角配准检核", "cross_view.py"),
]


def _link_results() -> None:
    """将 task1 默认输出 ../results 同步到用户配置的 suite task1 目录。"""
    dst_root = task_output_dir("task1")
    src = TASK1_CODE.parent / "results"
    if src.is_dir():
        dst_root.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            dst = dst_root / item.name
            if item.is_dir():
                if dst.exists():
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(item, dst)
            else:
                shutil.copy2(item, dst)


def run_task1_all(
    selected: list[str] | None = None,
    *,
    image: str = "",
    dom: str = "",
    dem: str = "",
    dom_spec: str = "",
    ground_points: str = "",
) -> str:
    """运行 Task1 全部或选定步骤。selected 为脚本文件名列表。"""
    ensure_output_dirs()
    apply_task1_env(
        image=image,
        dom=dom,
        dem=dem,
        dom_spec=dom_spec,
        ground_points=ground_points,
        ref_dom=dom,
        output_dir=str(task_output_dir("task1")),
    )
    if not TASK1_CODE.is_dir():
        raise FileNotFoundError(f"未找到 task1_code: {TASK1_CODE}")

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    task1_path = str(TASK1_CODE.resolve())
    if task1_path not in sys.path:
        sys.path.insert(0, task1_path)

    steps = STEPS
    if selected:
        steps = [s for s in STEPS if s[1] in selected]

    for title, script in steps:
        print("\n" + "=" * 60)
        print(f">>> Task1 {title} ({script})")
        print("=" * 60)
        path = TASK1_CODE / script
        if not path.is_file():
            raise FileNotFoundError(path)
        # 与 cd task1_code && python q1_project.py 等价：保证 rpc/dem 等本地模块可导入
        runpy.run_path(str(path), run_name="__main__")

    _link_results()
    out = task_output_dir("task1")
    return f"Task1 完成，输出: {out}"
