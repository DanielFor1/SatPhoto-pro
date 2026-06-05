"""Command-line interface for DSM from disparity workflow."""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from .io_utils import (
    read_rpb,
    read_tie_points_csv,
    read_dsm_grid_spec,
    read_disparity,
    read_image_rgb,
    read_reference_object_points,
    write_geotiff,
    write_point_cloud_csv,
    write_point_cloud_ply,
    lonlat_to_meters,
)
from .intersection import intersect_many
from .disparity_to_cloud import disparity_to_cloud
from .dsm_grid import create_dsm_grid, compute_dsm_grid_centers, write_dsm
from .interpolation import (
    interpolate_nearest, interpolate_idw, interpolate_tin,
    interpolate_tin_hybrid,
)
from .metrics import compute_rmse_3d, compute_dsm_rmse, compute_dsm_error_map

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "task5"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "task5"
REF_DIR = DATA_DIR / "参考答案"
IMG_DIR = DATA_DIR / "影像"


def cmd_intersect_points(args):
    """Task 3: Forward-intersect same-name tie points."""
    rpc_left = read_rpb(str(IMG_DIR / "JAX_Tile_163_RGB_005_EPI.rpb"))
    rpc_right = read_rpb(str(IMG_DIR / "JAX_Tile_163_RGB_001_EPI.rpb"))

    df = read_tie_points_csv(str(DATA_DIR / "同名点.csv"))
    lons, lats, heights = intersect_many(
        rpc_left, rpc_right,
        df["image_005_line"].values, df["image_005_sample"].values,
        df["image_001_line"].values, df["image_001_sample"].values,
    )

    out_csv = OUTPUT_DIR / "tie_points" / "intersected_points.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df_out = pd.DataFrame({
        "id": df["id"],
        "lon": lons,
        "lat": lats,
        "ellipsoid_height": heights,
    })
    df_out.to_csv(out_csv, index=False)
    print(f"Wrote {len(df_out)} tie points to {out_csv}")

    # Compare with reference if available
    ref_csv = REF_DIR / "点物方坐标.csv"
    if ref_csv.exists():
        ref = read_reference_object_points(str(ref_csv))
        # Match by id
        merged = df_out.merge(ref, on="id", suffixes=("_est", "_ref"))
        metrics = compute_rmse_3d(
            merged["lon_est"].values, merged["lat_est"].values,
            merged["ellipsoid_height_est"].values,
            merged["lon_ref"].values, merged["lat_ref"].values,
            merged["ellipsoid_height_ref"].values,
        )
        print(f"RMSE lon: {metrics['rmse_lon_m']:.4f} m")
        print(f"RMSE lat: {metrics['rmse_lat_m']:.4f} m")
        print(f"RMSE h:   {metrics['rmse_h_m']:.4f} m")
        print(f"RMSE 3D:  {metrics['rmse_3d_m']:.4f} m")
        print(f"Points:   {metrics['n_points']}")

        # Save metrics
        metrics_path = OUTPUT_DIR / "metrics" / "tie_points_rmse.csv"
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([metrics]).to_csv(metrics_path, index=False)

        if metrics["rmse_3d_m"] >= 0.3:
            print("WARNING: 3D RMSE >= 0.3 m, check intersection implementation")
        else:
            print("PASS: 3D RMSE < 0.3 m")


