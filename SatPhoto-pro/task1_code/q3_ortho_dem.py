# -*- coding: utf-8 -*-
"""第3题（进阶题，10分）：正射纠正到 DEM 高程面（DEM 为正常高/水准高）。

与第2题相同，但每个 DOM 像素的高程 Z 由 DEM 双线性内插获得。
注意：此处直接用正常高，未做椭球高改正，几何上相对第4题(椭球高)略有偏差。
"""
import os
from pathlib import Path

import numpy as np
from rpc import RPCModel
from ortho import orthorectify, dom_pixel_centers, valid_mask
from dem import DEM
import raster_io as rio

import suite_paths as sp
import raster_io as rio

OUT = sp.out_dir()
IMAGES = sp.images()


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


def run(img, dem):
    sfx = suffix_of(img)
    rpc_path, tif_path = sp.image_paths(img)
    rpc = RPCModel(str(rpc_path))
    src = rio.read_tif(str(tif_path))
    spec = load_spec(img)

    dom = orthorectify(rpc, src, spec, height_surface=dem.interp)

    out = os.path.join(OUT, f"q3_dom_orthoH{sfx}.tif")
    rio.write_dom(out, dom, spec["left"], spec["top"], spec["res_x"], spec["res_y"])

    LON, LAT = dom_pixel_centers(spec)
    line, samp = rpc.forward(LAT, LON, dem.interp(LON, LAT))
    m = valid_mask(line, samp, src.shape)
    print(f"[{img}] 有效像素 {m.sum()}/{m.size} ({100*m.mean():.1f}%) -> {out} (+ .tfw/.prj)")


def main():
    os.makedirs(OUT, exist_ok=True)
    dem_tif, dem_tfw = _dem_files()
    dem = DEM(dem_tif, dem_tfw)
    print(f"DEM {dem.data.shape} 正常高范围 [{dem.data.min():.2f},{dem.data.max():.2f}] m")
    for img in IMAGES:
        run(img, dem)


if __name__ == "__main__":
    main()
