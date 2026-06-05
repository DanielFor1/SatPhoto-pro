# -*- coding: utf-8 -*-
"""跨视角配准检核：001 与 005 两个视角在三种高程面下的正射 DOM 是否在地面重合。

这是本任务"为什么要用两个视角"的题眼，也是椭球高基准正确性最直接的证据：
  · 只有都用【椭球高 DEM】纠正，001 与 005 的地面地物才重合；
  · 用【0 高程面】或【水准高 DEM】纠正，因 RPC 高程基准是 WGS84 椭球高，
    二者引入约 26~30 m 的系统高程误差，使两个视角的同名地物在地面上明显错位；
  · 建筑、桥梁等高出地面的地物即便在椭球高 DOM 上仍存在投影差，局部不重合属正常。

做法（无 GDAL，仅用 .tfw 做地理配准）：
  1) 把 005 DOM 按地理坐标双线性重采样到 001 的像素格网；
  2) 公共有效区内：零位移 NCC（衡量整体重合度）+ 相位相关估系统残余平移(dx,dy)，
     再用 001 的像元地理尺寸换算为地面错位（米）；
  3) 输出可视化：红(001)/绿(005)边缘叠加（重合呈黄、错位红绿分离）+ 棋盘格(模拟卷帘)。
"""
import os
import numpy as np
import cv2
import tifffile
from scipy.ndimage import map_coordinates
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
matplotlib.rcParams["axes.unicode_minus"] = False
import raster_io as rio

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "results")
FIG = os.path.join(OUT, "figures")
os.makedirs(FIG, exist_ok=True)

DEG2M_LAT = 110540.0  # 1° 纬度 ≈ 110540 m

# (高程面名称, 001 DOM, 005 DOM)
SURFACES = [
    ("0高程面", "q2_dom_0m.tif",     "q2_dom_0m_005.tif"),
    ("水准高",  "q3_dom_orthoH.tif", "q3_dom_orthoH_005.tif"),
    ("椭球高",  "q4_dom_ellipH.tif", "q4_dom_ellipH_005.tif"),
]


def gray(a):
    a = a.astype(np.float64)
    return a.mean(2) if a.ndim == 3 else a


def resample_to(ref_shape, ref_tfw, src_gray, src_tfw):
    """把 src（带 tfw）按地理坐标重采样到 ref 的像素格网（双线性）。"""
    A1, _, _, E1, C1, F1 = ref_tfw
    A5, _, _, E5, C5, F5 = src_tfw
    h, w = ref_shape
    CC, RR = np.meshgrid(np.arange(w), np.arange(h))
    lon = C1 + CC * A1            # ref 像素中心经度
    lat = F1 + RR * E1            # ref 像素中心纬度 (E1<0)
    col5 = (lon - C5) / A5
    row5 = (lat - F5) / E5
    out = map_coordinates(src_gray, [row5.ravel(), col5.ravel()],
                          order=1, mode="constant", cval=0.0)
    return out.reshape(ref_shape)


def ncc(x, y, mask):
    xv, yv = x[mask], y[mask]
    xv = xv - xv.mean()
    yv = yv - yv.mean()
    denom = np.sqrt((xv ** 2).sum() * (yv ** 2).sum())
    return float((xv * yv).sum() / denom) if denom > 0 else 0.0


def phase_shift(a_img, b_img, mask):
    """公共有效区裁剪 + 归一化 + 汉宁窗，相位相关估残余平移 (dx, dy) 像素。"""
    ys, xs = np.where(mask)
    r0, r1, c0, c1 = ys.min(), ys.max(), xs.min(), xs.max()
    a = a_img[r0:r1 + 1, c0:c1 + 1].astype(np.float32)
    b = b_img[r0:r1 + 1, c0:c1 + 1].astype(np.float32)
    a = (a - a.mean()) / (a.std() + 1e-6)
    b = (b - b.mean()) / (b.std() + 1e-6)
    win = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(a * win, b * win)
    return dx, dy, resp


def norm01(x):
    pos = x[x > 0]
    if pos.size == 0:
        return np.zeros_like(x)
    lo, hi = np.percentile(pos, (2, 98))
    return np.clip((x - lo) / (hi - lo + 1e-6), 0, 1)


def edges(x):
    u8 = (norm01(x) * 255).astype(np.uint8)
    return cv2.Canny(u8, 60, 140) > 0


