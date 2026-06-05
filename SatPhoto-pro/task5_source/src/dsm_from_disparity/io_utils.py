"""I/O utilities for reading and writing data files."""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_bounds


def read_rpb(filepath: str) -> "RPCModel":
    """Parse an RPB file and return an RPCModel. Thin wrapper for convenience."""
    from .rpc_model import RPCModel
    return RPCModel.from_rpb(filepath)


def read_tie_points_csv(filepath: str) -> pd.DataFrame:
    """Read same-name tie points CSV file."""
    return pd.read_csv(filepath)


def read_dsm_grid_spec(filepath: str) -> dict:
    """Read DSM grid specification CSV and return a dict of parameters."""
    df = pd.read_csv(filepath)
    row = df.iloc[0]
    return {
        "width": int(row["width"]),
        "height": int(row["height"]),
        "left": float(row["left"]),
        "right": float(row["right"]),
        "top": float(row["top"]),
        "bottom": float(row["bottom"]),
        "res_x": float(row["res_x"]),
        "res_y": float(row["res_y"]),
        "crs": row["crs"],
        "nodata": float(row["nodata"]),
        "transform_a": float(row["transform_a"]),
        "transform_b": float(row["transform_b"]),
        "transform_c": float(row["transform_c"]),
        "transform_d": float(row["transform_d"]),
        "transform_e": float(row["transform_e"]),
        "transform_f": float(row["transform_f"]),
    }


def read_disparity(filepath: str) -> tuple[np.ndarray, rasterio.profiles.Profile]:
    """Read disparity GeoTIFF, return (array, profile)."""
    with rasterio.open(filepath) as src:
        data = src.read(1)
        profile = src.profile
    return data, profile


def read_image_rgb(filepath: str) -> tuple[np.ndarray, rasterio.profiles.Profile]:
    """Read RGB GeoTIFF, return (array, profile). Array shape: (3, H, W)."""
    with rasterio.open(filepath) as src:
        data = src.read()
        profile = src.profile
    return data, profile


def read_reference_object_points(filepath: str) -> pd.DataFrame:
    """Read reference answer CSV with lon, lat, ellipsoid_height columns."""
    return pd.read_csv(filepath)


def write_geotiff(filepath: str, array: np.ndarray, profile: dict):
    """Write a single-band GeoTIFF using the given profile."""
    profile.update(dtype=array.dtype, count=1)
    with rasterio.open(filepath, "w", **profile) as dst:
        dst.write(array, 1)


def write_point_cloud_csv(filepath: str, lon: np.ndarray, lat: np.ndarray,
                          height: np.ndarray):
    """Write point cloud as CSV with columns lon, lat, ellipsoid_height."""
    df = pd.DataFrame({
        "lon": lon,
        "lat": lat,
        "ellipsoid_height": height,
    })
    df.to_csv(filepath, index=False)


def write_point_cloud_ply(filepath: str, lon: np.ndarray, lat: np.ndarray,
                          height: np.ndarray, r: np.ndarray = None,
                          g: np.ndarray = None, b: np.ndarray = None):
    """Write a point cloud as a colored PLY file.

    Args:
        filepath: Output PLY path.
        lon, lat, height: Coordinates in degrees/meters.
        r, g, b: Optional uint8 color arrays.
    """
    n = len(lon)
    has_color = r is not None and g is not None and b is not None

    with open(filepath, "w") as f:
        f.write("ply\n")
        f.write("format ascii 1.0\n")
        f.write(f"element vertex {n}\n")
        f.write("property float x\n")
        f.write("property float y\n")
        f.write("property float z\n")
        if has_color:
            f.write("property uchar red\n")
            f.write("property uchar green\n")
            f.write("property uchar blue\n")
        f.write("end_header\n")
        for i in range(n):
            if has_color:
                f.write(f"{lon[i]:.10f} {lat[i]:.10f} {height[i]:.6f} "
                        f"{r[i]} {g[i]} {b[i]}\n")
            else:
                f.write(f"{lon[i]:.10f} {lat[i]:.10f} {height[i]:.6f}\n")


def lonlat_to_meters(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Convert lon/lat degrees to local meters using approximate formulas.

    Uses mid-latitude and mid-longitude reference.
    1 deg lat ≈ 111320 m
    1 deg lon ≈ 111320 * cos(lat_mid) m
    """
    lat_mid = np.mean(lat)
    meter_per_deg_lat = 111320.0
    meter_per_deg_lon = 111320.0 * np.cos(np.radians(lat_mid))
    x_m = (lon - np.mean(lon)) * meter_per_deg_lon
    y_m = (lat - np.mean(lat)) * meter_per_deg_lat
    return x_m, y_m
