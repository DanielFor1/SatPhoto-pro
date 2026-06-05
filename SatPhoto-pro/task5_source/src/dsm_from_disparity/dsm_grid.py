"""DSM grid creation and writing utilities."""

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.crs import CRS


def create_dsm_grid(spec: dict) -> tuple[np.ndarray, dict]:
    """Create an empty DSM array and corresponding GeoTIFF profile.

    Args:
        spec: Dict from io_utils.read_dsm_grid_spec().
    Returns:
        (array, profile) where array is (height, width) filled with nodata.
    """
    width = spec["width"]
    height = spec["height"]
    nodata = spec["nodata"]

    array = np.full((height, width), nodata, dtype=np.float32)

    # Use the affine transform from the spec
    transform = rasterio.transform.Affine(
        spec["transform_a"],
        spec["transform_b"],
        spec["transform_c"],
        spec["transform_d"],
        spec["transform_e"],
        spec["transform_f"],
    )

    crs_str = spec["crs"]
    if crs_str.startswith("EPSG:"):
        epsg_code = int(crs_str.split(":")[1])
        crs = CRS.from_epsg(epsg_code)
    else:
        crs = CRS.from_string(crs_str)

    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
    }
    return array, profile


def pixel_center_lonlat(spec: dict, rows: np.ndarray,
                        cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Compute pixel center lon/lat for given grid positions.

    Per spec: lon = left + (col + 0.5) * res_x
              lat = top - (row + 0.5) * res_y
    """
    lon = spec["left"] + (cols.astype(np.float64) + 0.5) * spec["res_x"]
    lat = spec["top"] - (rows.astype(np.float64) + 0.5) * spec["res_y"]
    return lon, lat


def compute_dsm_grid_centers(spec: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return (lon_grid, lat_grid) arrays of shape (height, width) for all pixel centers."""
    rows, cols = np.indices((spec["height"], spec["width"]), dtype=np.float64)
    return pixel_center_lonlat(spec, rows, cols)


def write_dsm(filepath: str, array: np.ndarray, profile: dict):
    """Write a DSM array to GeoTIFF."""
    profile.update(dtype=array.dtype, count=1)
    with rasterio.open(filepath, "w", **profile) as dst:
        dst.write(array, 1)
