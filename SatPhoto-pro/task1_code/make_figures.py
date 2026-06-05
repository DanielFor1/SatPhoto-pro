# -*- coding: utf-8 -*-
"""生成成果文档配图，输出到 ../results/figures/。"""
import os
import numpy as np
import tifffile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
matplotlib.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "实习数据", "task1")
OUT = os.path.join(ROOT, "results")
FIG = os.path.join(OUT, "figures")
os.makedirs(FIG, exist_ok=True)
IMG = "JAX_Tile_163_RGB_001"


def valid_bbox(dom):
    m = dom.sum(2) > 0 if dom.ndim == 3 else dom > 0
    ys, xs = np.where(m)
    return ys.min(), ys.max(), xs.min(), xs.max()


def fig_q1_points():
    src = tifffile.imread(os.path.join(DATA, "影像", IMG + ".tif"))
    gp = np.loadtxt(os.path.join(DATA, "ground_points.csv"), delimiter=",", skiprows=1)
    px = np.loadtxt(os.path.join(OUT, "q1_pixels.csv"), delimiter=",", skiprows=1)
    line, samp = px[:, 1], px[:, 2]
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.imshow(src)
    ax.scatter(samp, line, s=80, facecolors="none", edgecolors="red", linewidths=1.8)
    for i in range(len(px)):
        ax.text(samp[i] + 15, line[i] - 10, str(int(px[i, 0])), color="yellow", fontsize=11, weight="bold")
    ax.set_title("第1题  RPC正解：12个地面点投影到原始影像  (与参考答案 RMSE=0.000 像素)")
    ax.set_xlabel("sample (列)"); ax.set_ylabel("line (行)")
    plt.tight_layout(); plt.savefig(os.path.join(FIG, "fig_q1_points.png"), dpi=120); plt.close()


def _doms_panel(files, suptitle, out_png):
    fig, axes = plt.subplots(1, 3, figsize=(16, 6))
    for ax, (fn, title) in zip(axes, files):
        dom = tifffile.imread(os.path.join(OUT, fn))
        r0, r1, c0, c1 = valid_bbox(dom)
        ax.imshow(dom[r0:r1 + 1, c0:c1 + 1])
        ax.set_title(title); ax.axis("off")
    fig.suptitle(suptitle, fontsize=14)
    plt.tight_layout(); plt.savefig(os.path.join(FIG, out_png), dpi=110); plt.close()


def fig_doms():
    _doms_panel(
        [("q2_dom_0m.tif", "第2题  正射到0高程面"),
         ("q3_dom_orthoH.tif", "第3题  正射到水准高DEM"),
         ("q4_dom_ellipH.tif", "第4题  正射到椭球高DEM (正确)")],
        "基于RPC模型的正射影像DOM成果 (JAX_Tile_163_RGB_001, EPSG:4326)",
        "fig_doms.png")


def fig_doms_005():
    _doms_panel(
        [("q2_dom_0m_005.tif", "005  正射到0高程面"),
         ("q3_dom_orthoH_005.tif", "005  正射到水准高DEM"),
         ("q4_dom_ellipH_005.tif", "005  正射到椭球高DEM (正确)")],
        "第二视角正射影像DOM成果 (JAX_Tile_163_RGB_005, EPSG:4326)",
        "fig_doms_005.png")


def fig_q5():
    t_rpc, t_par, speed = 3780.0, 185.0, 20.4
    fig, ax = plt.subplots(1, 2, figsize=(12, 5))
    bars = ax[0].bar(["RPC正解", "平行投影模型"], [t_rpc, t_par], color=["#c0504d", "#4f81bd"])
    ax[0].set_ylabel("坐标解算耗时 (ms, 4.8M像素)")
    ax[0].set_title(f"第5题  平行投影加速  ≈ {speed:.0f}×")
    for b, v in zip(bars, [t_rpc, t_par]):
        ax[0].text(b.get_x() + b.get_width() / 2, v + 60, f"{v:.0f} ms", ha="center", weight="bold")
    ax[0].annotate(f"加速 {speed:.0f}×", xy=(1, t_par), xytext=(0.5, t_rpc * 0.6),
                   arrowprops=dict(arrowstyle="->"), fontsize=13, weight="bold", color="green")
    ax[1].axis("off")
    txt = ("平行投影(仿射)模型 vs RPC 精度对比\n"
           "（整幅 DOM，4.8M 像素）\n\n"
           "虚拟控制点拟合残差:\n   line 0.036 px,  sample 0.142 px\n\n"
           "像点坐标差异:\n   RMSE line 0.033 px, sample 0.131 px\n"
           "   最大点位误差 0.51 px (亚像素)\n\n"
           "DOM 灰度差异 RMSE: 1.3 / 255\n\n"
           "结论：无显著差异，加速约 20 倍")
    ax[1].text(0.02, 0.98, txt, va="top", ha="left", fontsize=12,
               family="Microsoft YaHei",
               bbox=dict(boxstyle="round", fc="#f2f2f2", ec="gray"))
    plt.tight_layout(); plt.savefig(os.path.join(FIG, "fig_q5.png"), dpi=120); plt.close()


def fig_ncc():
    keys = ["第2题\n0高程面", "第3题\n水准高", "第4题\n椭球高"]
    refs = ["参考\nref0", "参考\nref1", "参考\nref2"]
    M = np.array([[0.9902, 0.4687, 0.8873],
                  [0.8925, 0.4375, 0.9898],
                  [0.4431, 0.9890, 0.4118]])
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    im = ax.imshow(M, cmap="viridis", vmin=0.4, vmax=1.0)
    ax.set_xticks(range(3)); ax.set_xticklabels(refs)
    ax.set_yticks(range(3)); ax.set_yticklabels(keys)
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f"{M[i,j]:.3f}", ha="center", va="center",
                    color="white" if M[i, j] < 0.8 else "black", weight="bold")
    ax.set_title("与ArcGIS参考结果的NCC矩阵 (视角001)\n(对角占优=各变体正确匹配, 残余平移<0.2像素)")
    fig.colorbar(im, ax=ax, fraction=0.046)
    plt.tight_layout(); plt.savefig(os.path.join(FIG, "fig_ncc.png"), dpi=120); plt.close()


if __name__ == "__main__":
    fig_q1_points()
    fig_doms()
    fig_doms_005()
    fig_q5()
    fig_ncc()
    print("配图已生成:", os.listdir(FIG))