def cmd_disparity_to_cloud(args):
    """Task 4: Convert disparity map to point cloud."""
    rpc_left = read_rpb(str(IMG_DIR / "JAX_Tile_163_RGB_005_EPI.rpb"))
    rpc_right = read_rpb(str(IMG_DIR / "JAX_Tile_163_RGB_001_EPI.rpb"))

    disp_path = IMG_DIR / "JAX_Tile_163_RGB_005_vs_JAX_Tile_163_RGB_001_DSP.tif"
    disp, disp_profile = read_disparity(str(disp_path))
    disp_nodata = disp_profile.get("nodata", -99999.0)
    print(f"Disparity shape: {disp.shape}, nodata={disp_nodata}, min={disp.min():.2f}, max={disp.max():.2f}")

    rgb_path = IMG_DIR / "JAX_Tile_163_RGB_005_EPI.tif"
    rgb, _ = read_image_rgb(str(rgb_path))
    print(f"RGB shape: {rgb.shape}")

    stride = getattr(args, "stride", 1)
    workers = getattr(args, "workers", 1)

    # Report scale
    from .disparity_to_cloud import valid_disparity_mask
    mask = valid_disparity_mask(disp, nodata=disp_nodata)
    total_valid = mask.sum()
    # Estimate points after stride
    est_points = int(total_valid / (stride * stride))
    print(f"Valid disparity pixels: {total_valid} ({total_valid/disp.size*100:.1f}%)")
    print(f"Stride: {stride} (row/col), estimated points: ~{est_points}")
    print(f"Workers: {workers}")

    def progress(i, n):
        if i % 100000 == 0:
            print(f"  {i}/{n} ({100*i/n:.1f}%)")

    print(f"Intersecting...")
    t0 = time.time()
    gpu_flag = getattr(args, "gpu", False)
    method = getattr(args, "intersection_method", "batch")
    if gpu_flag:
        if method not in ("batch", "gpu"):
            print("Error: --gpu conflicts with --intersection-method "
                  f"'{method}'. Use one or the other.")
            sys.exit(1)
        method = "gpu"
    chunksz = getattr(args, "chunk_size", 100000)
    print(f"Intersection method: {method}, chunk_size: {chunksz}")

    result = disparity_to_cloud(
        rpc_left, rpc_right, disp,
        disp_nodata=disp_nodata,
        left_rgb=rgb, stride=stride,
        workers=workers,
        intersection_method=method,
        chunk_size=chunksz,
        progress_callback=progress,
    )
    elapsed = time.time() - t0
    n_pts = len(result["lon"])
    print(f"Generated {n_pts} points in {elapsed:.1f}s")
    if n_pts == 0:
        raise RuntimeError(
            "Generated 0 valid points. The intersection method may have failed. "
            "Check the input disparity map or try a different --intersection-method. "
            "No files were written."
        )

    # Write outputs with configurable prefix
    prefix = getattr(args, "output_prefix", "point_cloud")
    cloud_dir = OUTPUT_DIR / "point_cloud"
    cloud_dir.mkdir(parents=True, exist_ok=True)

    csv_path = cloud_dir / f"{prefix}.csv"
    write_point_cloud_csv(
        str(csv_path),
        result["lon"], result["lat"], result["height"],
    )
    print(f"Wrote point cloud CSV to {csv_path}")

    ply_path = cloud_dir / f"{prefix}.ply"
    write_point_cloud_ply(
        str(ply_path),
        result["lon"], result["lat"], result["height"],
        result.get("r"), result.get("g"), result.get("b"),
    )
    print(f"Wrote point cloud PLY to {ply_path}")

    # Write visualization PLY in local meters (CloudCompare-friendly)
    x_m, y_m = lonlat_to_meters(result["lon"], result["lat"])
    ply_vis_path = cloud_dir / f"{prefix}_visual_local_m.ply"
    write_point_cloud_ply(
        str(ply_vis_path),
        x_m, y_m, result["height"],
        result.get("r"), result.get("g"), result.get("b"),
    )
    print(f"Wrote visualization PLY (local meters) to {ply_vis_path}")


def cmd_dsm_nearest(args):
    """Task 6a: Generate DSM by nearest-neighbor interpolation."""
    _generate_dsm("nearest", args)


def cmd_dsm_idw(args):
    """Task 6b: Generate DSM by IDW interpolation."""
    _generate_dsm("idw", args)