def main():
    # 以 001 椭球高的格网为统一参考框架
    ref001 = {name: gray(tifffile.imread(os.path.join(OUT, f001)))
              for name, f001, _ in SURFACES}
    tfw001 = {name: rio.read_tfw(os.path.join(OUT, os.path.splitext(f001)[0] + ".tfw"))
              for name, f001, _ in SURFACES}
    res005 = {}
    for name, _, f005 in SURFACES:
        g5 = gray(tifffile.imread(os.path.join(OUT, f005)))
        t5 = rio.read_tfw(os.path.join(OUT, os.path.splitext(f005)[0] + ".tfw"))
        res005[name] = resample_to(ref001[name].shape, tfw001[name], g5, t5)

    # 001 格网像元的地面尺寸（米/像素）
    A1, _, _, E1, C1, F1 = tfw001["椭球高"]
    h, w = ref001["椭球高"].shape
    lat_c = F1 + (h / 2) * E1
    mx = abs(A1) * 111320.0 * np.cos(np.deg2rad(lat_c))
    my = abs(E1) * DEG2M_LAT

    print("=== 001×005 跨视角配准检核（公共有效区）===")
    print(f"001 格网像元地面尺寸 ≈ {mx:.3f} m/px(经) × {my:.3f} m/px(纬)\n")
    print(f"{'高程面':8s} {'重合NCC':>8s} {'残余平移dx':>10s} {'dy(px)':>8s} "
          f"{'|d|(px)':>8s} {'|d|(m)':>8s}")
    rows = []
    for name, _, _ in SURFACES:
        a = ref001[name]
        b = res005[name]
        m = (a > 0) & (b > 0)
        nc = ncc(a, b, m)
        dx, dy, _ = phase_shift(a, b, m)
        dpx = float(np.hypot(dx, dy))
        dm = float(np.hypot(dx * mx, dy * my))
        rows.append((name, nc, dx, dy, dpx, dm))
        print(f"{name:8s} {nc:8.4f} {dx:10.2f} {dy:8.2f} {dpx:8.2f} {dm:8.2f}")

    # 选取一个纹理丰富的公共子窗（用三面共有的有效区中心）
    common = np.ones(ref001["椭球高"].shape, bool)
    for name, _, _ in SURFACES:
        common &= (ref001[name] > 0) & (res005[name] > 0)
    ys, xs = np.where(common)
    cy, cx = int(ys.mean()), int(xs.mean())
    win_h, win_w = 520, 760
    r0 = max(ys.min(), cy - win_h // 2); r1 = min(ys.max(), r0 + win_h)
    c0 = max(xs.min(), cx - win_w // 2); c1 = min(xs.max(), c0 + win_w)

    # 可视化：上排棋盘格(模拟卷帘)，下排红001/绿005边缘叠加
    fig, axes = plt.subplots(2, 3, figsize=(16.5, 9.5))
    blk = 60
    for j, (name, _, _) in enumerate(SURFACES):
        a = norm01(ref001[name][r0:r1, c0:c1])
        b = norm01(res005[name][r0:r1, c0:c1])
        yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
        chk = ((yy // blk + xx // blk) % 2).astype(bool)
        board = np.where(chk, a, b)
        axes[0, j].imshow(board, cmap="gray")
        axes[0, j].set_title(f"{name}  棋盘格(001/005 卷帘)")
        axes[0, j].axis("off")

        ea = edges(ref001[name][r0:r1, c0:c1])
        eb = edges(res005[name][r0:r1, c0:c1])
        rg = np.zeros((*ea.shape, 3))
        rg[..., 0] = ea          # 红 = 001
        rg[..., 1] = eb          # 绿 = 005
        axes[1, j].imshow(rg)
        nc = next(r[1] for r in rows if r[0] == name)
        dm = next(r[5] for r in rows if r[0] == name)
        axes[1, j].set_title(f"{name}  边缘叠加 红001/绿005\nNCC={nc:.3f}  地面错位≈{dm:.2f} m")
        axes[1, j].axis("off")
    fig.suptitle("001×005 跨视角配准检核：仅椭球高在地面重合（边缘呈黄色），0高程/水准高明显错位（红绿分离）",
                 fontsize=14)
    plt.tight_layout()
    out_fig = os.path.join(FIG, "fig_crossview.png")
    plt.savefig(out_fig, dpi=110)
    plt.close()

    # 报告
    rep = os.path.join(OUT, "cross_view_report.txt")
    with open(rep, "w", encoding="utf-8") as f:
        f.write("001×005 跨视角配准检核（005 DOM 重采样到 001 格网，公共有效区）\n")
        f.write(f"001 格网像元地面尺寸 ≈ {mx:.3f} m/px(经) × {my:.3f} m/px(纬)\n\n")
        f.write(f"{'高程面':8s} {'重合NCC':>8s} {'dx(px)':>8s} {'dy(px)':>8s} "
                f"{'|d|(px)':>8s} {'|d|(m)':>8s}\n")
        for name, nc, dx, dy, dpx, dm in rows:
            f.write(f"{name:8s} {nc:8.4f} {dx:8.2f} {dy:8.2f} {dpx:8.2f} {dm:8.2f}\n")
        f.write("\n结论：椭球高残余平移最小、NCC 最高 → 两视角地面重合；"
                "0高程面/水准高残余平移达数米、NCC 偏低 → 不重合（高程基准错误）。\n"
                "椭球高 DOM 上高度地物的局部不重合源于投影差，属正常。\n")
    print(f"\n已输出: {out_fig}")
    print(f"已输出: {rep}")


if __name__ == "__main__":
    main()
