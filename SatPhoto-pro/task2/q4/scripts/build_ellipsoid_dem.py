# -*- coding: utf-8 -*-
"""由正高 DEM + EGM2008 生成椭球高 DEM（GeoTIFF）。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from osgeo import gdal

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA = ROOT / "实习数据" / "task2"
OUT_DIR = Path(__file__).resolve().parent.parent / "results"
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from egm2008_geoid import EGM2008Geoid, find_egm2008_pgm


def find_ortho_dem() -> Path:
    return next(DATA.rglob("USGS_13_n31w082_20221103_clip.tif"))


def build_ellipsoid_dem(out_path: Path | None = None) -> Path:
    ortho_path = find_ortho_dem()
    out_path = out_path or (OUT_DIR / "USGS_13_ellipsoid_dem.tif")

    ds = gdal.Open(str(ortho_path))
    if ds is None:
        raise FileNotFoundError(f"无法打开 DEM: {ortho_path}")

    h_ortho = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    rows, cols = h_ortho.shape

    # 像元中心经纬度
    cols_i = np.arange(cols, dtype=np.float64)
    rows_i = np.arange(rows, dtype=np.float64)
    lon_grid, lat_grid = np.meshgrid(
        gt[0] + (cols_i + 0.5) * gt[1],
        gt[3] + (rows_i + 0.5) * gt[5],
    )

    pgm = find_egm2008_pgm()
    n_grid = np.empty(h_ortho.shape, dtype=np.float64)
    with EGM2008Geoid(pgm) as geoid:
        flat_lat = lat_grid.ravel()
        flat_lon = lon_grid.ravel()
        flat_n = np.empty(flat_lat.size, dtype=np.float64)
        for i, (la, lo) in enumerate(zip(flat_lat, flat_lon)):
            flat_n[i] = float(geoid.height_anomaly(float(la), float(lo)))
        n_grid = flat_n.reshape(h_ortho.shape)

    h_ellipsoid = h_ortho + n_grid
    if nodata is not None:
        mask = h_ortho == nodata
        h_ellipsoid[mask] = nodata

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(str(out_path), cols, rows, 1, gdal.GDT_Float64)
    out_ds.SetGeoTransform(gt)
    out_ds.SetProjection(proj)
    band = out_ds.GetRasterBand(1)
    band.WriteArray(h_ellipsoid)
    if nodata is not None:
        band.SetNoDataValue(nodata)
    band.SetDescription("WGS84 ellipsoidal height = orthometric DEM + EGM2008 N")
    out_ds.FlushCache()
    out_ds = None

    print(f"正高 DEM: {ortho_path.name}")
    print(f"EGM2008:  {pgm.name}")
    print(f"椭球高 DEM: {out_path}")
    print(f"  N 范围: [{n_grid.min():.3f}, {n_grid.max():.3f}] m")
    print(f"  h 范围: [{np.nanmin(h_ellipsoid):.3f}, {np.nanmax(h_ellipsoid):.3f}] m")
    return out_path


if __name__ == "__main__":
    build_ellipsoid_dem()
