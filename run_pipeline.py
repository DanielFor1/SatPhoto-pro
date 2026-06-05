# -*- coding: utf-8 -*-
"""SatPhoto-Pro 全流程命令行入口（测试用例赛道默认 011/007）。

把 Task2(校正RPC) → Task1(DOM)/Task3(核线) → Task4(视差) → Task5(DSM) 串成一条龙，
核心是把 Task2 校正后的 RPC 传播给下游，实现"不准确 RPC → 准确 DOM/DSM"。

用法：
    run_pipeline.bat                      # 默认 011/007 全流程
    run_pipeline.bat --stages rpc dom     # 只跑指定阶段
    run_pipeline.bat --force              # 即使已有产物也重算
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUITE = ROOT / "SatPhoto-pro"
for p in (SUITE, SUITE / "task5_source"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from photogrammetry_suite.pipeline import PipelineConfig, run_full_pipeline  # noqa: E402

TC = ROOT / "全流程测试用例"
TRUTH = TC / "参考真值数据" / "JAX_Tile_163_RGB_011_vs_JAX_Tile_163_RGB_007"
LEFT, RIGHT = "JAX_Tile_163_RGB_011", "JAX_Tile_163_RGB_007"


def default_config() -> PipelineConfig:
    return PipelineConfig(
        left_image=str(TC / f"{LEFT}.tif"),
        right_image=str(TC / f"{RIGHT}.tif"),
        left_gcp=str(TC / f"{LEFT}_gcps_ellipsoid.csv"),
        right_gcp=str(TC / f"{RIGHT}_gcps_ellipsoid.csv"),
        left_check=str(TC / f"{LEFT}_gcps_check.csv"),
        right_check=str(TC / f"{RIGHT}_gcps_check.csv"),
        base_dom=str(TC / "底图DOM" / "JAX_Tile_163_RGB_016_DOM.tif"),
        ref_dom_left=str(TC / "参考真值数据" / "DOM" / f"{LEFT}_DOM.tif"),
        ref_dom_right=str(TC / "参考真值数据" / "DOM" / f"{RIGHT}_DOM.tif"),
        ref_dsm=str(TRUTH / f"{LEFT}_vs_{RIGHT}_DSM.tif"),
        ref_dsp=str(TRUTH / f"{LEFT}_vs_{RIGHT}_DSP.tif"),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", nargs="+",
                    default=["rpc", "dom", "epipolar", "match", "dsm"],
                    choices=["rpc", "dom", "epipolar", "match", "dsm"])
    ap.add_argument("--task4-all", action="store_true", help="运行 Task4 全部 5 种匹配算法")
    ap.add_argument("--task5-stride", type=int, default=2)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cfg = default_config()
    cfg.stages = tuple(args.stages)
    cfg.task4_run_all = args.task4_all
    cfg.task5_stride = args.task5_stride
    cfg.force = args.force

    res = run_full_pipeline(cfg)
    return 0 if res.get("all_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
