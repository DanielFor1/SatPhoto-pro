"""Convert disparity map to 3D point cloud via RPC forward intersection."""

import multiprocessing as mp

import numpy as np

from .rpc_model import RPCModel

# ---------------------------------------------------------------------------
# Multiprocessing worker globals — set once by Pool initializer.
# This avoids pickling RPCModel for every single pixel.
# ---------------------------------------------------------------------------
_worker_rpc_left = None
_worker_rpc_right = None
_worker_h0 = 0.0


def _worker_init(rpc_left: RPCModel, rpc_right: RPCModel, h0: float):
    """Pool initializer: store RPCs and initial height in globals."""
    global _worker_rpc_left, _worker_rpc_right, _worker_h0
    _worker_rpc_left = rpc_left
    _worker_rpc_right = rpc_right
    _worker_h0 = h0


def _worker_intersect(args):
    """Worker function — args is (r1, c1, r2, c2, r_val, g_val, b_val).

    Reads RPC models from global variables set by _worker_init.
    """
    from .intersection import intersect_single

    r1, c1, r2, c2, r_val, g_val, b_val = args
    try:
        lon, lat, h = intersect_single(
            _worker_rpc_left, _worker_rpc_right,
            (float(r1), float(c1)), (float(r2), float(c2)),
            initial=(_worker_rpc_left.long_offset, _worker_rpc_left.lat_offset, _worker_h0),
        )
    except Exception:
        lon, lat, h = np.nan, np.nan, np.nan
    return (lon, lat, h, r_val, g_val, b_val)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def valid_disparity_mask(disp: np.ndarray, nodata: float) -> np.ndarray:
    """Return boolean mask of valid disparity pixels."""
    return (disp != nodata) & np.isfinite(disp)


