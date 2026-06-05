# -*- coding: utf-8 -*-
"""
Task2 第2题：卫星影像与参考 DOM 特征匹配，加密像控点

流程：
  1. SIFT 特征提取 + BF 匹配 + Lowe 比值检验
  2. RANSAC 估计单应性矩阵 H（卫星像方 -> DOM 像方）
  3. 在卫星影像上取半格偏移规则网格（20×20 = 400 点）
  4. 用 H 映射到 DOM，读取 GeoTransform 得 lon/lat
  5. 高程由第一阶段稀疏控制点双线性插值（匹配阶段不单独估计高程）
"""

from __future__ import annotations

import csv
from pathlib import Path

import cv2
import numpy as np
from osgeo import gdal
from scipy.interpolate import griddata

ROOT = Path(__file__).resolve().parent.parent.parent.parent
import sys
sys.path.insert(0, str(ROOT / "task2"))
import suite_paths as t2sp

OUT_DIR = Path(__file__).resolve().parent.parent / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 与 gcps_ellipsoid.csv 一致的网格步长；半格偏移加密
GRID_STEP = 102.35
GRID_OFFSET = GRID_STEP / 2.0
GRID_N = 20  # 20×20 = 400 点


def find_data_paths() -> tuple[Path, Path]:
    return t2sp.image_tif(), t2sp.dom_tif()


def read_gray(path: Path) -> tuple[np.ndarray, gdal.Dataset]:
    ds = gdal.Open(str(path))
    if ds is None:
        raise FileNotFoundError(path)
    arr = ds.ReadAsArray()
    if arr.ndim == 3:
        arr = arr.transpose(1, 2, 0)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    else:
        gray = arr
    return gray, ds


def read_bgr(path: Path) -> np.ndarray:
    """读取彩色影像（OpenCV BGR 格式，仅用于可视化）。"""
    ds = gdal.Open(str(path))
    if ds is None:
        raise FileNotFoundError(path)
    arr = ds.ReadAsArray()
    if arr.ndim == 2:
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    rgb = arr.transpose(1, 2, 0)
    if rgb.shape[2] > 3:
        rgb = rgb[:, :, :3]
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def match_with_sift_ransac(
    sat_gray: np.ndarray,
    dom_gray: np.ndarray,
    ratio_thresh: float = 0.75,
    ransac_thresh: float = 3.0,
    n_features: int = 8000,
) -> tuple[np.ndarray, list[cv2.KeyPoint], list[cv2.KeyPoint], list[cv2.DMatch], np.ndarray]:
    """SIFT 匹配 + Lowe 检验 + RANSAC，返回 H（sat px -> dom px）及内点。"""
    sift = cv2.SIFT_create(
        nfeatures=n_features,
        contrastThreshold=0.03,
        edgeThreshold=10,
    )
    kp_sat, des_sat = sift.detectAndCompute(sat_gray, None)
    kp_dom, des_dom = sift.detectAndCompute(dom_gray, None)
    if des_sat is None or des_dom is None or len(kp_sat) < 4 or len(kp_dom) < 4:
        raise RuntimeError("特征点不足，请检查影像或调整 SIFT 参数")

    bf = cv2.BFMatcher(cv2.NORM_L2)
    knn = bf.knnMatch(des_sat, des_dom, k=2)
    good = [m for m, n in knn if m.distance < ratio_thresh * n.distance]
    if len(good) < 4:
        raise RuntimeError(f"有效匹配过少: {len(good)}")

    pts_sat = np.float32([kp_sat[m.queryIdx].pt for m in good])
    pts_dom = np.float32([kp_dom[m.trainIdx].pt for m in good])
    H, mask = cv2.findHomography(pts_sat, pts_dom, cv2.RANSAC, ransac_thresh)
    if H is None:
        raise RuntimeError("RANSAC 未能估计单应性矩阵")

    inlier_mask = mask.ravel().astype(bool)
    inlier_matches = [m for m, ok in zip(good, inlier_mask) if ok]
    return H, kp_sat, kp_dom, inlier_matches, inlier_mask


def load_sparse_height_field() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    csv_path = t2sp.gcp_ellipsoid_csv()
    lines, samps, heights = [], [], []
    with csv_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lines.append(float(row["line"]))
            samps.append(float(row["sample"]))
            heights.append(float(row["height"]))
    return map(np.array, (lines, samps, heights))


