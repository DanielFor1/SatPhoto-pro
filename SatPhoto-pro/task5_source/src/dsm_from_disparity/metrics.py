"""Accuracy metrics for point intersection and DSM comparison."""

import numpy as np


def compute_rmse_3d(lons_est: np.ndarray, lats_est: np.ndarray,
                    heights_est: np.ndarray, lons_ref: np.ndarray,
                    lats_ref: np.ndarray, heights_ref: np.ndarray) -> dict:
    """Compute 3D RMSE between estimated and reference object coordinates.

    Lon/lat differences are converted to meters using the lat-based conversion.
    """
    lat_mid = np.mean(lats_ref)
    meter_per_deg_lat = 111320.0
    meter_per_deg_lon = 111320.0 * np.cos(np.radians(lat_mid))

    dlon_m = (lons_est - lons_ref) * meter_per_deg_lon
    dlat_m = (lats_est - lats_ref) * meter_per_deg_lat
    dh = heights_est - heights_ref

    rmse_lon = np.sqrt(np.mean(dlon_m ** 2))
    rmse_lat = np.sqrt(np.mean(dlat_m ** 2))
    rmse_h = np.sqrt(np.mean(dh ** 2))
    rmse_3d = np.sqrt(np.mean(dlon_m ** 2 + dlat_m ** 2 + dh ** 2))

    return {
        "rmse_lon_m": rmse_lon,
        "rmse_lat_m": rmse_lat,
        "rmse_h_m": rmse_h,
        "rmse_3d_m": rmse_3d,
        "n_points": len(lons_est),
    }


def compute_dsm_rmse(dsm_est: np.ndarray, dsm_ref: np.ndarray,
                     nodata: float = -99999.0) -> dict:
    """Compute per-pixel DSM RMSE only over pixels where both are valid.

    Args:
        dsm_est: Estimated DSM array.
        dsm_ref: Reference DSM array.
        nodata: Nodata value to exclude.
    Returns:
        dict with rmse, mae, valid_count.
    """
    if dsm_est.shape != dsm_ref.shape:
        h1, w1 = dsm_est.shape
        h2, w2 = dsm_ref.shape
        raise ValueError(
            f"DSM 尺寸不一致: 估算 {w1}×{h1}，参考 {w2}×{h2}。"
            "请让「DSM 格网规格 CSV」与参考 DSM 对应同一像对，"
            "或在界面中指定与参考 DSM 同尺寸的格网规格。"
        )

    mask = (dsm_est != nodata) & (dsm_ref != nodata) & \
           np.isfinite(dsm_est) & np.isfinite(dsm_ref)

    diff = dsm_est[mask] - dsm_ref[mask]
    n = mask.sum()
    if n == 0:
        return {"rmse_m": np.nan, "mae_m": np.nan, "valid_count": 0}

    rmse = np.sqrt(np.mean(diff ** 2))
    mae = np.mean(np.abs(diff))
    return {"rmse_m": rmse, "mae_m": mae, "valid_count": int(n)}


def compute_dsm_error_map(dsm_est: np.ndarray, dsm_ref: np.ndarray,
                          nodata: float = -99999.0) -> np.ndarray:
    """Return difference map (est - ref), with nodata where either is nodata."""
    if dsm_est.shape != dsm_ref.shape:
        h1, w1 = dsm_est.shape
        h2, w2 = dsm_ref.shape
        raise ValueError(
            f"DSM 尺寸不一致: 估算 {w1}×{h1}，参考 {w2}×{h2}。"
        )

    mask = (dsm_est != nodata) & (dsm_ref != nodata) & \
           np.isfinite(dsm_est) & np.isfinite(dsm_ref)
    error_map = np.full_like(dsm_est, nodata, dtype=np.float32)
    error_map[mask] = dsm_est[mask].astype(np.float32) - dsm_ref[mask].astype(np.float32)
    return error_map
