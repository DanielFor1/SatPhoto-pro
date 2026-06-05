# -*- coding: utf-8 -*-
"""
Task2 第5题：后验粗差剔除 — 去除建筑物上的匹配点并重新精化 RPC

思路（指导书）：
  DEM 仅含地表高，建筑物顶上的匹配点若仍用地表高参与平差，投影差会使残差显著偏大。
  第一次平差后检查各点像方残差 v_i = sqrt(v_r^2 + v_c^2)，
  若 v_i > k * RMSE（默认 k=2），判定为粗差并剔除，再用干净控制点第二次平差。

实现要点：
  - 第一次平差用 fit_affine_only（最小二乘仿射，不修改 RPC），便于直接读取 v_r, v_c
  - 第二次平差用 refine_rpc_affine（与第4题一致，将补偿并入 RPC 偏移）
  - 迭代剔除直至无新增粗差点
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA = ROOT / "实习数据" / "task2"
Q4_GCPS = ROOT / "task2" / "q4" / "results" / "gcps_complete_ellipsoid.csv"
OUT_DIR = Path(__file__).resolve().parent.parent / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "task2"))
import suite_paths as t2sp
sys.path.insert(0, str(ROOT / "task2" / "q3" / "scripts"))
from rpc_utils import load_rpb, refine_rpc_affine, write_rpb

_q4_spec = importlib.util.spec_from_file_location(
    "q4_egm_rpc_refine", ROOT / "task2" / "q4" / "scripts" / "q4_egm_rpc_refine.py"
)
_q4 = importlib.util.module_from_spec(_q4_spec)
assert _q4_spec.loader is not None
_q4_spec.loader.exec_module(_q4)

_q3_spec = importlib.util.spec_from_file_location(
    "q3_dem_rpc_refine", ROOT / "task2" / "q3" / "scripts" / "q3_dem_rpc_refine.py"
)
_q3 = importlib.util.module_from_spec(_q3_spec)
assert _q3_spec.loader is not None
_q3_spec.loader.exec_module(_q3)

read_gcps_csv = _q4.read_gcps_csv
write_gcps_csv = _q4.write_gcps_csv
apply_affine_residual = _q4.apply_affine_residual
fit_affine_only = _q4.fit_affine_only
evaluate_points = _q4.evaluate_points
dem_bilinear = _q3.dem_bilinear

THRESHOLD_FACTOR = 2.0


def rows_to_arrays(rows: list[dict]) -> tuple[np.ndarray, ...]:
    lon = np.array([float(r["lon"]) for r in rows])
    lat = np.array([float(r["lat"]) for r in rows])
    h = np.array([float(r["height"]) for r in rows])
    line = np.array([float(r["line"]) for r in rows])
    samp = np.array([float(r["sample"]) for r in rows])
    return lon, lat, h, line, samp


def first_pass_affine_adjustment(
    rpc: dict,
    rows: list[dict],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, np.ndarray]:
    """第一次平差：6 参数仿射最小二乘（RPC 不变）。"""
    lon, lat, h, line, samp = rows_to_arrays(rows)
    aff = fit_affine_only(rpc, lon, lat, h, line, samp)
    rmse, v_line, v_samp = apply_affine_residual(rpc, aff, lon, lat, h, line, samp)
    v_i = np.sqrt(v_line**2 + v_samp**2)
    return v_i, v_line, v_samp, rmse, aff


def outlier_rejection_single_pass(
    rpc: dict,
    rows: list[dict],
    v_i: np.ndarray,
    v_line: np.ndarray,
    v_samp: np.ndarray,
    rmse: float,
    threshold_factor: float = THRESHOLD_FACTOR,
) -> tuple[list[dict], list[dict], dict]:
    """
    基于第一次平差残差的后验粗差剔除（单轮）。
    阈值固定为 threshold_factor × 第一次平差的全局 RMSE，避免迭代剔除雪崩。
    """
    thresh = threshold_factor * rmse
    bad = v_i > thresh
    kept = [r for i, r in enumerate(rows) if not bad[i]]
    removed = [
        {
            **rows[i],
            "v_px": float(v_i[i]),
            "v_line": float(v_line[i]),
            "v_sample": float(v_samp[i]),
        }
        for i in range(len(rows))
        if bad[i]
    ]
    stats = {
        "n_input": len(rows),
        "n_kept": len(kept),
        "n_removed": len(removed),
        "rmse_px": rmse,
        "threshold_px": thresh,
        "max_v_px": float(np.max(v_i)),
        "median_v_px": float(np.median(v_i)),
    }
    return kept, removed, stats


def main() -> None:
    stem = t2sp.image_stem()
    q1_rpc = t2sp.q1_refined_rpb()
    init_rpb = t2sp.init_rpb()
    if not Q4_GCPS.is_file():
        raise FileNotFoundError(
            f"未找到 {Q4_GCPS.name}，请先运行 task2/q4/scripts/q4_egm_rpc_refine.py"
        )

    all_rows = read_gcps_csv(Q4_GCPS)
    check_rows = read_gcps_csv(t2sp.gcp_check_csv())
    corners = read_gcps_csv(t2sp.corners_csv())
    sparse = read_gcps_csv(t2sp.gcp_ellipsoid_csv())

    rpc_q1 = load_rpb(q1_rpc)

    # --- 第一次平差 + 单轮后验粗差剔除（RPC 不变）---
    v_all, v_line_all, v_samp_all, rmse_all, _ = first_pass_affine_adjustment(rpc_q1, all_rows)
    kept_rows, removed_rows, reject_stats = outlier_rejection_single_pass(
        rpc_q1, all_rows, v_all, v_line_all, v_samp_all, rmse_all, THRESHOLD_FACTOR
    )
    lon_k, lat_k, h_k, line_k, samp_k = rows_to_arrays(kept_rows)

    # --- 第二次平差：干净控制点，精化 RPC ---
    rpc_refined = load_rpb(q1_rpc)
    hist2, aff_train = refine_rpc_affine(rpc_refined, lon_k, lat_k, h_k, line_k, samp_k)

    # --- 对照：未剔除时直接精化 ---
    rpc_before = load_rpb(q1_rpc)
    hist_before, aff_before = refine_rpc_affine(
        rpc_before, *rows_to_arrays(all_rows)
    )

    out_gcps_clean = OUT_DIR / "gcps_clean_ellipsoid.csv"
    out_gcps_removed = OUT_DIR / "gcps_removed_building.csv"
    write_gcps_csv(out_gcps_clean, kept_rows)
    with out_gcps_removed.open("w", newline="", encoding="utf-8") as f:
        fields = ["id", "lon", "lat", "height", "line", "sample", "v_px", "v_line", "v_sample"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in removed_rows:
            w.writerow({k: r[k] for k in fields})

    out_rpb = OUT_DIR / f"{stem}_refined_q5.rpb"
    write_rpb(rpc_refined, init_rpb, out_rpb)

    # --- 检核高程 ---
    ell_dem = ROOT / "task2" / "q4" / "results" / "USGS_13_ellipsoid_dem.tif"
    ds = gdal.Open(str(ell_dem))
    dem_arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
    gt = ds.GetGeoTransform()
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    h_corner_dem = np.array(
        [dem_bilinear(float(r["lon"]), float(r["lat"]), dem_arr, gt, nodata) for r in corners]
    )
    h_check_ref = np.array([float(r["height"]) for r in check_rows])
    h_corner_ref = np.array([float(r["height"]) for r in corners])

    h_sp = np.array([float(r["height"]) for r in sparse])
    lon_sp = np.array([float(r["lon"]) for r in sparse])
    lat_sp = np.array([float(r["lat"]) for r in sparse])
    lo_sp = np.array([float(r["line"]) for r in sparse])
    sa_sp = np.array([float(r["sample"]) for r in sparse])

    aff_eval = fit_affine_only(rpc_refined, lon_sp, lat_sp, h_sp, lo_sp, sa_sp)
    check_ref = evaluate_points(rpc_refined, aff_eval, check_rows, h_check_ref)
    corner_ref = evaluate_points(rpc_refined, aff_eval, corners, h_corner_ref)
    corner_train = evaluate_points(rpc_refined, aff_train, corners, h_corner_dem)
    corner_before = evaluate_points(rpc_before, aff_before, corners, h_corner_dem)
    check_train = evaluate_points(rpc_refined, aff_train, check_rows, h_check_ref)

    def flag(v: float, limit: float = 1.0) -> str:
        if v < limit:
            return f"达成 <{limit:g}px"
        if v < 2.0:
            return "达成 <2px"
        return "未达成"

    print("\n========== Task2 第5题：后验粗差剔除 ==========")
    print(f"输入像控点: {len(all_rows)} (椭球高, 来自第4题)")
    print(f"第一次平差 RMSE: {rmse_all:.4f} px  (阈值 {THRESHOLD_FACTOR}×RMSE = {THRESHOLD_FACTOR * rmse_all:.4f} px)")
    print(f"剔除粗差点: {len(removed_rows)} 个 -> 保留 {len(kept_rows)} 个")
    print(f"第二次平差 RMSE: {hist2[-1]['rmse_all']:.4f} px")
    print(f"\n检查点 RMSE (441点仿射): {check_ref['rmse']:.4f} px  {flag(check_ref['rmse'])}")
    print(f"四角点 RMSE (441点仿射): {corner_ref['rmse']:.4f} px  {flag(corner_ref['rmse'])}")
    print(f"\n外推检核 (训练点仿射 + 参考/ DEM 高程):")
    print(f"  四角点 剔除前: {corner_before['rmse']:.4f} px")
    print(f"  四角点 剔除后: {corner_train['rmse']:.4f} px")
    print(f"  检查点 剔除后: {check_train['rmse']:.4f} px")

    lines_out = [
        "Task2 第5题 — 后验粗差剔除（建筑物匹配点）",
        "==========================================",
        "方法: 第一次仿射平差 -> v_i=sqrt(v_r^2+v_c^2) -> v_i>2×RMSE 剔除 -> 第二次 RPC 精化",
        f"输入: {Q4_GCPS.name} ({len(all_rows)} 点, 椭球高)",
        f"初值 RPC: {q1_rpc.name}",
        f"阈值: v_i > {THRESHOLD_FACTOR} × RMSE（单轮，固定第一次平差 RMSE）",
        "",
        "【粗差剔除统计】",
        f"  第一次平差 RMSE(仿射补偿后): {rmse_all:.6f} px",
        f"  残差阈值: {THRESHOLD_FACTOR * rmse_all:.6f} px",
        f"  剔除点数: {len(removed_rows)}",
        f"  保留点数: {len(kept_rows)}",
        f"  第二次平差 RMSE(补偿后): {hist2[-1]['rmse_all']:.6f} px",
        f"  未剔除对照训练 RMSE: {hist_before[-1]['rmse_all']:.6f} px",
        "",
        "【剔除明细】",
        f"  输入 {reject_stats['n_input']} 点, 剔除 {reject_stats['n_removed']} 点, 保留 {reject_stats['n_kept']} 点",
        f"  中位残差={reject_stats['median_v_px']:.4f}px, 最大残差={reject_stats['max_v_px']:.4f}px",
    ]

    lines_out.extend(
        [
            "",
            "【像素 RMSE（仿射补偿后）】",
            f"  训练像控点 (剔除后 {len(kept_rows)}点): {hist2[-1]['rmse_all']:.6f} px",
            f"  检查点 (441点仿射, 参考椭球高): {check_ref['rmse']:.6f} px  ({flag(check_ref['rmse'])})",
            f"  四角点 (441点仿射, 参考椭球高): {corner_ref['rmse']:.6f} px  ({flag(corner_ref['rmse'])})",
            "",
            "【外推检核：训练点仿射 + 椭球高】",
            f"  检查点 (剔除后 {len(kept_rows)}点仿射): {check_train['rmse']:.6f} px",
            f"  四角点 剔除前 ({len(all_rows)}点): {corner_before['rmse']:.6f} px",
            f"  四角点 剔除后 ({len(kept_rows)}点): {corner_train['rmse']:.6f} px",
            "",
            f"输出 RPC: {out_rpb.name}",
            f"干净像控点: {out_gcps_clean.name}",
            f"剔除点列表: {out_gcps_removed.name}",
            "",
            "【说明】",
            "  第一次平差在 Q1 RPC 上做 6 参数仿射最小二乘（不修改 RPC），",
            "  此时建筑物点因 DEM 投影差残差偏大；剔除后再做 refine_rpc_affine。",
            "  441 点仿射检核与第4题一致；外推检核反映加密点仿射在检查/四角上的泛化。",
            "  指导书允许外推四角 RMSE 暂难达 1px，重点在于说明剔除过程与机理。",
        ]
    )

    if removed_rows:
        lines_out.append("")
        lines_out.append("剔除点 (按残差 v_i 降序):")
        for r in sorted(removed_rows, key=lambda x: x["v_px"], reverse=True):
            lines_out.append(
                f"  {r['id']}: v={r['v_px']:.2f}px "
                f"(v_line={r['v_line']:+.2f}, v_sample={r['v_sample']:+.2f})"
            )

    lines_out.extend(["", "四角点逐点 RMSE (441点仿射, px):"])
    for d in corner_ref["details"]:
        lines_out.append(f"  {d['id']}: {d['rmse_px']:.4f}")

    summary = OUT_DIR / "q5_results.txt"
    summary.write_text("\n".join(lines_out), encoding="utf-8")
    print(f"\n结果摘要: {summary}")


if __name__ == "__main__":
    main()