def densify_grid_gcps(
    H: np.ndarray,
    dom_ds: gdal.Dataset,
    lines0: np.ndarray,
    samps0: np.ndarray,
    heights0: np.ndarray,
) -> list[dict]:
    """在半格偏移规则网格上生成加密像控点。"""
    gt = dom_ds.GetGeoTransform()
    dom_w, dom_h = dom_ds.RasterXSize, dom_ds.RasterYSize
    gcps: list[dict] = []
    idx = 1

    for i in range(GRID_N):
        for j in range(GRID_N):
            line = GRID_OFFSET + i * GRID_STEP
            sample = GRID_OFFSET + j * GRID_STEP
            dom_xy = cv2.perspectiveTransform(
                np.array([[[sample, line]]], dtype=np.float32),
                H,
            )[0, 0]
            col, row = float(dom_xy[0]), float(dom_xy[1])
            if not (0 <= col < dom_w - 1 and 0 <= row < dom_h - 1):
                continue

            lon = gt[0] + col * gt[1] + row * gt[2]
            lat = gt[3] + col * gt[4] + row * gt[5]
            height = float(
                griddata((lines0, samps0), heights0, (line, sample), method="linear")
            )
            gcps.append(
                {
                    "id": f"M{idx:03d}",
                    "lon": lon,
                    "lat": lat,
                    "height": height,
                    "line": line,
                    "sample": sample,
                }
            )
            idx += 1
    return gcps


def write_gcps_csv(path: Path, gcps: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "lon", "lat", "height", "line", "sample"])
        w.writeheader()
        for g in gcps:
            w.writerow(
                {
                    "id": g["id"],
                    "lon": f"{g['lon']:.10f}",
                    "lat": f"{g['lat']:.10f}",
                    "height": f"{g['height']:.4f}",
                    "line": f"{g['line']:.3f}",
                    "sample": f"{g['sample']:.3f}",
                }
            )


def imwrite_unicode(path: Path, image: np.ndarray) -> None:
    """OpenCV 在 Windows 中文路径下 imwrite 会静默失败，改用 imencode 写入。"""
    suffix = path.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
        suffix = ".png"
    ok, buf = cv2.imencode(suffix, image)
    if not ok:
        raise RuntimeError(f"图像编码失败: {path.name}")
    path.write_bytes(buf.tobytes())