def disparity_to_cloud(rpc_left: RPCModel, rpc_right: RPCModel,
                       disp: np.ndarray,
                       disp_nodata: float,
                       left_rgb: np.ndarray = None,
                       stride: int = 1,
                       height_initial: float = None,
                       workers: int = 1,
                       intersection_method: str = "batch",
                       chunk_size: int = 100000,
                       progress_callback=None) -> dict:
    """Convert disparity map to point cloud via forward intersection.

    Args:
        rpc_left: Left image (005) RPC model.
        rpc_right: Right image (001) RPC model.
        disp: Disparity array (H, W), pixel units.
        disp_nodata: Nodata value from the disparity GeoTIFF.
        left_rgb: Optional left RGB image (3, H, W) for coloring.
        stride: Row/column stride.
        height_initial: Initial height guess for intersection.
        workers: Number of parallel workers (scipy mode only).
        intersection_method: "batch" or "scipy".
        chunk_size: Chunk size for batch processing.
        progress_callback: Optional callable(i, total) for progress.
    Returns:
        dict with keys: lon, lat, height, r, g, b (colors optional).
    """
    mask = valid_disparity_mask(disp, nodata=disp_nodata)
    H, W = disp.shape

    rows, cols = np.mgrid[0:H:stride, 0:W:stride]
    rows = rows.ravel()
    cols = cols.ravel()

    valid_positions = mask[rows, cols]
    rows = rows[valid_positions]
    cols = cols[valid_positions]
    disparities = disp[rows, cols]

    n = len(rows)
    has_color = left_rgb is not None
    h0 = height_initial if height_initial is not None else rpc_left.height_offset

    # Pre-extract RGB arrays
    if has_color:
        rgb_r = left_rgb[0]
        rgb_g = left_rgb[1]
        rgb_b = left_rgb[2]

    if intersection_method == "gpu":
        from .intersection import intersect_many_gpu

        line_l = rows.astype(np.float64)
        samp_l = cols.astype(np.float64)
        line_r = line_l.copy()
        samp_r = cols.astype(np.float64) + disparities

        cs = max(1, chunk_size)
        lons_all = np.empty(n, dtype=np.float64)
        lats_all = np.empty(n, dtype=np.float64)
        heights_all = np.empty(n, dtype=np.float64)

        for start in range(0, n, cs):
            end = min(start + cs, n)
            if progress_callback:
                progress_callback(start, n)
            lo, la, hh = intersect_many_gpu(
                rpc_left, rpc_right,
                line_l[start:end], samp_l[start:end],
                line_r[start:end], samp_r[start:end],
                initial=(rpc_left.long_offset, rpc_left.lat_offset, h0),
            )
            lons_all[start:end] = lo
            lats_all[start:end] = la
            heights_all[start:end] = hh

        if progress_callback:
            progress_callback(n, n)

        valid = np.isfinite(lons_all) & np.isfinite(lats_all) & np.isfinite(heights_all)
        result = {
            "lon": lons_all[valid],
            "lat": lats_all[valid],
            "height": heights_all[valid],
        }
        if has_color:
            result["r"] = rgb_r[rows[valid], cols[valid]]
            result["g"] = rgb_g[rows[valid], cols[valid]]
            result["b"] = rgb_b[rows[valid], cols[valid]]
        return result

    if intersection_method == "batch":
        # Build observation arrays
        line_l = rows.astype(np.float64)
        samp_l = cols.astype(np.float64)
        line_r = line_l.copy()  # r2 = r1
        samp_r = cols.astype(np.float64) + disparities

        from .intersection import intersect_many_batch

        # Process in chunks for memory efficiency
        cs = max(1, chunk_size)
        lons_all = np.empty(n, dtype=np.float64)
        lats_all = np.empty(n, dtype=np.float64)
        heights_all = np.empty(n, dtype=np.float64)

        initial_guess = (rpc_left.long_offset, rpc_left.lat_offset, h0)

        for start in range(0, n, cs):
            end = min(start + cs, n)
            if progress_callback:
                progress_callback(start, n)
            lo, la, hh = intersect_many_batch(
                rpc_left, rpc_right,
                line_l[start:end], samp_l[start:end],
                line_r[start:end], samp_r[start:end],
                initial=initial_guess,
            )
            lons_all[start:end] = lo
            lats_all[start:end] = la
            heights_all[start:end] = hh

        if progress_callback:
            progress_callback(n, n)

        valid = np.isfinite(lons_all) & np.isfinite(lats_all) & np.isfinite(heights_all)
        result = {
            "lon": lons_all[valid],
            "lat": lats_all[valid],
            "height": heights_all[valid],
        }
        if has_color:
            result["r"] = rgb_r[rows[valid], cols[valid]]
            result["g"] = rgb_g[rows[valid], cols[valid]]
            result["b"] = rgb_b[rows[valid], cols[valid]]
        return result

    if workers > 1:
        # Generator that yields args tuples lazily — no giant list.
        def _arg_generator():
            for i in range(n):
                r1 = float(rows[i])
                c1 = float(cols[i])
                r2 = r1
                c2 = c1 + float(disparities[i])
                rv = int(rgb_r[rows[i], cols[i]]) if has_color else 0
                gv = int(rgb_g[rows[i], cols[i]]) if has_color else 0
                bv = int(rgb_b[rows[i], cols[i]]) if has_color else 0
                yield (r1, c1, r2, c2, rv, gv, bv)

        chunksize = max(1, min(1000, n // (workers * 4)))
        with mp.Pool(
            processes=workers,
            initializer=_worker_init,
            initargs=(rpc_left, rpc_right, h0),
        ) as pool:
            results_iter = pool.imap_unordered(
                _worker_intersect, _arg_generator(), chunksize=chunksize,
            )
            # Collect results
            lons = np.empty(n, dtype=np.float64)
            lats = np.empty(n, dtype=np.float64)
            heights = np.empty(n, dtype=np.float64)
            if has_color:
                r_vals = np.empty(n, dtype=np.uint8)
                g_vals = np.empty(n, dtype=np.uint8)
                b_vals = np.empty(n, dtype=np.uint8)
            else:
                r_vals = g_vals = b_vals = None

            report_interval = max(1, n // 20)  # ~5% intervals
            for idx, res in enumerate(results_iter):
                lons[idx] = res[0]
                lats[idx] = res[1]
                heights[idx] = res[2]
                if has_color:
                    r_vals[idx] = res[3]
                    g_vals[idx] = res[4]
                    b_vals[idx] = res[5]
                if idx % report_interval == 0:
                    pct = 100.0 * idx / n
                    print(f"  {idx}/{n} ({pct:.1f}%)", flush=True)
    else:
        from .intersection import intersect_single

        lons = np.empty(n, dtype=np.float64)
        lats = np.empty(n, dtype=np.float64)
        heights = np.empty(n, dtype=np.float64)
        if has_color:
            r_vals = np.empty(n, dtype=np.uint8)
            g_vals = np.empty(n, dtype=np.uint8)
            b_vals = np.empty(n, dtype=np.uint8)
        else:
            r_vals = g_vals = b_vals = None

        for i in range(n):
            r1 = float(rows[i])
            c1 = float(cols[i])
            r2 = r1
            c2 = c1 + float(disparities[i])

            try:
                lon, lat, h = intersect_single(
                    rpc_left, rpc_right,
                    (r1, c1), (r2, c2),
                    initial=(rpc_left.long_offset, rpc_left.lat_offset, h0),
                )
            except Exception:
                lon, lat, h = np.nan, np.nan, np.nan

            lons[i] = lon
            lats[i] = lat
            heights[i] = h

            if has_color:
                r_vals[i] = rgb_r[rows[i], cols[i]]
                g_vals[i] = rgb_g[rows[i], cols[i]]
                b_vals[i] = rgb_b[rows[i], cols[i]]

            if i % max(1, n // 20) == 0:
                print(f"  {i}/{n} ({100.0*i/n:.1f}%)", flush=True)

    valid = np.isfinite(lons) & np.isfinite(lats) & np.isfinite(heights)
    result = {
        "lon": lons[valid],
        "lat": lats[valid],
        "height": heights[valid],
    }
    if has_color:
        result["r"] = r_vals[valid]
        result["g"] = g_vals[valid]
        result["b"] = b_vals[valid]
    return result
