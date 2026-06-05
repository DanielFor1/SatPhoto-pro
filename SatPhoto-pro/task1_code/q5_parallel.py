# -*- coding: utf-8 -*-
"""第5题（挑战题，5分）：用平行投影模型近似 RPC 加速正射纠正。

用第4题数据（椭球高 DEM）。流程：
  1) RPC 构建虚拟控制格网 -> 最小二乘拟合 8 参数平行投影(仿射)模型；
  2) 分别用 RPC 与 平行投影模型 做坐标解算，计时对比加速倍率；
  3) 比较两者像点坐标残差与最终 DOM 差异，确认"无显著差异"。
"""
import os
import time
import numpy as np
from rpc import RPCModel
from ortho import orthorectify, dom_pixel_centers, valid_mask
from dem import DEM
from geoid_egm2008 import EGM2008Geoid
from parallel_model import ParallelProjection
import raster_io as rio

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "实习数据", "task1")
OUT = os.path.join(ROOT, "results")
IMG = "JAX_Tile_163_RGB_001"
DEM_TIF = os.path.join(DATA, "DEM", "USGS_13_n31w082_20221103_clip.tif")
DEM_TFW = os.path.join(DATA, "DEM", "USGS_13_n31w082_20221103_clip.tfw")
GEOID_CANDIDATES = [
    os.path.join(ROOT, "geoid_data", "geoids", "egm2008-5.pgm"),
    os.path.join(ROOT, "EGM2008 - 1'.pgm"),
]
GEOID = next((p for p in GEOID_CANDIDATES if os.path.isfile(p)), GEOID_CANDIDATES[0])


def timeit(fn, repeats=5):
    fn()  # 预热
    t0 = time.perf_counter()
    for _ in range(repeats):
        fn()
    return (time.perf_counter() - t0) / repeats


def main():
    os.makedirs(OUT, exist_ok=True)
    rpc = RPCModel(os.path.join(DATA, "影像", IMG + ".rpb"))
    src = rio.read_tif(os.path.join(DATA, "影像", IMG + ".tif"))
    spec = rio.load_dom_spec(os.path.join(DATA, "正射影像范围.csv"), IMG)
    dem = DEM(DEM_TIF, DEM_TFW)
    geoid = EGM2008Geoid(GEOID)

    def ellip_surface(LON, LAT):
        return dem.interp(LON, LAT) + geoid.undulation(LON, LAT)

    # DOM 经纬度与椭球高高程面
    LON, LAT = dom_pixel_centers(spec)
    Z = ellip_surface(LON, LAT)

    # 1) 拟合平行投影模型：范围取 DOM 经纬度 + 实际椭球高范围
    par = ParallelProjection(rpc).fit(
        lon_rng=(spec["left"], spec["right"]),
        lat_rng=(spec["bottom"], spec["top"]),
        h_rng=(float(Z.min()), float(Z.max())),
        n_xy=21, n_h=5)
    print(f"平行投影模型虚拟控制点拟合残差 RMSE: line={par.fit_rmse[0]:.4f}, "
          f"sample={par.fit_rmse[1]:.4f} 像素")
    print("仿射参数 a(sample)=", np.array2string(par.a, precision=4))
    print("仿射参数 b(line)  =", np.array2string(par.b, precision=4))

    # 2) 坐标解算计时对比
    t_rpc = timeit(lambda: rpc.forward(LAT, LON, Z), repeats=5)
    t_par = timeit(lambda: par.forward(LAT, LON, Z), repeats=5)
    speedup = t_rpc / t_par
    npx = LON.size
    print(f"\n=== 坐标解算计时（{npx} 像素，5 次平均）===")
    print(f"RPC 正解      : {t_rpc*1000:.2f} ms")
    print(f"平行投影模型  : {t_par*1000:.2f} ms")
    print(f"加速倍率      : {speedup:.2f} x")

    # 3) 像点坐标残差
    l_rpc, s_rpc = rpc.forward(LAT, LON, Z)
    l_par, s_par = par.forward(LAT, LON, Z)
    dl, ds = l_par - l_rpc, s_par - s_rpc
    rmse_l = float(np.sqrt(np.mean(dl ** 2)))
    rmse_s = float(np.sqrt(np.mean(ds ** 2)))
    maxerr = float(np.max(np.sqrt(dl ** 2 + ds ** 2)))
    print(f"\n=== 平行投影 vs RPC 像点坐标差异（整幅 DOM）===")
    print(f"RMSE line={rmse_l:.4f}  sample={rmse_s:.4f}  最大点位误差={maxerr:.4f} 像素")

    # 生成平行投影 DOM 并与 RPC(第4题) DOM 比较
    dom_par = orthorectify(par, src, spec, height_surface=ellip_surface)
    out = os.path.join(OUT, "q5_dom_parallel.tif")
    rio.write_dom(out, dom_par, spec["left"], spec["top"], spec["res_x"], spec["res_y"])

    import tifffile
    dom_rpc = tifffile.imread(os.path.join(OUT, "q4_dom_ellipH.tif"))
    m = valid_mask(l_rpc, s_rpc, src.shape)
    diff = dom_par.astype(np.float64) - dom_rpc.astype(np.float64)
    rmse_pix = float(np.sqrt(np.mean(diff[m] ** 2)))
    print(f"\nDOM 灰度差异(有效区) RMSE = {rmse_pix:.3f} (0-255)")

    # 写计时报告
    with open(os.path.join(OUT, "q5_timing.txt"), "w", encoding="utf-8") as f:
        f.write("平行投影模型近似 RPC 加速正射 —— 实验结果\n")
        f.write(f"DOM 尺寸: {spec['height']} x {spec['width']} = {npx} 像素\n")
        f.write(f"虚拟控制点拟合残差 RMSE: line={par.fit_rmse[0]:.4f}, sample={par.fit_rmse[1]:.4f} 像素\n")
        f.write(f"RPC 正解坐标解算耗时   : {t_rpc*1000:.2f} ms\n")
        f.write(f"平行投影模型坐标解算耗时: {t_par*1000:.2f} ms\n")
        f.write(f"加速倍率: {speedup:.2f} x\n")
        f.write(f"像点坐标差异 RMSE: line={rmse_l:.4f}, sample={rmse_s:.4f}, 最大={maxerr:.4f} 像素\n")
        f.write(f"DOM 灰度差异(有效区) RMSE: {rmse_pix:.3f} (0-255)\n")
    print(f"\n已输出: {out}  与  {os.path.join(OUT,'q5_timing.txt')}")


if __name__ == "__main__":
    main()
