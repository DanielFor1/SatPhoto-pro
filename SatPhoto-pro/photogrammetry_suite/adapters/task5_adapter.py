# -*- coding: utf-8 -*-
"""
Task5 适配器 — 视差转点云 + DSM 生成（组员新版 task5_source）。

与组员 CLI `run-all` 对齐：
  1. 同名点前方交会 → tie_points/intersected_points.csv
  2. 视差 → 点云
  3. IDW + Pure TIN masked + TIN+IDW hybrid DSM + metrics
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

from photogrammetry_suite.config import TASK5_ROOT, Task5CloudConfig, ensure_output_dirs, task_output_dir

if str(TASK5_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK5_ROOT))


def gpu_available() -> tuple[bool, str]:
    """检测 CuPy/CUDA 是否可用于 Task5 GPU 模式。"""
    try:
        import cupy as cp  # noqa: F401
        n = cp.cuda.runtime.getDeviceCount()
        if n < 1:
            return False, "未检测到 CUDA 设备"
        name = cp.cuda.runtime.getDeviceProperties(0)["name"].decode("utf-8", errors="replace")
        return True, name
    except ImportError:
        return False, "未安装 cupy（可执行 pip install -r gpu_requirements.txt）"
    except Exception as exc:
        return False, str(exc)


def _ensure_task5_deps() -> None:
    """Task5 必需依赖（rasterio 等）。"""
    missing: list[str] = []
    for mod, pkg in (("rasterio", "rasterio"), ("pandas", "pandas"), ("scipy", "scipy")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        pkgs = " ".join(dict.fromkeys(missing))
        raise RuntimeError(
            f"Task5 缺少依赖: {', '.join(missing)}\n"
            f"请在 Anaconda 终端执行: pip install {pkgs}\n"
            f"或: pip install -r photogrammetry_suite/requirements.txt"
        )


def _ensure_compute_backend(cfg: Task5CloudConfig) -> str:
    method = cfg.resolved_intersection_method()
    if method == "gpu":
        ok, msg = gpu_available()
        if not ok:
            raise RuntimeError(
                f"GPU 模式不可用: {msg}\n"
                "请在软件中选择 CPU 模式，或安装 CUDA 与 cupy 后重试。"
            )
        print(f"  GPU 设备: {msg}")
    return method


def _out_base(cfg: Task5CloudConfig) -> Path:
    return Path(cfg.output_dir or task_output_dir("task5"))


def _spec_from_raster(path: Path) -> dict:
    """从 GeoTIFF 参考 DSM 推导格网规格（与 dsm_grid_spec.csv 字段一致）。"""
    import rasterio

    with rasterio.open(path) as src:
        transform = src.transform
        bounds = src.bounds
        crs = src.crs
        nodata = src.nodata if src.nodata is not None else -99999.0
        return {
            "width": int(src.width),
            "height": int(src.height),
            "left": float(bounds.left),
            "right": float(bounds.right),
            "top": float(bounds.top),
            "bottom": float(bounds.bottom),
            "res_x": abs(float(transform.a)),
            "res_y": abs(float(transform.e)),
            "crs": crs.to_string() if crs else "EPSG:4326",
            "nodata": float(nodata),
            "transform_a": float(transform.a),
            "transform_b": float(transform.b),
            "transform_c": float(transform.c),
            "transform_d": float(transform.d),
            "transform_e": float(transform.e),
            "transform_f": float(transform.f),
        }


def _grid_matches(a: dict, b: dict, tol_deg: float = 1e-7) -> bool:
    """两个格网规格是否为同一格网（尺寸 + 原点 + 分辨率都一致）。"""
    return (
        a["width"] == b["width"]
        and a["height"] == b["height"]
        and abs(a["left"] - b["left"]) <= tol_deg
        and abs(a["top"] - b["top"]) <= tol_deg
        and abs(a["res_x"] - b["res_x"]) <= tol_deg
        and abs(a["res_y"] - b["res_y"]) <= tol_deg
    )


def _resolve_dsm_spec(cfg: Task5CloudConfig) -> dict:
    """确定输出 DSM 的格网。

    有参考 DSM 时**以参考 DSM 的地理变换为准**：输出 DSM 必须与真值同格网（同原点、
    同分辨率、同尺寸）才能逐格对比，否则误用其它像对的 dsm_grid_spec.csv 会造成平面
    错位（例如 005/001 网格原点与 011/007 真值相差约 33 m，导致“屋顶比地面”而 RMSE 暴增）。
    仅在没有参考 DSM 时才用 CSV 规格。
    """
    from src.dsm_from_disparity.io_utils import read_dsm_grid_spec

    spec_path = Path(cfg.grid_spec) if cfg.grid_spec else None
    csv_spec = (
        read_dsm_grid_spec(str(spec_path))
        if (spec_path and spec_path.is_file())
        else None
    )

    ref_path = Path(cfg.ref_dsm) if cfg.ref_dsm else None
    if ref_path and ref_path.is_file():
        ref_spec = _spec_from_raster(ref_path)
        if csv_spec is not None and not _grid_matches(csv_spec, ref_spec):
            print("  注意: DSM 格网规格 CSV 与参考 DSM 不一致，已以参考 DSM 的地理变换为准：")
            print(
                f"    CSV : {csv_spec['width']}×{csv_spec['height']} "
                f"left={csv_spec['left']:.6f} top={csv_spec['top']:.6f}"
            )
            print(
                f"    参考: {ref_spec['width']}×{ref_spec['height']} "
                f"left={ref_spec['left']:.6f} top={ref_spec['top']:.6f}"
            )
        return ref_spec

    if csv_spec is None:
        raise FileNotFoundError("请在软件界面指定 DSM 格网规格 CSV 或参考 DSM")
    return csv_spec


def _load_ref_dsm_array(cfg: Task5CloudConfig, expected_shape: tuple[int, int] | None = None):
    if not cfg.ref_dsm:
        return None
    ref_path = Path(cfg.ref_dsm)
    if not ref_path.is_file():
        return None
    import rasterio

    with rasterio.open(ref_path) as src:
        arr = src.read(1)
    if expected_shape is not None and arr.shape != expected_shape:
        raise ValueError(
            f"参考 DSM 尺寸 {arr.shape[1]}×{arr.shape[0]} 与输出格网 "
            f"{expected_shape[1]}×{expected_shape[0]} 仍不一致，请检查输入。"
        )
    return arr


def _validate_disparity_rgb_shapes(disp, rgb, disp_path: Path, rgb_path: Path) -> None:
    if rgb is None:
        return
    if disp.shape == rgb.shape[1:]:
        return
    raise ValueError(
        f"视差与左 RGB 尺寸不一致:\n"
        f"  视差 {disp_path.name}: {disp.shape[1]}×{disp.shape[0]}\n"
        f"  左 RGB {rgb_path.name}: {rgb.shape[2]}×{rgb.shape[1]}\n"
        "请使用与视差同尺寸的核线左影像（同一 Task3 输出目录）。"
    )


# ---------------------------------------------------------------------------
# 输入一致性自检（保证“视差 / 左右 RPC / 同名点 / 真值”属于同一像对）
# ---------------------------------------------------------------------------

def _validate_stereo_pair(rpc_left, rpc_right) -> None:
    """左右 RPC 应覆盖同一地区：经纬 offset 之差应远小于 scale，否则疑似选错像对。"""
    dlon = abs(rpc_left.long_offset - rpc_right.long_offset)
    dlat = abs(rpc_left.lat_offset - rpc_right.lat_offset)
    lon_tol = 2.0 * max(rpc_left.long_scale, rpc_right.long_scale)
    lat_tol = 2.0 * max(rpc_left.lat_scale, rpc_right.lat_scale)
    if dlon > lon_tol or dlat > lat_tol:
        raise ValueError(
            "左、右 RPC 不像同一地区的立体像对（经纬 offset 偏差过大）。\n"
            f"  左 RPC 中心=({rpc_left.long_offset:.5f}, {rpc_left.lat_offset:.5f})\n"
            f"  右 RPC 中心=({rpc_right.long_offset:.5f}, {rpc_right.lat_offset:.5f})\n"
            "  请确认左右 RPC 选择正确，且与视差/同名点来自同一核线像对。"
        )


def _warn_disp_vs_rpc_size(disp, rpc_left) -> None:
    """视差(核线影像)尺寸应≈ 2*line_scale × 2*samp_scale，偏差大则提示像对可能不匹配。"""
    h, w = disp.shape
    exp_h = 2.0 * rpc_left.line_scale
    exp_w = 2.0 * rpc_left.samp_scale
    if exp_h <= 0 or exp_w <= 0:
        return
    if abs(h - exp_h) / exp_h > 0.1 or abs(w - exp_w) / exp_w > 0.1:
        print(
            f"  警告: 视差尺寸 {w}×{h} 与左核线 RPC 隐含尺寸 ~{exp_w:.0f}×{exp_h:.0f} "
            "偏差较大，请确认视差与 RPC 来自同一核线像对。"
        )


def _reprojection_residual_px(rpc_left, rpc_right, lon, lat, h,
                              line_l, samp_l, line_r, samp_r):
    """把交会得到的地面点投回两影像，与观测像点比较，返回每点综合残差(px)。

    数据自洽时残差≈0；若同名点/视差与 RPC 不属于同一像对，残差会显著增大。
    """
    pll, pls = rpc_left.project(lon, lat, h)
    prl, prs = rpc_right.project(lon, lat, h)
    return np.sqrt(
        (pll - line_l) ** 2 + (pls - samp_l) ** 2
        + (prl - line_r) ** 2 + (prs - samp_r) ** 2
    )


def _read_tie_columns(df):
    """通用识别同名点 CSV 中两幅影像的 image_<id>_line / image_<id>_sample 列（不写死 005/001）。

    返回 (left_id, right_id, line_l, samp_l, line_r, samp_r)；按列出现顺序，第一对为左、第二对为右。
    """
    import re

    ids: list[str] = []
    for c in df.columns:
        m = re.match(r"image_(.+)_line$", str(c))
        if m and m.group(1) not in ids and f"image_{m.group(1)}_sample" in df.columns:
            ids.append(m.group(1))
    if len(ids) < 2:
        raise ValueError(
            "同名点 CSV 需包含两幅影像的 image_<标识>_line 与 image_<标识>_sample 列，"
            f"当前识别到: {ids or '无'}"
        )
    lid, rid = ids[0], ids[1]
    def col(tag: str, kind: str):
        return df[f"image_{tag}_{kind}"].values.astype(np.float64)
    return lid, rid, col(lid, "line"), col(lid, "sample"), col(rid, "line"), col(rid, "sample")


def run_task5_intersect_points(cfg: Task5CloudConfig | None = None) -> str:
    """基础题1：同名点前方交会（与组员 intersect-points 一致）。"""
    _ensure_task5_deps()
    ensure_output_dirs()
    cfg = cfg or Task5CloudConfig()
    out_base = _out_base(cfg)
    tie_csv = Path(cfg.tie_csv) if cfg.tie_csv else None
    if not tie_csv or not tie_csv.is_file():
        raise FileNotFoundError("请在软件界面指定同名点 CSV")
    rpc_l = Path(cfg.rpc_left)
    rpc_r = Path(cfg.rpc_right)
    for p, name in [(tie_csv, "同名点 CSV"), (rpc_l, "左 RPC"), (rpc_r, "右 RPC")]:
        if not p.is_file():
            raise FileNotFoundError(f"{name} 不存在: {p}")

    import pandas as pd

    from src.dsm_from_disparity.intersection import intersect_many
    from src.dsm_from_disparity.io_utils import read_rpb, read_tie_points_csv
    from src.dsm_from_disparity.metrics import compute_rmse_3d

    print("Task5 同名点前方交会")
    rpc_left = read_rpb(str(rpc_l))
    rpc_right = read_rpb(str(rpc_r))
    _validate_stereo_pair(rpc_left, rpc_right)
    df = read_tie_points_csv(str(tie_csv))
    left_id, right_id, ll_obs, ls_obs, rl_obs, rs_obs = _read_tie_columns(df)
    print(f"  同名点列: 左=image_{left_id}_*  右=image_{right_id}_*  共 {len(df)} 点")
    lons, lats, heights = intersect_many(
        rpc_left, rpc_right, ll_obs, ls_obs, rl_obs, rs_obs,
    )

    # 反算残差自检：地面点投回两影像 vs 观测像点。
    # 注意：该残差能拦截“几何彻底错”（左右选反、视差/核线不是同一帧），但对“同一地区两个
    # 合法核线像对配错”无效（残差仍≈0，却会有数百米平面偏移）——后者须靠参考真值 3D RMSE 把关。
    res_px = _reprojection_residual_px(
        rpc_left, rpc_right, lons, lats, heights, ll_obs, ls_obs, rl_obs, rs_obs
    )
    finite = np.isfinite(res_px)
    rms_res = float(np.sqrt(np.mean(res_px[finite] ** 2))) if finite.any() else float("inf")
    print(f"  前方交会反算残差 RMSE = {rms_res:.3f} px（数据自洽时应≈0）")
    if (not finite.any()) or rms_res > 20.0:
        raise ValueError(
            f"同名点前方交会反算残差过大({rms_res:.2f} px)，几何严重不一致。\n"
            f"  疑似左右 RPC 选反，或同名点列(左=image_{left_id}, 右=image_{right_id})与核线 RPC 不匹配。"
        )
    if rms_res > 2.0:
        print(f"  警告: 反算残差偏大({rms_res:.2f} px)，请确认左右 RPC 与同名点确为同一核线像对。")

    out_dir = out_base / "tie_points"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "intersected_points.csv"
    df_out = pd.DataFrame(
        {"id": df["id"], "lon": lons, "lat": lats, "ellipsoid_height": heights}
    )
    df_out.to_csv(out_csv, index=False)
    print(f"  输出 {len(df_out)} 点 → {out_csv}")

    ref_csv = Path(cfg.ref_tie_csv) if cfg.ref_tie_csv else None
    msg = f"Task5 同名点交会完成: {len(df_out)} 点 → {out_csv}"
    if ref_csv is not None and ref_csv.is_file():
        from src.dsm_from_disparity.io_utils import read_reference_object_points

        ref = read_reference_object_points(str(ref_csv))
        merged = df_out.merge(ref, on="id", suffixes=("_est", "_ref"))
        metrics = compute_rmse_3d(
            merged["lon_est"].values,
            merged["lat_est"].values,
            merged["ellipsoid_height_est"].values,
            merged["lon_ref"].values,
            merged["lat_ref"].values,
            merged["ellipsoid_height_ref"].values,
        )
        metrics_dir = out_base / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([metrics]).to_csv(metrics_dir / "tie_points_rmse.csv", index=False)
        print(f"  3D RMSE: {metrics['rmse_3d_m']:.4f} m")
        if metrics["rmse_3d_m"] > 50.0:
            raise ValueError(
                f"同名点交会 3D RMSE 高达 {metrics['rmse_3d_m']:.1f} m，远超合理范围。\n"
                f"  极可能是『同名点 CSV(左=image_{left_id}, 右=image_{right_id}) 与参考真值』"
                "不是当前左右 RPC 对应的像对（像对配错）。\n"
                "  请改用与本核线像对匹配的同名点与参考真值（勿沿用其它像对的 CSV）。"
            )
        msg += f"（3D RMSE={metrics['rmse_3d_m']:.4f} m）"
    return msg


def run_task5_point_cloud(cfg: Task5CloudConfig | None = None) -> str:
    """基础题2：视差 → 点云（CPU batch/scipy 或 GPU）。"""
    ensure_output_dirs()
    cfg = cfg or Task5CloudConfig()
    method = _ensure_compute_backend(cfg)
    out_dir = _out_base(cfg) / "point_cloud"
    out_dir.mkdir(parents=True, exist_ok=True)

    disp_path = Path(cfg.disp_path)
    rpc_l = Path(cfg.rpc_left)
    rpc_r = Path(cfg.rpc_right)
    rgb_path = Path(cfg.rgb_left) if cfg.rgb_left else None

    for p, name in [(disp_path, "视差"), (rpc_l, "左RPC"), (rpc_r, "右RPC")]:
        if not p.is_file():
            raise FileNotFoundError(f"{name} 不存在: {p}")

    from src.dsm_from_disparity.disparity_to_cloud import disparity_to_cloud, valid_disparity_mask
    from src.dsm_from_disparity.io_utils import (
        read_disparity,
        read_image_rgb,
        read_rpb,
        write_point_cloud_csv,
        write_point_cloud_ply,
        lonlat_to_meters,
    )

    backend_label = {"batch": "CPU 批量", "scipy": "CPU 多进程", "gpu": "GPU"}.get(method, method)
    print("Task5 点云生成")
    print(f"  视差: {disp_path}")
    print(f"  后端: {backend_label}, stride={cfg.stride}, workers={cfg.workers}, chunk={cfg.chunk_size}")

    rpc_left = read_rpb(str(rpc_l))
    rpc_right = read_rpb(str(rpc_r))
    disp, disp_profile = read_disparity(str(disp_path))
    nodata = disp_profile.get("nodata", -99999.0)
    _validate_stereo_pair(rpc_left, rpc_right)
    _warn_disp_vs_rpc_size(disp, rpc_left)

    rgb = None
    if rgb_path and rgb_path.is_file():
        rgb, _ = read_image_rgb(str(rgb_path))
    _validate_disparity_rgb_shapes(disp, rgb, disp_path, rgb_path)

    mask = valid_disparity_mask(disp, nodata=nodata)
    est = int(mask.sum() / (cfg.stride**2))
    print(f"  有效视差像元: {mask.sum()}, 预计输出点: ~{est}")

    def progress(i: int, n: int) -> None:
        if n > 0:
            print(f"  进度: {i}/{n} ({100 * i / n:.1f}%)", flush=True)

    t0 = time.time()
    result = disparity_to_cloud(
        rpc_left,
        rpc_right,
        disp,
        disp_nodata=nodata,
        left_rgb=rgb,
        stride=cfg.stride,
        workers=cfg.workers,
        intersection_method=method,
        chunk_size=cfg.chunk_size,
        progress_callback=progress,
    )
    elapsed = time.time() - t0
    n_pts = len(result["lon"])
    if n_pts == 0:
        raise RuntimeError("未生成有效点云，请检查视差/RPC 或更换计算后端。")
    print(f"  生成 {n_pts} 点，耗时 {elapsed:.1f}s ({n_pts / max(elapsed, 0.1):.0f} 点/秒)")

    csv_path = out_dir / "point_cloud.csv"
    ply_path = out_dir / "point_cloud.ply"
    write_point_cloud_csv(str(csv_path), result["lon"], result["lat"], result["height"])
    write_point_cloud_ply(
        str(ply_path),
        result["lon"],
        result["lat"],
        result["height"],
        result.get("r"),
        result.get("g"),
        result.get("b"),
    )

    x_m, y_m = lonlat_to_meters(result["lon"], result["lat"])
    ply_vis = out_dir / "point_cloud_visual_local_m.ply"
    write_point_cloud_ply(
        str(ply_vis),
        x_m,
        y_m,
        result["height"],
        result.get("r"),
        result.get("g"),
        result.get("b"),
    )
    return f"Task5 点云完成 ({backend_label}): {n_pts} 点, {elapsed:.1f}s → {out_dir}"


def run_task5_dsm_idw(cfg: Task5CloudConfig | None = None) -> str:
    """进阶题：点云 → IDW DSM（单独运行）。"""
    ensure_output_dirs()
    cfg = cfg or Task5CloudConfig()
    out_base = _out_base(cfg)

    cloud_csv = out_base / "point_cloud" / "point_cloud.csv"
    if not cloud_csv.is_file():
        raise FileNotFoundError(f"请先运行点云生成: {cloud_csv}")

    import pandas as pd

    from src.dsm_from_disparity.dsm_grid import compute_dsm_grid_centers, create_dsm_grid, write_dsm
    from src.dsm_from_disparity.interpolation import interpolate_idw
    from src.dsm_from_disparity.metrics import compute_dsm_rmse

    df = pd.read_csv(cloud_csv)
    spec = _resolve_dsm_spec(cfg)
    grid_lon, grid_lat = compute_dsm_grid_centers(spec)

    print(f"Task5 DSM-IDW: {len(df)} 点 → {spec['width']}×{spec['height']} 格网")
    t0 = time.time()
    dsm = interpolate_idw(
        df["lon"].values,
        df["lat"].values,
        df["ellipsoid_height"].values,
        grid_lon,
        grid_lat,
        k=8,
        power=2.0,
        max_radius_m=3.0,
        nodata=spec["nodata"],
    )
    print(f"  插值耗时 {time.time() - t0:.1f}s")

    dsm_dir = out_base / "dsm"
    dsm_dir.mkdir(parents=True, exist_ok=True)
    _, profile = create_dsm_grid(spec)
    out_path = dsm_dir / "dsm_idw.tif"
    write_dsm(str(out_path), dsm, profile)

    ref_arr = _load_ref_dsm_array(cfg, expected_shape=dsm.shape)
    if ref_arr is not None:
        m = compute_dsm_rmse(dsm, ref_arr, nodata=spec["nodata"])
        metrics_dir = out_base / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([m]).to_csv(metrics_dir / "dsm_idw_rmse.csv", index=False)
        print(f"  DSM RMSE: {m['rmse_m']:.4f} m")

    return f"Task5 IDW DSM 完成 → {out_path}"


def run_task5_dsm_all(cfg: Task5CloudConfig | None = None) -> str:
    """挑战题 + 完整 DSM：IDW + Pure TIN masked + TIN hybrid（与组员 run-all 一致）。"""
    ensure_output_dirs()
    cfg = cfg or Task5CloudConfig()
    out_base = _out_base(cfg)
    cloud_csv = out_base / "point_cloud" / "point_cloud.csv"
    if not cloud_csv.is_file():
        raise FileNotFoundError(f"请先运行点云生成: {cloud_csv}")

    import pandas as pd
    import rasterio
    from scipy.spatial import Delaunay, cKDTree

    from src.dsm_from_disparity.dsm_grid import compute_dsm_grid_centers, create_dsm_grid, write_dsm
    from src.dsm_from_disparity.interpolation import build_point_support_mask
    from src.dsm_from_disparity.io_utils import write_geotiff
    from src.dsm_from_disparity.metrics import compute_dsm_error_map, compute_dsm_rmse

    df = pd.read_csv(cloud_csv)
    spec = _resolve_dsm_spec(cfg)
    grid_lon, grid_lat = compute_dsm_grid_centers(spec)
    h, w = grid_lon.shape
    print(f"Task5 DSM 全套: {len(df)} 点 → {w}×{h} 格网")

    lon0, lat0 = float(df["lon"].mean()), float(df["lat"].mean())
    mpl = 111320.0
    mpl_cos = mpl * np.cos(np.radians(lat0))
    px = (df["lon"].values - lon0) * mpl_cos
    py = (df["lat"].values - lat0) * mpl
    heights = df["ellipsoid_height"].values
    xy = np.column_stack([px, py])

    gx = (grid_lon.ravel() - lon0) * mpl_cos
    gy = (grid_lat.ravel() - lat0) * mpl
    grid_xy = np.column_stack([gx, gy])

    dsm_dir = out_base / "dsm"
    metrics_dir = out_base / "metrics"
    dsm_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)
    _, profile = create_dsm_grid(spec)

    ref_dsm = _load_ref_dsm_array(cfg, expected_shape=(h, w))

    tree = cKDTree(xy)
    _, unique_idx = np.unique(np.round(xy, decimals=4), axis=0, return_index=True)
    xy_u = xy[unique_idx]
    h_u = heights[unique_idx]
    tri = Delaunay(xy_u)
    support_mask = build_point_support_mask(
        df["lon"].values,
        df["lat"].values,
        grid_lon,
        grid_lat,
        spec,
        support_radius_m=cfg.support_radius,
    )
    tri_verts = xy_u[tri.simplices]
    edges = np.sqrt(((tri_verts[:, [0, 1, 2], :] - tri_verts[:, [1, 2, 0], :]) ** 2).sum(axis=2))
    tri_max_edge = edges.max(axis=1)
    max_edge = cfg.max_edge

    # IDW
    print("  → IDW")
    dist, idx = tree.query(grid_xy, k=8)
    dsm_flat = np.full(h * w, spec["nodata"], dtype=np.float32)
    for i in range(h * w):
        di = dist[i]
        ii = idx[i]
        in_r = di <= 3.0
        if np.any(in_r):
            di_v = np.maximum(di[in_r], 1e-12)
            wgt = 1.0 / (di_v**2)
            dsm_flat[i] = float(np.sum(wgt * heights[ii[in_r]]) / np.sum(wgt))
    dsm_idw = dsm_flat.reshape(h, w)
    write_dsm(str(dsm_dir / "dsm_idw.tif"), dsm_idw, profile)
    if ref_dsm is not None:
        m = compute_dsm_rmse(dsm_idw, ref_dsm, nodata=spec["nodata"])
        pd.DataFrame([m]).to_csv(metrics_dir / "dsm_idw_rmse.csv", index=False)
        print(f"    IDW RMSE={m['rmse_m']:.4f} m")

    # Pure TIN masked
    print("  → Pure TIN masked")
    simplex_idx = tri.find_simplex(grid_xy)
    valid = (simplex_idx >= 0) & support_mask.ravel() & (tri_max_edge[simplex_idx] <= max_edge)
    dsm_tm = np.full(h * w, spec["nodata"], dtype=np.float32)
    if np.any(valid):
        simplices = tri.simplices[simplex_idx[valid]]
        tris = tri.transform[simplex_idx[valid], :2]
        origins = tri.transform[simplex_idx[valid], 2]
        dx = grid_xy[valid, 0] - origins[:, 0]
        dy = grid_xy[valid, 1] - origins[:, 1]
        b1 = tris[:, 0, 0] * dx + tris[:, 0, 1] * dy
        b2 = tris[:, 1, 0] * dx + tris[:, 1, 1] * dy
        l0, l1, l2 = 1.0 - b1 - b2, b1, b2
        dsm_tm[valid] = (
            l0 * h_u[simplices[:, 0]] + l1 * h_u[simplices[:, 1]] + l2 * h_u[simplices[:, 2]]
        ).astype(np.float32)
        bad = (l0 < -1e-6) | (l1 < -1e-6) | (l2 < -1e-6)
        vf = np.where(valid)[0]
        dsm_tm[vf[bad]] = spec["nodata"]
    dsm_tm = dsm_tm.reshape(h, w)
    write_dsm(str(dsm_dir / "dsm_tin_pure_masked.tif"), dsm_tm, profile)
    if ref_dsm is not None:
        m = compute_dsm_rmse(dsm_tm, ref_dsm, nodata=spec["nodata"])
        pd.DataFrame([m]).to_csv(metrics_dir / "dsm_tin_pure_masked_rmse.csv", index=False)
        print(f"    Pure TIN RMSE={m['rmse_m']:.4f} m")

    # TIN + IDW hybrid
    print("  → TIN+IDW hybrid")
    use_tin = (simplex_idx >= 0) & support_mask.ravel() & (tri_max_edge[simplex_idx] <= max_edge)
    dsm_hy = np.full(h * w, spec["nodata"], dtype=np.float32)
    if np.any(use_tin):
        simplices_h = tri.simplices[simplex_idx[use_tin]]
        tris_h = tri.transform[simplex_idx[use_tin], :2]
        origins_h = tri.transform[simplex_idx[use_tin], 2]
        dx_h = grid_xy[use_tin, 0] - origins_h[:, 0]
        dy_h = grid_xy[use_tin, 1] - origins_h[:, 1]
        b1_h = tris_h[:, 0, 0] * dx_h + tris_h[:, 0, 1] * dy_h
        b2_h = tris_h[:, 1, 0] * dx_h + tris_h[:, 1, 1] * dy_h
        l0_h, l1_h, l2_h = 1.0 - b1_h - b2_h, b1_h, b2_h
        dsm_hy[use_tin] = (
            l0_h * h_u[simplices_h[:, 0]]
            + l1_h * h_u[simplices_h[:, 1]]
            + l2_h * h_u[simplices_h[:, 2]]
        ).astype(np.float32)
        bad_h = (l0_h < -1e-6) | (l1_h < -1e-6) | (l2_h < -1e-6)
        uf = np.where(use_tin)[0]
        dsm_hy[uf[bad_h]] = spec["nodata"]
    use_idw = dsm_hy == spec["nodata"]
    if np.any(use_idw):
        dsm_hy[use_idw] = dsm_idw.ravel()[use_idw]
    dsm_hy = dsm_hy.reshape(h, w)
    write_dsm(str(dsm_dir / "dsm_tin_hybrid.tif"), dsm_hy, profile)
    if ref_dsm is not None:
        m = compute_dsm_rmse(dsm_hy, ref_dsm, nodata=spec["nodata"])
        pd.DataFrame([m]).to_csv(metrics_dir / "dsm_tin_hybrid_rmse.csv", index=False)
        print(f"    Hybrid RMSE={m['rmse_m']:.4f} m")
        for name, dsm in [("idw", dsm_idw), ("tin_pure_masked", dsm_tm), ("tin_hybrid", dsm_hy)]:
            em = compute_dsm_error_map(dsm, ref_dsm, nodata=spec["nodata"])
            ep = profile.copy()
            ep.pop("nodata", None)
            write_geotiff(str(dsm_dir / f"dsm_{name}_error.tif"), em, ep)

    return f"Task5 DSM 全套完成 → {dsm_dir}"


def run_task5_all(cfg: Task5CloudConfig | None = None) -> str:
    """完整 Task5：同名点 + 点云 + 全部 DSM（与组员 run-all 对齐）。

    未指定同名点 CSV 时跳过“同名点前方交会”（例如 011/007 没有配套同名点），
    仍照常生成点云与完整 DSM，便于复现全流程而不被同名点步骤阻断。
    """
    cfg = cfg or Task5CloudConfig()
    msgs = []
    if cfg.tie_csv and Path(cfg.tie_csv).is_file():
        msgs.append(run_task5_intersect_points(cfg))
    else:
        msgs.append("跳过同名点前方交会（未指定同名点 CSV）")
    msgs.append(run_task5_point_cloud(cfg))
    msgs.append(run_task5_dsm_all(cfg))
    return "\n".join(msgs)


def run_task5_quick(cfg: Task5CloudConfig | None = None) -> str:
    """快速模式：点云 + IDW DSM（旧版 GUI 默认）。"""
    msg1 = run_task5_point_cloud(cfg)
    msg2 = run_task5_dsm_idw(cfg)
    return msg1 + "\n" + msg2
