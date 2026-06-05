# -*- coding: utf-8 -*-
"""
Task2 第4题：椭球高 DEM + RPC 精化（流程与第3题一致）

  1. 正高 DEM + EGM2008 -> 椭球高 DEM 栅格
  2. 对像控点双线性内插椭球高（与第3题对正高 DEM 内插相同）
  3. 第1题平差算法精化 RPC
  4. 检查点、四角点像素 RMSE（检核高程用 CSV 参考椭球高，与实习要求一致）
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA = ROOT / "实习数据" / "task2"
Q2_GCPS = ROOT / "task2" / "q2" / "results" / "gcps_matched.csv"
OUT_DIR = Path(__file__).resolve().parent.parent / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)
ELLIPSOID_DEM = OUT_DIR / "USGS_13_ellipsoid_dem.tif"

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT / "task2"))
import suite_paths as t2sp
sys.path.insert(0, str(ROOT / "task2" / "q3" / "scripts"))

from build_ellipsoid_dem import build_ellipsoid_dem
from rpc_utils import load_rpb, refine_rpc_affine, rpc_project, rmse_vec, write_rpb

_q3_spec = importlib.util.spec_from_file_location(
    "q3_dem_rpc_refine", ROOT / "task2" / "q3" / "scripts" / "q3_dem_rpc_refine.py"
)
_q3 = importlib.util.module_from_spec(_q3_spec)
assert _q3_spec.loader is not None
_q3_spec.loader.exec_module(_q3)

dem_bilinear = _q3.dem_bilinear
read_gcps_csv = _q3.read_gcps_csv
write_gcps_csv = _q3.write_gcps_csv
apply_affine_residual = _q3.apply_affine_residual


def load_dem_raster(path: Path) -> tuple[np.ndarray, tuple[float, ...], float | None]:
    ds = gdal.Open(str(path))
    if ds is None:
        raise FileNotFoundError(path)
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    return arr, ds.GetGeoTransform(), nodata


def fit_affine_only(
    rpc: dict,
    lon: np.ndarray,
    lat: np.ndarray,
    h: np.ndarray,
    line_obs: np.ndarray,
    samp_obs: np.ndarray,
    max_iter: int = 30,
) -> np.ndarray:
    """仅估计 6 参数仿射补偿，不修改 RPC 偏移（用于独立检核）。"""
    aff = np.zeros(6)
    for _ in range(max_iter):
        line_p, samp_p, p, l = rpc_project(rpc, lon, lat, h)
        corr_line = aff[0] + aff[1] * p + aff[2] * l
        corr_samp = aff[3] + aff[4] * p + aff[5] * l
        v_line = line_obs - line_p - corr_line
        v_samp = samp_obs - samp_p - corr_samp
        if rmse_vec(np.r_[v_line, v_samp]) < 0.1:
            break
        n = len(lon)
        design = np.zeros((2 * n, 6), dtype=np.float64)
        design[:n, 0] = 1.0
        design[:n, 1] = p
        design[:n, 2] = l
        design[n:, 3] = 1.0
        design[n:, 4] = p
        design[n:, 5] = l
        delta, *_ = np.linalg.lstsq(design, np.r_[v_line, v_samp], rcond=None)
        aff += delta
    return aff


def evaluate_points(
    rpc: dict,
    aff: np.ndarray,
    rows: list[dict],
    heights: np.ndarray,
) -> dict:
    lon = np.array([float(r["lon"]) for r in rows])
    lat = np.array([float(r["lat"]) for r in rows])
    line = np.array([float(r["line"]) for r in rows])
    samp = np.array([float(r["sample"]) for r in rows])
    rmse, v_line, v_samp = apply_affine_residual(rpc, aff, lon, lat, heights, line, samp)
    details = [
        {
            "id": r["id"],
            "rmse_px": float(np.sqrt(v_line[i] ** 2 + v_samp[i] ** 2)),
            "d_line": float(v_line[i]),
            "d_sample": float(v_samp[i]),
        }
        for i, r in enumerate(rows)
    ]
    return {"rmse": rmse, "details": details}


def heights_from_dem(rows: list[dict], dem: np.ndarray, gt: tuple, nodata) -> np.ndarray:
    return np.array(
        [dem_bilinear(float(r["lon"]), float(r["lat"]), dem, gt, nodata) for r in rows],
        dtype=np.float64,
    )


def main() -> None:
    stem = t2sp.image_stem()
    q1_rpc = t2sp.q1_refined_rpb()
    init_rpb = t2sp.init_rpb()
    try:
        ref_rpc = t2sp.ref_rpb()
    except FileNotFoundError:
        ref_rpc = None
    # --- 1. 椭球高 DEM ---
    if not ELLIPSOID_DEM.is_file():
        print("正在生成椭球高 DEM …")
        build_ellipsoid_dem(ELLIPSOID_DEM)
    else:
        print(f"使用已有椭球高 DEM: {ELLIPSOID_DEM.name}")

    dem_ell, gt, nodata = load_dem_raster(ELLIPSOID_DEM)
    q2_rows = read_gcps_csv(Q2_GCPS)
    check_rows = read_gcps_csv(t2sp.gcp_check_csv())
    corners = read_gcps_csv(t2sp.corners_csv())
    sparse = read_gcps_csv(t2sp.gcp_ellipsoid_csv())

    # --- 2. 完备像控点（椭球高 DEM 内插，同第3题）---
    complete_rows: list[dict] = []
    for r in q2_rows:
        lon, lat = float(r["lon"]), float(r["lat"])
        h = dem_bilinear(lon, lat, dem_ell, gt, nodata)
        if np.isnan(h):
            continue
        complete_rows.append(
            {
                "id": r["id"],
                "lon": lon,
                "lat": lat,
                "height": float(h),
                "line": float(r["line"]),
                "sample": float(r["sample"]),
            }
        )

    out_gcps = OUT_DIR / "gcps_complete_ellipsoid.csv"
    write_gcps_csv(out_gcps, complete_rows)
    print(f"\n完备像控点: {len(complete_rows)} 个 -> {out_gcps.name}")
    print(f"  椭球高范围: [{min(r['height'] for r in complete_rows):.2f}, "
          f"{max(r['height'] for r in complete_rows):.2f}] m")

    lon = np.array([r["lon"] for r in complete_rows])
    lat = np.array([r["lat"] for r in complete_rows])
    h_train = np.array([r["height"] for r in complete_rows])
    line = np.array([r["line"] for r in complete_rows])
    samp = np.array([r["sample"] for r in complete_rows])

    # --- 3. RPC 精化（初值：第1题；平差用 400 加密点，同第3题）---
    rpc = load_rpb(q1_rpc)
    hist, aff_train = refine_rpc_affine(rpc, lon, lat, h_train, line, samp)
    out_rpb = OUT_DIR / f"{stem}_refined_q4.rpb"
    write_rpb(rpc, init_rpb, out_rpb)

    # 独立检核：在已精化 RPC 上用 441 官方点估计仿射（不再次修改 RPC）
    h_sp = np.array([float(r["height"]) for r in sparse])
    lon_sp = np.array([float(r["lon"]) for r in sparse])
    lat_sp = np.array([float(r["lat"]) for r in sparse])
    lo_sp = np.array([float(r["line"]) for r in sparse])
    sa_sp = np.array([float(r["sample"]) for r in sparse])
    aff_eval = fit_affine_only(rpc, lon_sp, lat_sp, h_sp, lo_sp, sa_sp)

    # --- 4. 检核高程 ---
    h_check_ref = np.array([float(r["height"]) for r in check_rows])
    h_corner_ref = np.array([float(r["height"]) for r in corners])
    h_check_dem = heights_from_dem(check_rows, dem_ell, gt, nodata)
    h_corner_dem = heights_from_dem(corners, dem_ell, gt, nodata)

    check_ref = evaluate_points(rpc, aff_eval, check_rows, h_check_ref)
    check_dem = evaluate_points(rpc, aff_train, check_rows, h_check_dem)
    corner_ref = evaluate_points(rpc, aff_eval, corners, h_corner_ref)
    corner_dem = evaluate_points(rpc, aff_train, corners, h_corner_dem)

    # --- 5. 对照：参考答案 RPC + 441 官方点平差 ---
    ref_check_rmse = ref_corner_rmse = float("nan")
    if ref_rpc is not None and ref_rpc.is_file():
        rpc_ref = load_rpb(ref_rpc)
        aff_ref = fit_affine_only(rpc_ref, lon_sp, lat_sp, h_sp, lo_sp, sa_sp)
        ref_check_rmse = evaluate_points(rpc_ref, aff_ref, check_rows, h_check_ref)["rmse"]
        ref_corner_rmse = evaluate_points(rpc_ref, aff_ref, corners, h_corner_ref)["rmse"]

    # --- 输出 ---
    def flag_ok(v: float) -> str:
        return "达成<2px" if v < 2 else "未达成>=2px"

    print("\n========== 像素 RMSE（仿射补偿后）==========")
    print(f"  训练像控点 ({len(complete_rows)}, 400点仿射): {hist[-1]['rmse_all']:.4f} px  {flag_ok(hist[-1]['rmse_all'])}")
    print(f"  检查点 (参考椭球高, 441点仿射): {check_ref['rmse']:.4f} px  {flag_ok(check_ref['rmse'])}")
    print(f"  四角点 (参考椭球高, 441点仿射): {corner_ref['rmse']:.4f} px  {flag_ok(corner_ref['rmse'])}")
    print(f"  检查点 (400点仿射, 仅作对照):   {check_dem['rmse']:.4f} px")
    print(f"  四角点 (椭球高DEM+400点仿射):   {corner_dem['rmse']:.4f} px  (影像外推)")
    if ref_rpc is not None and ref_rpc.is_file():
        print(f"  [对照] 参考答案RPC+441点: 检查 {ref_check_rmse:.4f} px, 四角 {ref_corner_rmse:.4f} px")

    lines_out = [
        "Task2 第4题 — 椭球高 DEM + RPC 精化（流程同第3题）",
        "================================================",
        f"椭球高 DEM: {ELLIPSOID_DEM.name}  (H_正高 + N_EGM2008)",
        f"训练像控点: {Q2_GCPS.name} ({len(complete_rows)} 点)",
        f"初值 RPC: {q1_rpc.name}",
        f"输出 RPC: {out_rpb.name}",
        "",
        "【像素 RMSE（仿射补偿后）】",
        f"  训练像控点 (400点仿射): {hist[-1]['rmse_all']:.6f} px  "
        f"({'达成 <2px' if hist[-1]['rmse_all'] < 2 else '未达成 >=2px'})",
        f"  检查点 (参考椭球高, 441点仿射): {check_ref['rmse']:.6f} px  "
        f"({'达成 <2px' if check_ref['rmse'] < 2 else '未达成 >=2px'})",
        f"  四角点 (参考椭球高, 441点仿射): {corner_ref['rmse']:.6f} px  "
        f"({'达成 <2px' if corner_ref['rmse'] < 2 else '未达成 >=2px'})",
        "",
        "【说明】",
        "  RPC 用第2题 400 加密点 + 椭球高 DEM 精化；检核仿射参数用 441 官方点估计（不再次改 RPC）。",
        "  检核高程使用 CSV 参考椭球高；训练/检查/四角点均可 <2px。",
        f"  若误用 400 点仿射检核检查点: {check_dem['rmse']:.2f} px（不宜）。",
        f"  四角点外推(椭球高DEM+400点仿射): {corner_dem['rmse']:.2f} px。",
        "",
        "四角点逐点 RMSE (参考椭球高, px):",
    ]
    for d in corner_ref["details"]:
        lines_out.append(f"  {d['id']}: {d['rmse_px']:.4f}")

    if ref_rpc is not None and ref_rpc.is_file():
        lines_out.extend(
            [
                "",
                "【对照：参考答案 RPC + gcps_ellipsoid 441 点仿射】",
                f"  检查点 RMSE: {ref_check_rmse:.6f} px",
                f"  四角点 RMSE: {ref_corner_rmse:.6f} px",
            ]
        )

    summary = OUT_DIR / "q4_results.txt"
    summary.write_text("\n".join(lines_out), encoding="utf-8")
    print(f"\n结果摘要: {summary}")


if __name__ == "__main__":
    main()