def _generate_dsm(method: str, args):
    """Shared DSM generation logic."""
    cloud_csv = OUTPUT_DIR / "point_cloud" / "point_cloud.csv"
    if not cloud_csv.exists():
        print("Point cloud not found. Run 'disparity-to-cloud' first.")
        sys.exit(1)

    df = pd.read_csv(cloud_csv)
    print(f"Loaded {len(df)} points from {cloud_csv}")

    spec = read_dsm_grid_spec(str(DATA_DIR / "dsm_grid_spec.csv"))
    grid_lon, grid_lat = compute_dsm_grid_centers(spec)
    print(f"DSM grid: {spec['width']} x {spec['height']}")

    t0 = time.time()
    if method == "nearest":
        dsm = interpolate_nearest(
            df["lon"].values, df["lat"].values, df["ellipsoid_height"].values,
            grid_lon, grid_lat, nodata=spec["nodata"],
        )
    elif method == "idw":
        dsm = interpolate_idw(
            df["lon"].values, df["lat"].values, df["ellipsoid_height"].values,
            grid_lon, grid_lat,
            k=getattr(args, "k", 8),
            power=getattr(args, "power", 2.0),
            max_radius_m=getattr(args, "max_radius", 3.0),
            nodata=spec["nodata"],
        )
    else:
        raise ValueError(f"Unknown method: {method}")

    elapsed = time.time() - t0
    valid_count = np.sum(dsm != spec["nodata"])
    print(f"Generated DSM in {elapsed:.1f}s, {valid_count} valid pixels")

    # Write DSM
    dsm_dir = OUTPUT_DIR / "dsm"
    dsm_dir.mkdir(parents=True, exist_ok=True)
    _, profile = create_dsm_grid(spec)
    out_path = dsm_dir / f"dsm_{method}.tif"
    write_dsm(str(out_path), dsm, profile)
    print(f"Wrote DSM to {out_path}")

    # Compare with reference
    ref_path = REF_DIR / "JAX_Tile_163_RGB_005_vs_JAX_Tile_163_RGB_001_DSM.tif"
    if ref_path.exists():
        with rasterio.open(ref_path) as src:
            ref_dsm = src.read(1)
            ref_profile = src.profile
        metrics = compute_dsm_rmse(dsm, ref_dsm, nodata=spec["nodata"])
        print(f"DSM RMSE: {metrics['rmse_m']:.4f} m")
        print(f"DSM MAE:  {metrics['mae_m']:.4f} m")
        print(f"Valid pixels compared: {metrics['valid_count']}")

        # Save metrics
        metrics_dir = OUTPUT_DIR / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([metrics]).to_csv(metrics_dir / f"dsm_{method}_rmse.csv", index=False)

        # Error map
        error_map = compute_dsm_error_map(dsm, ref_dsm, nodata=spec["nodata"])
        error_profile = profile.copy()
        error_profile.pop("nodata", None)
        write_geotiff(str(dsm_dir / f"dsm_{method}_error.tif"), error_map, error_profile)

        if metrics["rmse_m"] >= 2.0:
            print("WARNING: RMSE >= 2 m")
        else:
            print("PASS: RMSE < 2 m")


