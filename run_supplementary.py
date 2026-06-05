# -*- coding: utf-8 -*-
"""补充数据赛道实验（FWD/BWD，无底图）。

老师提示：该区域没给底图，可自找开源底图，也可把 BWD 正射出来当底图；
n23_e113_1arc_v3.tif（SRTM）作为正射时的 DEM。本脚本据此完成：

  1. 把 FWD/BWD 的 RPC00B 文本转为 .rpb（复用课程全部既有 RPC 流程）；
  2. 用 SRTM 作 DEM，对 BWD、FWD 的重叠中心区做"开窗正射"（避免整幅 2.8GB 入内存），
     得到带地理参考的 DOM —— 其中 BWD 的 DOM 即作为"自制参考底图"；
  3. 评估 BWD 底图与 FWD-DOM 的相互配准（相位相关 + SIFT/RANSAC），
     量化两幅影像 RPC 的相对一致性 —— 这正是控制点匹配(Task2)能否进行的前提。

无真值，故采用"相对/自洽"评估，并以 SRTM 做合理性核验。
注意：补充数据与测试用例属于两条独立数据赛道，输出互不混用。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
SUITE = ROOT / "SatPhoto-pro"
for p in (SUITE, SUITE / "task1_code"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SUPP = ROOT / "卫星摄影测量-补充数据"
OUT = SUITE / "suite_outputs" / "supplementary"
SRTM = SUPP / "n23_e113_1arc_v3.tif"


def _stretch_uint8(arr: np.ndarray) -> np.ndarray:
    """按 2%/98% 分位线性拉伸到 uint8，便于查看（忽略 0/无效值）。"""
    v = arr[np.isfinite(arr) & (arr > 0)]
    if v.size == 0:
        return np.zeros_like(arr, dtype=np.uint8)
    lo, hi = np.percentile(v, [2, 98])
    if hi <= lo:
        hi = lo + 1
    out = np.clip((arr - lo) / (hi - lo) * 255.0, 0, 255)
    out[~np.isfinite(arr)] = 0
    return out.astype(np.uint8)


def windowed_ortho(rpb: Path, tif: Path, lon0, lon1, lat0, lat1, res, geoid_n=0.0):
    """开窗间接法正射：输出网格→SRTM 取高→RPC 正解→只读所需影像窗口→双线性重采样。"""
    import rasterio
    from rasterio.windows import Window
    from scipy.ndimage import map_coordinates
    import rpc as t1rpc

    W = int(round((lon1 - lon0) / res))
    H = int(round((lat1 - lat0) / res))
    cols = np.arange(W); rows = np.arange(H)
    lon = lon0 + (cols + 0.5) * res
    lat = lat1 - (rows + 0.5) * res
    LON, LAT = np.meshgrid(lon, lat)

    with rasterio.open(SRTM) as s:
        srtm = s.read(1).astype(np.float64)
        t = s.transform
    cs = (LON - t.c) / t.a
    rs = (LAT - t.f) / t.e
    Z = map_coordinates(srtm, [rs.ravel(), cs.ravel()], order=1, mode="nearest").reshape(LON.shape)
    Z = Z + geoid_n

    model = t1rpc.RPCModel(str(rpb))
    line, samp = model.forward(LAT, LON, Z)
    fin = np.isfinite(line) & np.isfinite(samp)
    r0 = max(0, int(np.floor(np.nanmin(line[fin]))) - 2)
    c0 = max(0, int(np.floor(np.nanmin(samp[fin]))) - 2)
    with rasterio.open(tif) as src:
        r1 = min(src.height, int(np.ceil(np.nanmax(line[fin]))) + 2)
        c1 = min(src.width, int(np.ceil(np.nanmax(samp[fin]))) + 2)
        win = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(np.float32)
    dom = map_coordinates(win, [(line - r0).ravel(), (samp - c0).ravel()],
                          order=1, mode="constant", cval=0).reshape(LON.shape)
    spec = {"left": lon0, "top": lat1, "res_x": res, "res_y": res, "width": W, "height": H,
            "img_window": [int(c0), int(r0), int(c1), int(r1)],
            "srtm_min": float(np.nanmin(Z)), "srtm_max": float(np.nanmax(Z))}
    return dom, spec


def _phase_shift(a, b):
    import cv2
    a = _stretch_uint8(a).astype(np.float32); b = _stretch_uint8(b).astype(np.float32)
    m = (a > 0) & (b > 0)
    if m.sum() < 0.05 * a.size:
        return float("nan"), float("nan"), float("nan")
    a = np.where(m, a, 0); b = np.where(m, b, 0)
    win = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), _ = cv2.phaseCorrelate(a, b, win)
    return float(dx), float(dy), float(np.hypot(dx, dy))


def _sift_match(a, b):
    import cv2
    ga, gb = _stretch_uint8(a), _stretch_uint8(b)
    sift = cv2.SIFT_create(nfeatures=4000)
    ka, da = sift.detectAndCompute(ga, None)
    kb, db = sift.detectAndCompute(gb, None)
    if da is None or db is None or len(ka) < 8 or len(kb) < 8:
        return {"keypoints_a": len(ka or []), "keypoints_b": len(kb or []), "good": 0, "inliers": 0}
    bf = cv2.BFMatcher(cv2.NORM_L2)
    knn = bf.knnMatch(da, db, k=2)
    good = [m for m, n in knn if m.distance < 0.75 * n.distance]
    inliers = 0
    shift = (float("nan"), float("nan"))
    if len(good) >= 8:
        pa = np.float32([ka[m.queryIdx].pt for m in good])
        pb = np.float32([kb[m.trainIdx].pt for m in good])
        Mmat, mask = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=3.0)
        if mask is not None:
            inliers = int(mask.sum())
            inl = mask.ravel().astype(bool)
            d = pb[inl] - pa[inl]
            shift = (float(np.median(d[:, 0])), float(np.median(d[:, 1])))
    return {"keypoints_a": len(ka), "keypoints_b": len(kb), "good": len(good),
            "inliers": inliers, "median_shift_px": shift,
            "shift_mag_px": float(np.hypot(*shift)) if np.isfinite(shift[0]) else float("nan")}


def main() -> int:
    import rasterio  # noqa
    from photogrammetry_suite.pipeline.supp_rpc import txt_to_rpb
    import raster_io as rio

    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    result = {"track": "supplementary", "srtm": str(SRTM)}

    # 1. RPC txt -> rpb
    rpb = {}
    for name in ("BWD", "FWD"):
        rpb[name] = txt_to_rpb(SUPP / f"{name}_rpc.txt", OUT / f"{name}.rpb")
    result["rpb"] = {k: str(v) for k, v in rpb.items()}
    print(f"[1] RPC 文本→.rpb 完成: {rpb['BWD'].name}, {rpb['FWD'].name}")

    # 2. 选重叠中心瓦片，开窗正射（SRTM 作 DEM）
    res = 2.0e-5  # ~2.2 m
    lon0, lon1, lat0, lat1 = 113.470, 113.530, 23.100, 23.160  # 重叠中心 ~6.1km 方块
    result["tile"] = {"lon0": lon0, "lon1": lon1, "lat0": lat0, "lat1": lat1, "res_deg": res}
    print(f"[2] 开窗正射瓦片 lon[{lon0},{lon1}] lat[{lat0},{lat1}] res≈{res*111000:.1f}m (SRTM 作 DEM)")
    doms = {}
    for name in ("BWD", "FWD"):
        dom, spec = windowed_ortho(rpb[name], SUPP / f"{name}.tif", lon0, lon1, lat0, lat1, res)
        doms[name] = dom
        rio.write_dom(str(OUT / f"{name}_DOM_srtm.tif"), _stretch_uint8(dom),
                      spec["left"], spec["top"], spec["res_x"], spec["res_y"])
        result.setdefault("dom", {})[name] = {**spec, "out": str(OUT / f"{name}_DOM_srtm.tif")}
        print(f"    {name}: DOM {spec['width']}x{spec['height']}, 取窗 {spec['img_window']}, "
              f"SRTM 高程 {spec['srtm_min']:.0f}~{spec['srtm_max']:.0f} m")

    # 3. 相互配准评估（BWD 底图 vs FWD-DOM）
    print("[3] BWD 底图 vs FWD-DOM 相互配准")
    dx, dy, mag = _phase_shift(doms["BWD"], doms["FWD"])
    sift = _sift_match(doms["BWD"], doms["FWD"])
    result["registration"] = {"phase": {"dx": dx, "dy": dy, "shift_px": mag, "shift_m": mag * res * 111000},
                              "sift": sift}
    print(f"    相位相关残余平移 = {mag:.2f} px (≈{mag*res*111000:.2f} m)")
    print(f"    SIFT: keypoints {sift['keypoints_a']}/{sift['keypoints_b']}, good {sift['good']}, "
          f"RANSAC 内点 {sift['inliers']}, 中值平移 {sift.get('shift_mag_px', float('nan')):.2f} px")

    # 4. 对比图
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 3, figsize=(16, 5.6), dpi=140)
        ax[0].imshow(_stretch_uint8(doms["BWD"]), cmap="gray"); ax[0].set_title("BWD 正射底图 (SRTM as DEM)")
        ax[1].imshow(_stretch_uint8(doms["FWD"]), cmap="gray"); ax[1].set_title("FWD 正射 DOM (SRTM as DEM)")
        ov = np.zeros((*doms["BWD"].shape, 3), np.uint8)
        ov[..., 0] = _stretch_uint8(doms["BWD"]); ov[..., 1] = _stretch_uint8(doms["FWD"])
        ax[2].imshow(ov); ax[2].set_title(f"叠加 (红BWD/绿FWD) 残余{mag:.1f}px")
        for a in ax:
            a.axis("off")
        fig.suptitle("补充数据：BWD/FWD 用 SRTM 正射的重叠瓦片", fontsize=13)
        fig.tight_layout()
        fig.savefig(OUT / "supp_dom_compare.png", bbox_inches="tight")
        plt.close(fig)
        result["figure"] = str(OUT / "supp_dom_compare.png")
        print(f"[4] 对比图 → {OUT / 'supp_dom_compare.png'}")
    except Exception as exc:  # noqa: BLE001
        print(f"[4] 绘图跳过: {exc}")

    result["elapsed_sec"] = round(time.time() - t0, 2)
    (OUT / "supplementary_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n完成，用时 {result['elapsed_sec']}s；结果 → {OUT / 'supplementary_result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