def save_match_figure(
    sat_bgr: np.ndarray,
    dom_bgr: np.ndarray,
    H: np.ndarray,
    kp_dom: list[cv2.KeyPoint],
    inlier_matches: list[cv2.DMatch],
    out_path: Path,
    max_draw: int = 100,
    display_max_width: int = 1800,
) -> None:
    """
    在 DOM 坐标系下可视化匹配：左 DOM 彩色，右为 H 配准后的卫星彩色影像。
    内点对应点在同一像素位置，连线为水平平行线（符合题目要求）。
    """
    dom_h, dom_w = dom_bgr.shape[:2]
    sat_warped = cv2.warpPerspective(sat_bgr, H, (dom_w, dom_h))

    draw = inlier_matches
    if len(draw) > max_draw:
        step = max(1, len(draw) // max_draw)
        draw = draw[::step]

    canvas = np.hstack([dom_bgr, sat_warped])
    for m in draw:
        x, y = kp_dom[m.trainIdx].pt
        px, py = int(round(x)), int(round(y))
        if not (0 <= px < dom_w and 0 <= py < dom_h):
            continue
        p_left = (px, py)
        p_right = (px + dom_w, py)
        cv2.line(canvas, p_left, p_right, (0, 255, 0), 1, cv2.LINE_AA)
        cv2.circle(canvas, p_left, 3, (0, 0, 255), -1, cv2.LINE_AA)
        cv2.circle(canvas, p_right, 3, (0, 0, 255), -1, cv2.LINE_AA)

    cv2.putText(
        canvas, "DOM (reference)", (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA,
    )
    cv2.putText(
        canvas, "Satellite (warped to DOM)", (dom_w + 20, 40),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA,
    )

    if canvas.shape[1] > display_max_width:
        scale = display_max_width / canvas.shape[1]
        canvas = cv2.resize(
            canvas,
            (display_max_width, int(canvas.shape[0] * scale)),
            interpolation=cv2.INTER_AREA,
        )

    imwrite_unicode(out_path, canvas)


def compare_with_reference(gcps: list[dict], ref_csv: Path) -> dict:
    """与检查点 gcps_check.csv 对比（按 line/sample 排序）。"""
    ours = sorted(gcps, key=lambda g: (g["line"], g["sample"]))
    ref_rows = list(csv.DictReader(ref_csv.open(encoding="utf-8")))
    ref = sorted(
        ref_rows,
        key=lambda r: (float(r["line"]), float(r["sample"])),
    )
    n = min(len(ours), len(ref))
    lon_err = []
    lat_err = []
    h_err = []
    for i in range(n):
        lon_err.append(abs(ours[i]["lon"] - float(ref[i]["lon"])) * 3600.0)
        lat_err.append(abs(ours[i]["lat"] - float(ref[i]["lat"])) * 3600.0)
        h_err.append(abs(ours[i]["height"] - float(ref[i]["height"])))
    return {
        "count_ours": len(ours),
        "count_ref": len(ref),
        "lon_mean_arcsec": float(np.mean(lon_err)),
        "lon_max_arcsec": float(np.max(lon_err)),
        "lat_mean_arcsec": float(np.mean(lat_err)),
        "lat_max_arcsec": float(np.max(lat_err)),
        "h_mean_m": float(np.mean(h_err)),
        "h_max_m": float(np.max(h_err)),
    }


def main() -> None:
    sat_path, dom_path = find_data_paths()
    print(f"卫星影像: {sat_path.name}")
    print(f"参考 DOM: {dom_path.name}")

    sat_gray, _ = read_gray(sat_path)
    dom_gray, dom_ds = read_gray(dom_path)
    sat_bgr = read_bgr(sat_path)
    dom_bgr = read_bgr(dom_path)
    print(f"尺寸: 卫星 {sat_gray.shape[1]}×{sat_gray.shape[0]}, DOM {dom_gray.shape[1]}×{dom_gray.shape[0]}")

    H, kp_sat, kp_dom, inlier_matches, inlier_mask = match_with_sift_ransac(
        sat_gray, dom_gray
    )
    print(f"SIFT 匹配: 内点 {len(inlier_matches)} / RANSAC 总候选 {inlier_mask.size}")

    lines0, samps0, heights0 = load_sparse_height_field()
    gcps = densify_grid_gcps(H, dom_ds, lines0, samps0, heights0)
    print(f"加密像控点: {len(gcps)} 个（{GRID_N}×{GRID_N} 半格偏移网格）")

    out_csv = OUT_DIR / "gcps_matched.csv"
    write_gcps_csv(out_csv, gcps)
    print(f"已写出: {out_csv}")

    vis_path = OUT_DIR / "match_sift_ransac.png"
    save_match_figure(sat_bgr, dom_bgr, H, kp_dom, inlier_matches, vis_path)
    print(f"匹配可视化: {vis_path}")

    ref_csv = t2sp.gcp_check_csv()
    if ref_csv.exists():
        stats = compare_with_reference(gcps, ref_csv)
        print("\n--- 与 gcps_check.csv 对比 ---")
        print(f"  点数: {stats['count_ours']} / {stats['count_ref']}")
        print(
            f"  经度误差: mean={stats['lon_mean_arcsec']:.4f}\", max={stats['lon_max_arcsec']:.4f}\""
        )
        print(
            f"  纬度误差: mean={stats['lat_mean_arcsec']:.4f}\", max={stats['lat_max_arcsec']:.4f}\""
        )
        print(f"  高程误差: mean={stats['h_mean_m']:.3f} m, max={stats['h_max_m']:.3f} m")

        summary = OUT_DIR / "q2_results.txt"
        summary.write_text(
            "\n".join(
                [
                    "Task2 第2题 — SIFT + RANSAC 加密像控点",
                    "================================",
                    f"算法: SIFT + Lowe(0.75) + RANSAC(3px)",
                    f"SIFT 内点: {len(inlier_matches)}",
                    f"输出像控点: {len(gcps)}",
                    f"输出 CSV: {out_csv.name}",
                    f"可视化: {vis_path.name}",
                    "",
                    "与 gcps_check.csv 对比:",
                    f"  lon mean/max (arcsec): {stats['lon_mean_arcsec']:.4f} / {stats['lon_max_arcsec']:.4f}",
                    f"  lat mean/max (arcsec): {stats['lat_mean_arcsec']:.4f} / {stats['lat_max_arcsec']:.4f}",
                    f"  height mean/max (m): {stats['h_mean_m']:.3f} / {stats['h_max_m']:.3f}",
                ]
            ),
            encoding="utf-8",
        )
        print(f"结果摘要: {summary}")


if __name__ == "__main__":
    main()