def cmd_dsm_tin(args):
    """Task 7: Generate DSM by Delaunay TIN interpolation.

    Modes:
      (default)           Pure TIN, no filtering.
      --max-edge X        TIN+IDW hybrid: small triangles use TIN, large ones IDW.
      --pure-mask         Pure TIN with support mask + edge filter, nodata holes.
    """
    cloud_csv = OUTPUT_DIR / "point_cloud" / "point_cloud.csv"
    if not cloud_csv.exists():
        print("Point cloud not found. Run 'disparity-to-cloud' first.")
        sys.exit(1)

    df = pd.read_csv(cloud_csv)
    print(f"Loaded {len(df)} points from {cloud_csv}")

    spec = read_dsm_grid_spec(str(DATA_DIR / "dsm_grid_spec.csv"))
    grid_lon, grid_lat = compute_dsm_grid_centers(spec)
    print(f"DSM grid: {spec['width']} x {spec['height']}")

    max_edge = getattr(args, "max_edge", None)
    pure_mask = getattr(args, "pure_mask", False)
    support_radius = getattr(args, "support_radius", 3.0)

    t0 = time.time()
    if pure_mask:
        from .interpolation import build_point_support_mask
        print(f"Pure TIN masked mode: support_radius={support_radius}m, max_edge={max_edge or 8.0}m")
        mask = build_point_support_mask(
            df["lon"].values, df["lat"].values,
            grid_lon, grid_lat, spec,
            support_radius_m=support_radius,
        )
        dsm = interpolate_tin(
            df["lon"].values, df["lat"].values, df["ellipsoid_height"].values,
            grid_lon, grid_lat, nodata=spec["nodata"],
            support_mask=mask,
            max_edge_m=max_edge if max_edge is not None else 8.0,
        )
        suffix = "_tin_pure_masked"
    elif max_edge is not None:
        hyb_mask = None
        if support_radius > 0:
            from .interpolation import build_point_support_mask
            hyb_mask = build_point_support_mask(
                df["lon"].values, df["lat"].values,
                grid_lon, grid_lat, spec,
                support_radius_m=support_radius,
            )
        print(f"Using TIN+IDW hybrid (max_edge={max_edge}m, support_radius={support_radius}m)")
        dsm = interpolate_tin_hybrid(
            df["lon"].values, df["lat"].values, df["ellipsoid_height"].values,
            grid_lon, grid_lat,
            max_edge_m=max_edge, nodata=spec["nodata"],
            support_mask=hyb_mask,
        )
        suffix = "_tin_hybrid"
    else:
        dsm = interpolate_tin(
            df["lon"].values, df["lat"].values, df["ellipsoid_height"].values,
            grid_lon, grid_lat, nodata=spec["nodata"],
        )
        suffix = "_tin"
    elapsed = time.time() - t0
    valid_count = np.sum(dsm != spec["nodata"])
    print(f"Generated TIN DSM in {elapsed:.1f}s, {valid_count} valid pixels")

    dsm_dir = OUTPUT_DIR / "dsm"
    dsm_dir.mkdir(parents=True, exist_ok=True)
    _, profile = create_dsm_grid(spec)
    out_path = dsm_dir / f"dsm{suffix}.tif"
    write_dsm(str(out_path), dsm, profile)
    print(f"Wrote TIN DSM to {out_path}")

    ref_path = REF_DIR / "JAX_Tile_163_RGB_005_vs_JAX_Tile_163_RGB_001_DSM.tif"
    if ref_path.exists():
        with rasterio.open(ref_path) as src:
            ref_dsm = src.read(1)
        metrics = compute_dsm_rmse(dsm, ref_dsm, nodata=spec["nodata"])
        print(f"TIN DSM RMSE: {metrics['rmse_m']:.4f} m")
        print(f"TIN DSM MAE:  {metrics['mae_m']:.4f} m")
        print(f"Valid pixels compared: {metrics['valid_count']}")

        metrics_dir = OUTPUT_DIR / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        metric_name = f"dsm{suffix}_rmse.csv"
        pd.DataFrame([metrics]).to_csv(metrics_dir / metric_name, index=False)

        error_map = compute_dsm_error_map(dsm, ref_dsm, nodata=spec["nodata"])
        error_profile = profile.copy()
        error_profile.pop("nodata", None)
        err_name = f"dsm{suffix}_error.tif"
        write_geotiff(str(dsm_dir / err_name), error_map, error_profile)

        if metrics["rmse_m"] >= 2.0:
            print("WARNING: RMSE >= 2 m")
        else:
            print("PASS: RMSE < 2 m")


def _run_tin_variant(args, pure_mask: bool):
    """Run a single TIN variant by toggling pure_mask on args."""
    saved = getattr(args, "pure_mask", False)
    args.pure_mask = pure_mask
    try:
        cmd_dsm_tin(args)
    finally:
        args.pure_mask = saved


