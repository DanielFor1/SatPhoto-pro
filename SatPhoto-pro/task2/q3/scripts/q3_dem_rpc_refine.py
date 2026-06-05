# -*- coding: utf-8 -*-
"""
Task2 第3题：DEM 双线性内插高程 + RPC 精化 + 四角点检核

流程：
  1. 读取第2题加密像控点（gcps_matched.csv）
  2. 对每点 (lon, lat) 在 DEM 上双线性内插高程，得到完备像控点
  3. 以第1题精化 RPC 为初值，用第1题平差算法再次精化
  4. 用四角点.csv 评估；对比「有/无 DEM 高程」时四角点 RMSE 差异
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA = ROOT / "实习数据" / "task2"
Q2_GCPS = ROOT / "task2" / "q2" / "results" / "gcps_matched.csv"
OUT_DIR = Path(__file__).resolve().parent.parent / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "task2"))
import suite_paths as t2sp

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rpc_utils import load_rpb, refine_rpc_affine, rmse_vec, rpc_project, write_rpb


def find_dem_path() -> Path:
    return t2sp.dem_tif()


def load_dem() -> tuple[np.ndarray, tuple[float, ...], float | None]:
    ds = gdal.Open(str(find_dem_path()))
    if ds is None:
        raise FileNotFoundError("未找到 DEM")
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    return arr, ds.GetGeoTransform(), nodata


def dem_bilinear(
    lon: np.ndarray | float,
    lat: np.ndarray | float,
    dem: np.ndarray,
    gt: tuple[float, ...],
    nodata: float | None = None,
) -> np.ndarray | float:
    """地理坐标 -> DEM 双线性内插高程（米）。"""
    lon_a = np.atleast_1d(np.asarray(lon, dtype=np.float64))
    lat_a = np.atleast_1d(np.asarray(lat, dtype=np.float64))

    col = (lon_a - gt[0]) / gt[1]
    row = (lat_a - gt[3]) / gt[5]
    h, w = dem.shape

    c0 = np.floor(col).astype(int)
    r0 = np.floor(row).astype(int)
    dc = col - c0
    dr = row - r0

    out = np.full(lon_a.shape, np.nan, dtype=np.float64)
    valid = (c0 >= 0) & (r0 >= 0) & (c0 + 1 < w) & (r0 + 1 < h)
    if not np.any(valid):
        return out[0] if out.size == 1 else out

    c0v, r0v = c0[valid], r0[valid]
    dcv, drv = dc[valid], dr[valid]
    z00 = dem[r0v, c0v]
    z01 = dem[r0v, c0v + 1]
    z10 = dem[r0v + 1, c0v]
    z11 = dem[r0v + 1, c0v + 1]
    z = (
        (1 - dcv) * (1 - drv) * z00
        + dcv * (1 - drv) * z01
        + (1 - dcv) * drv * z10
        + dcv * drv * z11
    )
    if nodata is not None:
        for arr in (z00, z01, z10, z11):
            z = np.where(arr == nodata, np.nan, z)
    out[valid] = z
    return float(out[0]) if out.size == 1 else out


def read_gcps_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_gcps_csv(path: Path, rows: list[dict]) -> None:
    fields = ["id", "lon", "lat", "height", "line", "sample"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "id": r["id"],
                    "lon": f"{float(r['lon']):.10f}",
                    "lat": f"{float(r['lat']):.10f}",
                    "height": f"{float(r['height']):.4f}",
                    "line": f"{float(r['line']):.3f}",
                    "sample": f"{float(r['sample']):.3f}",
                }
            )


def apply_affine_residual(
    rpc: dict,
    aff: np.ndarray,
    lon: np.ndarray,
    lat: np.ndarray,
    h: np.ndarray,
    line_obs: np.ndarray,
    samp_obs: np.ndarray,
) -> tuple[float, np.ndarray, np.ndarray]:
    line_p, samp_p, p, l = rpc_project(rpc, lon, lat, h)
    corr_line = aff[0] + aff[1] * p + aff[2] * l
    corr_samp = aff[3] + aff[4] * p + aff[5] * l
    v_line = line_obs - line_p - corr_line
    v_samp = samp_obs - samp_p - corr_samp
    return rmse_vec(np.r_[v_line, v_samp]), v_line, v_samp


def evaluate_corners(
    rpc: dict,
    aff: np.ndarray,
    corners: list[dict],
    corner_heights: np.ndarray,
) -> dict:
    lon = np.array([float(r["lon"]) for r in corners])
    lat = np.array([float(r["lat"]) for r in corners])
    line = np.array([float(r["line"]) for r in corners])
    samp = np.array([float(r["sample"]) for r in corners])
    rmse, v_line, v_samp = apply_affine_residual(rpc, aff, lon, lat, corner_heights, line, samp)
    details = []
    for i, r in enumerate(corners):
        details.append(
            {
                "id": r["id"],
                "rmse_px": float(np.sqrt(v_line[i] ** 2 + v_samp[i] ** 2)),
                "d_line": float(v_line[i]),
                "d_sample": float(v_samp[i]),
            }
        )
    return {"rmse": rmse, "details": details}


def main() -> None:
    stem = t2sp.image_stem()
    q1_rpc = t2sp.q1_refined_rpb()
    init_rpb = t2sp.init_rpb()
    dem, gt, nodata = load_dem()
    q2_rows = read_gcps_csv(Q2_GCPS)
    corners = read_gcps_csv(t2sp.corners_csv())

    # --- 1. DEM 双线性内插，生成完备像控点 ---
    complete_rows: list[dict] = []
    for r in q2_rows:
        lon, lat = float(r["lon"]), float(r["lat"])
        h_dem = dem_bilinear(lon, lat, dem, gt, nodata)
        if np.isnan(h_dem):
            continue
        complete_rows.append(
            {
                "id": r["id"],
                "lon": lon,
                "lat": lat,
                "height": h_dem,
                "line": float(r["line"]),
                "sample": float(r["sample"]),
            }
        )
    out_gcps = OUT_DIR / "gcps_complete_dem.csv"
    write_gcps_csv(out_gcps, complete_rows)
    print(f"完备像控点（DEM 高程）: {len(complete_rows)} 个 -> {out_gcps}")

    lon = np.array([r["lon"] for r in complete_rows])
    lat = np.array([r["lat"] for r in complete_rows])
    h_dem = np.array([r["height"] for r in complete_rows])
    h_q2 = np.array([float(r["height"]) for r in q2_rows[: len(complete_rows)]])
    line = np.array([r["line"] for r in complete_rows])
    samp = np.array([r["sample"] for r in complete_rows])

    h_corner_dem = np.array(
        [dem_bilinear(float(r["lon"]), float(r["lat"]), dem, gt, nodata) for r in corners]
    )
    h_corner_ref = np.array([float(r["height"]) for r in corners])

    # --- 2. 用 DEM 高程精化 RPC（初值：第1题结果）---
    rpc_dem = load_rpb(q1_rpc)
    hist_dem, aff_dem = refine_rpc_affine(rpc_dem, lon, lat, h_dem, line, samp)
    print("\n[DEM 高程精化 RPC]")
    print(f"  训练点: {len(lon)}, 迭代 {len(hist_dem)} 次")
    print(f"  训练 RMSE(补偿后): {hist_dem[-1]['rmse_all']:.4f} px")
    corner_dem = evaluate_corners(rpc_dem, aff_dem, corners, h_corner_dem)
    print(f"  四角点 RMSE(补偿后, 角点用 DEM 高): {corner_dem['rmse']:.4f} px")

    out_rpb = OUT_DIR / f"{stem}_refined_q3.rpb"
    write_rpb(rpc_dem, init_rpb, out_rpb)
    print(f"  已写出: {out_rpb}")

    # --- 3. 对比：不使用 DEM（仍用第2题插值高程）---
    rpc_no_dem = load_rpb(q1_rpc)
    hist_no, aff_no = refine_rpc_affine(rpc_no_dem, lon, lat, h_q2, line, samp)
    corner_no = evaluate_corners(rpc_no_dem, aff_no, corners, h_corner_ref)
    print("\n[无 DEM：使用第2题插值高程]")
    print(f"  训练 RMSE(补偿后): {hist_no[-1]['rmse_all']:.4f} px")
    print(f"  四角点 RMSE(补偿后, 角点用参考椭球高): {corner_no['rmse']:.4f} px")

    # --- 4. 与四角点参考值逐点对比（DEM 方案）---
    print("\n--- 四角点逐点误差（DEM 方案）---")
    for d in corner_dem["details"]:
        print(
            f"  {d['id']}: RMSE={d['rmse_px']:.3f} px "
            f"(d_line={d['d_line']:+.3f}, d_sample={d['d_sample']:+.3f})"
        )

    summary = OUT_DIR / "q3_results.txt"
    lines_out = [
        "Task2 第3题 — DEM 内插高程 + RPC 精化",
        "================================",
        f"DEM: {find_dem_path().name}",
        f"输入像控点: {Q2_GCPS.name} ({len(complete_rows)} 点)",
        f"初值 RPC: {q1_rpc.name}",
        "",
        "【DEM 双线性内插 + RPC 精化】",
        f"  训练 RMSE(补偿后): {hist_dem[-1]['rmse_all']:.6f} px",
        f"  四角点 RMSE: {corner_dem['rmse']:.6f} px",
        f"  输出 RPC: {out_rpb.name}",
        f"  完备像控点: {out_gcps.name}",
        "",
        "【对比：无 DEM，使用第2题插值高程】",
        f"  训练 RMSE(补偿后): {hist_no[-1]['rmse_all']:.6f} px",
        f"  四角点 RMSE: {corner_no['rmse']:.6f} px",
        "",
        "四角点逐点 RMSE (DEM 方案, px):",
    ]
    for d in corner_dem["details"]:
        lines_out.append(f"  {d['id']}: {d['rmse_px']:.4f}")
    summary.write_text("\n".join(lines_out), encoding="utf-8")
    print(f"\n结果摘要: {summary}")


if __name__ == "__main__":
    main()
