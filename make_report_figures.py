# -*- coding: utf-8 -*-
"""生成两份报告所需图件（中文字体 simhei）。输出到分享包 报告/figs/。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parent
SUITE = ROOT / "SatPhoto-pro"
OUTR = SUITE / "suite_outputs"
TC = ROOT / "全流程测试用例"
# 兼容两种布局：分享包内（根/报告/figs）与开发布局（根/SatPhoto-Pro-share/报告/figs）
FIGS = (ROOT / "报告" / "figs") if (ROOT / "报告").is_dir() else (ROOT / "SatPhoto-Pro-share" / "报告" / "figs")
FIGS.mkdir(parents=True, exist_ok=True)

# 中文字体
for fp in (r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\msyh.ttc"):
    if Path(fp).is_file():
        try:
            font_manager.fontManager.addfont(fp)
        except Exception:
            pass
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

import tifffile


def gray(a):
    a = np.asarray(a)
    if a.ndim == 3:
        a = a[..., :3].mean(axis=2)
    return a.astype(np.float32)


def st8(a):
    a = gray(a)
    v = a[np.isfinite(a) & (a > 0)]
    if v.size == 0:
        return np.zeros_like(a, np.uint8)
    lo, hi = np.percentile(v, [2, 98])
    return np.clip((a - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)


def overlay(a, b):
    ga, gb = st8(a), st8(b)
    h = min(ga.shape[0], gb.shape[0]); w = min(ga.shape[1], gb.shape[1])
    ov = np.zeros((h, w, 3), np.uint8)
    ov[..., 0] = ga[:h, :w]; ov[..., 1] = gb[:h, :w]
    return ov


# ---- 图1：测试用例 DOM 校正前后 vs 真值（011 / 007）----
def fig_dom():
    pairs = [("JAX_Tile_163_RGB_011", "9.09", "0.81"), ("JAX_Tile_163_RGB_007", "9.24", "0.71")]
    fig, ax = plt.subplots(2, 3, figsize=(13.5, 9), dpi=140)
    for r, (stem, sb, sa) in enumerate(pairs):
        ref = tifffile.imread(TC / "参考真值数据" / "DOM" / f"{stem}_DOM.tif")
        orig = tifffile.imread(OUTR / "pipeline" / "03_dom" / f"{stem}_DOM_original.tif")
        corr = tifffile.imread(OUTR / "pipeline" / "03_dom" / f"{stem}_DOM_corrected.tif")
        ax[r, 0].imshow(overlay(ref, orig)); ax[r, 0].set_title(f"{stem[-3:]} 原始RPC ⊕ 真值\n残余平移≈{sb}px（红绿分离=错位）")
        ax[r, 1].imshow(overlay(ref, corr)); ax[r, 1].set_title(f"{stem[-3:]} 校正后RPC ⊕ 真值\n残余平移≈{sa}px（趋于灰=重合）")
        ax[r, 2].imshow(st8(corr), cmap="gray"); ax[r, 2].set_title(f"{stem[-3:]} 校正后 DOM 成果")
        for c in range(3):
            ax[r, c].axis("off")
    fig.suptitle("测试用例 Task1 DOM：不准确 RPC → 校正后 RPC（红=真值, 绿=本方成果）", fontsize=14, y=0.995)
    fig.tight_layout()
    fig.savefig(FIGS / "fig_testcase_dom.png", bbox_inches="tight")
    plt.close(fig)
    print("fig_testcase_dom.png")


# ---- 图2：测试用例 DSM 成果 vs 真值 + 误差 ----
def fig_dsm():
    truth = TC / "参考真值数据" / "JAX_Tile_163_RGB_011_vs_JAX_Tile_163_RGB_007" / "JAX_Tile_163_RGB_011_vs_JAX_Tile_163_RGB_007_DSM.tif"
    my = OUTR / "task5" / "dsm" / "dsm_tin_pure_masked.tif"
    err = OUTR / "task5" / "dsm" / "dsm_tin_pure_masked_error.tif"
    nod = -99999.0

    def load(p):
        a = tifffile.imread(p).astype(np.float32)
        if a.ndim == 3:
            a = a[..., 0]
        return np.ma.masked_where((a <= nod + 1) | ~np.isfinite(a), a)

    tdsm, mdsm = load(truth), load(my)
    vmin = float(np.nanpercentile(tdsm.compressed(), 2))
    vmax = float(np.nanpercentile(tdsm.compressed(), 98))
    fig, ax = plt.subplots(1, 3, figsize=(15, 5.2), dpi=140)
    im0 = ax[0].imshow(mdsm, cmap="terrain", vmin=vmin, vmax=vmax); ax[0].set_title("本方 DSM（Pure TIN）")
    im1 = ax[1].imshow(tdsm, cmap="terrain", vmin=vmin, vmax=vmax); ax[1].set_title("老师参考 DSM（真值）")
    fig.colorbar(im1, ax=[ax[0], ax[1]], shrink=0.8, label="椭球高 (m)")
    if err.is_file():
        e = load(err)
        im2 = ax[2].imshow(e, cmap="RdBu_r", vmin=-15, vmax=15); ax[2].set_title("高程误差 (本方 − 真值)")
        fig.colorbar(im2, ax=ax[2], shrink=0.8, label="误差 (m)")
    for a in ax:
        a.axis("off")
    fig.suptitle("测试用例 Task5 DSM：Pure TIN RMSE ≈ 4.84 m（vs 老师真值）", fontsize=14)
    fig.savefig(FIGS / "fig_testcase_dsm.png", bbox_inches="tight")
    plt.close(fig)
    print("fig_testcase_dsm.png")


# ---- 图3：补充数据 BWD/FWD 正射底图对比（中文字体重绘）----
def fig_supp():
    sd = OUTR / "supplementary"
    bwd = tifffile.imread(sd / "BWD_DOM_srtm.tif")
    fwd = tifffile.imread(sd / "FWD_DOM_srtm.tif")
    fig, ax = plt.subplots(1, 3, figsize=(16, 5.6), dpi=140)
    ax[0].imshow(st8(bwd), cmap="gray"); ax[0].set_title("BWD 正射底图（SRTM 作 DEM）")
    ax[1].imshow(st8(fwd), cmap="gray"); ax[1].set_title("FWD 正射 DOM（SRTM 作 DEM）")
    ax[2].imshow(overlay(bwd, fwd)); ax[2].set_title("叠加（红 BWD / 绿 FWD）残余≈3.6px")
    for a in ax:
        a.axis("off")
    fig.suptitle("补充数据：用 SRTM 把 BWD/FWD 正射到同一重叠瓦片（广州 N23/E113）", fontsize=14)
    fig.tight_layout()
    fig.savefig(FIGS / "fig_supp_dom.png", bbox_inches="tight")
    plt.close(fig)
    print("fig_supp_dom.png")


# ---- 图4：全流程数据流向图 ----
def fig_flow():
    fig, ax = plt.subplots(figsize=(13, 5.4), dpi=140)
    ax.axis("off")
    def box(x, y, w, h, text, fc):
        ax.add_patch(plt.Rectangle((x, y), w, h, fc=fc, ec="#333", lw=1.5, zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=11, zorder=3)
    def arrow(x0, y0, x1, y1):
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(arrowstyle="-|>", color="#c0392b", lw=2), zorder=1)
    box(0.0, 0.42, 0.17, 0.16, "不准确 RPC\n立体像对+控制点", "#fdebd0")
    box(0.22, 0.42, 0.16, 0.16, "Task2\n控制点/RPC校正", "#d6eaf8")
    box(0.44, 0.70, 0.16, 0.16, "Task1\n正射 → DOM", "#d5f5e3")
    box(0.44, 0.14, 0.16, 0.16, "Task3\n核线纠正", "#d5f5e3")
    box(0.65, 0.14, 0.15, 0.16, "Task4\n密集匹配", "#d5f5e3")
    box(0.84, 0.14, 0.15, 0.16, "Task5\n点云→DSM", "#d5f5e3")
    box(0.84, 0.70, 0.15, 0.16, "准确 DOM", "#fadbd8")
    box(0.84, 0.42, 0.15, 0.16, "准确 DSM", "#fadbd8")
    arrow(0.17, 0.50, 0.22, 0.50)
    arrow(0.38, 0.52, 0.44, 0.74)   # ->task1
    arrow(0.38, 0.50, 0.44, 0.26)   # ->task3
    arrow(0.60, 0.78, 0.84, 0.78)   # task1->dom
    arrow(0.60, 0.22, 0.65, 0.22)   # task3->task4
    arrow(0.80, 0.22, 0.84, 0.22)   # task4->task5
    arrow(0.915, 0.30, 0.915, 0.42) # task5->dsm
    ax.text(0.5, 0.04, "关键：Task2 校正后的 RPC 经『同名 .rpb 暂存』传播给下游 Task1/Task3，"
            "整条链真正实现『不准确 RPC → 准确产品』", ha="center", fontsize=10, color="#555")
    ax.set_xlim(0, 1); ax.set_ylim(0, 0.95)
    fig.suptitle("SatPhoto-Pro 全流程数据流向（生产顺序：Task2 先行，而非编号 1→5）", fontsize=13)
    fig.savefig(FIGS / "fig_pipeline_flow.png", bbox_inches="tight")
    plt.close(fig)
    print("fig_pipeline_flow.png")


if __name__ == "__main__":
    fig_flow()
    fig_dom()
    fig_dsm()
    fig_supp()
    print("ALL FIGURES →", FIGS)
