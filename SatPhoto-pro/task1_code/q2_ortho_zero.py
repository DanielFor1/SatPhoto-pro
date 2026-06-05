# -*- coding: utf-8 -*-
"""第2题（进阶题，10分）：用双线性内插将影像正射纠正到 0 高程面。

间接法：每个 DOM 像素中心(lon,lat) + 高程 Z=0 -> RPC 正解 -> 原图双线性重采样。
"""
import os
import numpy as np
from rpc import RPCModel
from ortho import orthorectify, dom_pixel_centers, valid_mask
import raster_io as rio

import suite_paths as sp

OUT = sp.out_dir()
IMAGES = sp.images()


def suffix_of(img):
    """001 沿用原文件名（无后缀），其余视角加 _NNN 后缀。"""
    return "" if img.endswith("001") else "_" + img[-3:]


def load_spec(img):
    spec_csv = sp.dom_spec_csv_optional()
    if spec_csv is not None:
        return rio.load_dom_spec(str(spec_csv), img)
    return rio.dom_spec_from_reference(str(sp.reference_dom()), img)


def run(img):
    sfx = suffix_of(img)
    rpc_path, tif_path = sp.image_paths(img)
    rpc = RPCModel(str(rpc_path))
    src = rio.read_tif(str(tif_path))
    spec = load_spec(img)
    print(f"[{img}] 源影像 {src.shape}, DOM {spec['height']}x{spec['width']}")

    dom = orthorectify(rpc, src, spec, height_surface=0.0)

    out = os.path.join(OUT, f"q2_dom_0m{sfx}.tif")
    rio.write_dom(out, dom, spec["left"], spec["top"], spec["res_x"], spec["res_y"])

    # 统计有效区
    LON, LAT = dom_pixel_centers(spec)
    line, samp = rpc.forward(LAT, LON, np.zeros_like(LON))
    m = valid_mask(line, samp, src.shape)
    print(f"[{img}] 有效像素 {m.sum()}/{m.size} ({100*m.mean():.1f}%) -> {out} (+ .tfw/.prj)")


def main():
    os.makedirs(OUT, exist_ok=True)
    for img in IMAGES:
        run(img)


if __name__ == "__main__":
    main()