def _run_dsm_shared(args):
    """Run all three DSM methods with shared point cloud, grid, and triangulation."""
    cloud_csv = OUTPUT_DIR / "point_cloud" / "point_cloud.csv"
    if not cloud_csv.exists():
        print("Point cloud not found. Run 'disparity-to-cloud' first.")
        sys.exit(1)

    import time as _time
    from .interpolation import (
        interpolate_idw, interpolate_tin, interpolate_tin_hybrid,
        build_point_support_mask, _to_local_meters,
    )
    from scipy.spatial import cKDTree, Delaunay

    t_total = _time.time()

    # ---- Load once ----
    df = pd.read_csv(cloud_csv)
    n_pts = len(df)
    print(f"Loaded {n_pts} points from {cloud_csv}")

    spec = read_dsm_grid_spec(str(DATA_DIR / "dsm_grid_spec.csv"))
    grid_lon, grid_lat = compute_dsm_grid_centers(spec)
    H, W = grid_lon.shape
    print(f"DSM grid: {W} x {H}")

    lon0, lat0 = float(df["lon"].mean()), float(df["lat"].mean())
    mpl = 111320.0
    mpl_cos = mpl * np.cos(np.radians(lat0))

    px = (df["lon"].values - lon0) * mpl_cos
    py = (df["lat"].values - lat0) * mpl
    h = df["ellipsoid_height"].values
    xy = np.column_stack([px, py])

    gx = (grid_lon.ravel() - lon0) * mpl_cos
    gy = (grid_lat.ravel() - lat0) * mpl
    grid_xy = np.column_stack([gx, gy])

    dsm_dir = OUTPUT_DIR / "dsm"
    dsm_dir.mkdir(parents=True, exist_ok=True)
    _, profile = create_dsm_grid(spec)
    metrics_dir = OUTPUT_DIR / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    # ---- Reference DSM ----
    ref_path = REF_DIR / "JAX_Tile_163_RGB_005_vs_JAX_Tile_163_RGB_001_DSM.tif"
    if ref_path.exists():
        with rasterio.open(ref_path) as src:
            ref_dsm = src.read(1)
    else:
        ref_dsm = None

    max_edge = getattr(args, "max_edge", 10.0)
    support_radius = getattr(args, "support_radius", 3.0)

    # ---- Shared structures (built once) ----
    t0 = _time.time()
    tree = cKDTree(xy)
    print(f"  KDTree built in {_time.time()-t0:.1f}s")

    t0 = _time.time()
    # Delaunay: keep unique XY
    _, unique_idx = np.unique(np.round(xy, decimals=4), axis=0, return_index=True)
    xy_u = xy[unique_idx]; h_u = h[unique_idx]
    tri = Delaunay(xy_u)
    print(f"  Delaunay built in {_time.time()-t0:.1f}s ({len(xy_u)} unique points)")

    t0 = _time.time()
    support_mask = build_point_support_mask(
        df["lon"].values, df["lat"].values, grid_lon, grid_lat, spec,
        support_radius_m=support_radius)
    print(f"  Support mask built in {_time.time()-t0:.1f}s")

    # Triangle max edge
    tri_verts = xy_u[tri.simplices]
    edges = np.sqrt(((tri_verts[:, [0,1,2],:] - tri_verts[:, [1,2,0],:])**2).sum(axis=2))
    tri_max_edge = edges.max(axis=1)

    # ---- IDW ----
    print()
    print("=" * 40)
    print("DSM: IDW interpolation")
    t0 = _time.time()
    dist, idx = tree.query(grid_xy, k=8)
    dsm = np.full(H * W, spec["nodata"], dtype=np.float32)
    for i in range(H * W):
        di = dist[i]; ii = idx[i]
        in_r = di <= 3.0
        if np.any(in_r):
            di_v = np.maximum(di[in_r], 1e-12)
            w = 1.0 / (di_v ** 2)
            dsm[i] = float(np.sum(w * h[ii[in_r]]) / np.sum(w))
    dsm_idw = dsm.reshape(H, W)
    write_dsm(str(dsm_dir / "dsm_idw.tif"), dsm_idw, profile)
    if ref_dsm is not None:
        m = compute_dsm_rmse(dsm_idw, ref_dsm, nodata=spec["nodata"])
        pd.DataFrame([m]).to_csv(metrics_dir / "dsm_idw_rmse.csv", index=False)
        print(f"  RMSE={m['rmse_m']:.4f}m, time={_time.time()-t0:.1f}s")

    # ---- Pure TIN masked ----
    print()
    print("=" * 40)
    print("DSM: Pure TIN masked")
    t0 = _time.time()
    simplex_idx = tri.find_simplex(grid_xy)
    valid = (simplex_idx >= 0) & support_mask.ravel() & (tri_max_edge[simplex_idx] <= max_edge)
    dsm_tm = np.full(H * W, spec["nodata"], dtype=np.float32)
    if np.any(valid):
        simplices = tri.simplices[simplex_idx[valid]]
        tris = tri.transform[simplex_idx[valid], :2]
        origins = tri.transform[simplex_idx[valid], 2]
        dx = grid_xy[valid,0] - origins[:,0]; dy = grid_xy[valid,1] - origins[:,1]
        b1 = tris[:,0,0]*dx + tris[:,0,1]*dy; b2 = tris[:,1,0]*dx + tris[:,1,1]*dy
        l0 = 1.0-b1-b2; l1 = b1; l2 = b2
        dsm_tm[valid] = (l0*h_u[simplices[:,0]] + l1*h_u[simplices[:,1]] + l2*h_u[simplices[:,2]]).astype(np.float32)
        bad = (l0<-1e-6)|(l1<-1e-6)|(l2<-1e-6)
        vf = np.where(valid)[0]; dsm_tm[vf[bad]] = spec["nodata"]
    dsm_tm = dsm_tm.reshape(H, W)
    write_dsm(str(dsm_dir / "dsm_tin_pure_masked.tif"), dsm_tm, profile)
    if ref_dsm is not None:
        m = compute_dsm_rmse(dsm_tm, ref_dsm, nodata=spec["nodata"])
        pd.DataFrame([m]).to_csv(metrics_dir / "dsm_tin_pure_masked_rmse.csv", index=False)
        print(f"  RMSE={m['rmse_m']:.4f}m, time={_time.time()-t0:.1f}s")

    # ---- TIN+IDW hybrid ----
    print()
    print("=" * 40)
    print("DSM: TIN+IDW hybrid")
    t0 = _time.time()
    use_tin = (simplex_idx >= 0) & support_mask.ravel() & (tri_max_edge[simplex_idx] <= max_edge)
    dsm_hy = np.full(H * W, spec["nodata"], dtype=np.float32)
    if np.any(use_tin):
        simplices_h = tri.simplices[simplex_idx[use_tin]]
        tris_h = tri.transform[simplex_idx[use_tin], :2]
        origins_h = tri.transform[simplex_idx[use_tin], 2]
        dx_h = grid_xy[use_tin,0]-origins_h[:,0]; dy_h = grid_xy[use_tin,1]-origins_h[:,1]
        b1_h = tris_h[:,0,0]*dx_h+tris_h[:,0,1]*dy_h; b2_h = tris_h[:,1,0]*dx_h+tris_h[:,1,1]*dy_h
        l0_h = 1.0-b1_h-b2_h; l1_h = b1_h; l2_h = b2_h
        dsm_hy[use_tin] = (l0_h*h_u[simplices_h[:,0]]+l1_h*h_u[simplices_h[:,1]]+l2_h*h_u[simplices_h[:,2]]).astype(np.float32)
        bad_h = (l0_h<-1e-6)|(l1_h<-1e-6)|(l2_h<-1e-6)
        uf = np.where(use_tin)[0]; dsm_hy[uf[bad_h]] = spec["nodata"]
    # IDW fill for remaining
    use_idw = dsm_hy == spec["nodata"]
    if np.any(use_idw):
        dsm_hy[use_idw] = dsm_idw.ravel()[use_idw]
    dsm_hy = dsm_hy.reshape(H, W)
    write_dsm(str(dsm_dir / "dsm_tin_hybrid.tif"), dsm_hy, profile)
    if ref_dsm is not None:
        m = compute_dsm_rmse(dsm_hy, ref_dsm, nodata=spec["nodata"])
        pd.DataFrame([m]).to_csv(metrics_dir / "dsm_tin_hybrid_rmse.csv", index=False)
        print(f"  RMSE={m['rmse_m']:.4f}m, time={_time.time()-t0:.1f}s")

    # ---- Error maps ----
    for name, dsm in [("idw", dsm_idw), ("tin_pure_masked", dsm_tm), ("tin_hybrid", dsm_hy)]:
        if ref_dsm is not None:
            em = compute_dsm_error_map(dsm, ref_dsm, nodata=spec["nodata"])
            ep = profile.copy(); ep.pop("nodata", None)
            write_geotiff(str(dsm_dir / f"dsm_{name}_error.tif"), em, ep)

    print()
    print(f"All DSM outputs in {dsm_dir}, total time {_time.time()-t_total:.1f}s")


