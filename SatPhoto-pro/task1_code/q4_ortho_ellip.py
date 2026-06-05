# -*- coding: utf-8 -*-
"""第4题（进阶题，5分）：用 EGM2008 将 DEM 正常高改正为椭球高后正射纠正（正确结果）。

椭球高 h = 正常高 H(DEM) + 高程异常 N(EGM2008)。
RPC 模型的高程基准是椭球高（WGS84），故必须用椭球高才几何正确。

含交叉校验：12 个地面点高程为椭球高，DEM 上取正常高，
N_implied = h_ellip - H_dem 应与 EGM2008 的 N 接近，验证 N 正确。
"""
import os
from pathlib import Path

import numpy as np
from rpc import RPCModel
from ortho import orthorectify, dom_pixel_centers, valid_mask
from dem import DEM
from geoid_egm2008 import EGM2008Geoid
import raster_io as rio
import suite_paths as sp

OUT = sp.out_dir()
IMAGES = sp.images()
GEOID_CANDIDATES = [
    os.path.join(sp.ROOT, "geoid_data", "geoids", "egm2008-5.pgm"),
    os.path.join(sp.ROOT, "EGM2008 - 1'.pgm"),
]
GEOID = next((p for p in GEOID_CANDIDATES if os.path.isfile(p)), GEOID_CANDIDATES[0])


def _dem_files():
    dem = sp.dem_path()
    tfw = dem.with_suffix(".tfw")
    if not tfw.is_file():
        tfw = Path(str(dem) + ".tfw")
    return str(dem), str(tfw)


def suffix_of(img):
    return "" if img.endswith("001") else "_" + img[-3:]


def load_spec(img):
    spec_csv = sp.dom_spec_csv_optional()
    if spec_csv is not None:
        return rio.load_dom_spec(str(spec_csv), img)
    return rio.dom_spec_from_reference(str(sp.reference_dom()), img)


def cross_check_N(dem, geoid):
    """用地面点交叉校验 EGM2008（可选）。"""
    gp_path = sp.ground_points_csv()
    if gp_path is None:
        print("跳过 EGM2008 交叉校验：未找到 ground_points.csv")
        return
    gp = np.loadtxt(str(gp_path), delimiter=",", skiprows=1)
    lon_g, lat_g, h_ellip_g = gp[:, 1], gp[:, 2], gp[:, 3]
    H_dem_g = dem.interp(lon_g, lat_g)
    N_egm_g = geoid.undulation(lon_g, lat_g)
    N_implied = h_ellip_g - H_dem_g
    print("=== EGM2008 高程异常 N 交叉校验（12 个地面点）===")
    print(f"EGM2008 N      : 均值 {N_egm_g.mean():.3f} m  范围[{N_egm_g.min():.3f},{N_egm_g.max():.3f}]")
    print(f"控制点隐含 N    : 均值 {N_implied.mean():.3f} m  范围[{N_implied.min():.3f},{N_implied.max():.3f}]")
    print(f"两者差(N_egm - N_implied): 均值 {(N_egm_g-N_implied).mean():.3f} m  "
          f"RMSE {np.sqrt(np.mean((N_egm_g-N_implied)**2)):.3f} m")


def run(img, dem, geoid):
    sfx = suffix_of(img)
    rpc_path, tif_path = sp.image_paths(img)
    rpc = RPCModel(str(rpc_path))
    src = rio.read_tif(str(tif_path))
    spec = load_spec(img)

    # 椭球高高程面：h = 正常高 H(DEM) + 高程异常 N(EGM2008)
    def ellip_surface(LON, LAT):
        return dem.interp(LON, LAT) + geoid.undulation(LON, LAT)

    dom = orthorectify(rpc, src, spec, height_surface=ellip_surface)
    out = os.path.join(OUT, f"q4_dom_ellipH{sfx}.tif")
    rio.write_dom(out, dom, spec["left"], spec["top"], spec["res_x"], spec["res_y"])

    LON, LAT = dom_pixel_centers(spec)
    line, samp = rpc.forward(LAT, LON, ellip_surface(LON, LAT))
    m = valid_mask(line, samp, src.shape)
    print(f"[{img}] DOM 区域 N 均值 {geoid.undulation(LON, LAT).mean():.3f} m, "
          f"有效像素 {m.sum()}/{m.size} ({100*m.mean():.1f}%) -> {out} (椭球高正射, 正确)")


def main():
    os.makedirs(OUT, exist_ok=True)
    dem_tif, dem_tfw = _dem_files()
    dem = DEM(dem_tif, dem_tfw)
    geoid = EGM2008Geoid(GEOID)
    cross_check_N(dem, geoid)
    for img in IMAGES:
        run(img, dem, geoid)


if __name__ == "__main__":
    main()
