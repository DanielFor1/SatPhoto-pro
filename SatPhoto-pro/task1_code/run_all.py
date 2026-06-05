# -*- coding: utf-8 -*-
"""一键依次运行任务一全部 5 小题，最后与参考结果对比。"""
import runpy
import os

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
STEPS = [
    ("第1题 RPC 正解", "q1_project.py"),
    ("第2题 0高程面正射 (001+005)", "q2_ortho_zero.py"),
    ("第3题 水准高 DEM 正射 (001+005)", "q3_ortho_dem.py"),
    ("第4题 椭球高 DEM 正射 (001+005)", "q4_ortho_ellip.py"),
    ("第5题 平行投影加速", "q5_parallel.py"),
    ("与参考结果定量对比 (001+005)", "compare.py"),
    ("001×005 跨视角配准检核", "cross_view.py"),
]

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    for title, script in STEPS:
        print("\n" + "=" * 70)
        print(f">>> {title}  ({script})")
        print("=" * 70)
        runpy.run_path(os.path.join(here, script), run_name="__main__")
    print("\n全部完成，结果见 ../results/")