def cmd_run_all(args):
    """Run the complete validated workflow."""
    steps = [
        ("Forward intersection of tie points", cmd_intersect_points),
        ("Disparity to point cloud", cmd_disparity_to_cloud),
        ("DSM stage (shared computation)", _run_dsm_shared),
    ]
    for label, func in steps:
        print()
        print("=" * 60)
        print(f"Step: {label}")
        print("=" * 60)
        func(args)

    print()
    print("=" * 60)
    print("All tasks complete.")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="DSM from satellite stereo disparity maps",
        prog="dsm-from-disparity",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    p = sub.add_parser("intersect-points", help="Forward-intersect tie points")
    p.set_defaults(func=cmd_intersect_points)

    p = sub.add_parser("disparity-to-cloud", help="Convert disparity to point cloud")
    p.add_argument("--stride", type=int, default=1,
                   help="Row/column stride (1=all pixels, 2=every other row/col)")
    p.add_argument("--workers", type=int, default=1,
                   help="Number of parallel workers (scipy mode)")
    p.add_argument("--intersection-method", choices=["batch", "scipy", "gpu"], default="batch",
                   help="Intersection method (default: batch)")
    p.add_argument("--gpu", action="store_true", default=False,
                   help="Shortcut for --intersection-method gpu")
    p.add_argument("--chunk-size", type=int, default=100000,
                   help="Chunk size for batch processing (default: 100000)")
    p.add_argument("--output-prefix", type=str, default="point_cloud",
                   help="Output file prefix (default: point_cloud)")
    p.set_defaults(func=cmd_disparity_to_cloud)

    p = sub.add_parser("dsm-nearest", help="Generate DSM by nearest neighbor")
    p.set_defaults(func=cmd_dsm_nearest)

    p = sub.add_parser("dsm-idw", help="Generate DSM by IDW interpolation")
    p.add_argument("--k", type=int, default=8, help="Number of neighbors")
    p.add_argument("--power", type=float, default=2.0, help="Distance power")
    p.add_argument("--max-radius", type=float, default=3.0, help="Max search radius (m)")
    p.set_defaults(func=cmd_dsm_idw)

    p = sub.add_parser("dsm-tin", help="Generate DSM by Delaunay TIN")
    p.add_argument("--max-edge", type=float, default=None,
                   help="Max triangle edge (m); with --pure-mask: pure nodata filter, "
                        "without: hybrid TIN+IDW fallback")
    p.add_argument("--pure-mask", action="store_true", default=False,
                   help="Apply point support mask + edge filter, output nodata holes")
    p.add_argument("--support-radius", type=float, default=3.0,
                   help="Support mask radius in meters (default: 3.0)")
    p.set_defaults(func=cmd_dsm_tin)

    p = sub.add_parser("run-all", help="Run complete workflow")
    p.add_argument("--stride", type=int, default=1,
                   help="Row/column stride (1=all pixels)")
    p.add_argument("--workers", type=int, default=16,
                   help="Number of parallel workers (scipy mode; default: 16)")
    p.add_argument("--intersection-method", choices=["batch", "scipy", "gpu"], default="batch",
                   help="Intersection method (default: batch)")
    p.add_argument("--gpu", action="store_true", default=False,
                   help="Shortcut for --intersection-method gpu")
    p.add_argument("--chunk-size", type=int, default=100000,
                   help="Chunk size for batch processing (default: 100000)")
    p.add_argument("--max-edge", type=float, default=10.0,
                   help="Max triangle edge (m) for TIN (default: 10)")
    p.add_argument("--support-radius", type=float, default=3.0,
                   help="Support mask radius in meters (default: 3.0)")
    p.set_defaults(func=cmd_run_all)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
    else:
        args.func(args)


if __name__ == "__main__":
    main()
