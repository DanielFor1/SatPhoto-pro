# -*- coding: utf-8 -*-
"""与老师参考结果（ArcGIS 生成的 DOM）做定量几何对比。

参考 DOM 与我方 DOM 网格完全一致（同一 .tfw），但参考为 16bit 且经 ArcGIS
颜色拉伸，故不直接比灰度值，而比【几何对齐】：
  · NCC（归一化互相关，对线性拉伸不敏感）—— 同一变体应接近 1；
  · 相位相关求残余平移(dx,dy) —— 几何重合则接近 0 像素。

参考文件名为 GBK，解压后乱码不可逆，故用 NCC 矩阵自动把我方 q2/q3/q4
与 3 个参考变体配对（行最大即对应变体），无需依赖文件名。
"""
import os
import glob
import numpy as np
import cv2
import tifffile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import suite_paths as sp

OUT = sp.out_dir()


def gray(a):
    a = a.astype(np.float64)
    if a.ndim == 3:
        a = a.mean(axis=2)
    return a


def ncc(x, y, mask):
    xv, yv = x[mask], y[mask]
    xv = xv - xv.mean()
    yv = yv - yv.mean()
    denom = np.sqrt((xv ** 2).sum() * (yv ** 2).sum())
    return float((xv * yv).sum() / denom) if denom > 0 else 0.0


def phase_shift(our, ref, mask):
    """在公共有效区裁剪 + 汉宁窗，用相位相关估残余平移 (dx, dy) 像素。"""
    ys, xs = np.where(mask)
    r0, r1, c0, c1 = ys.min(), ys.max(), xs.min(), xs.max()
    a = our[r0:r1 + 1, c0:c1 + 1].astype(np.float32)
    b = ref[r0:r1 + 1, c0:c1 + 1].astype(np.float32)
    # 归一化抵消拉伸
    a = (a - a.mean()) / (a.std() + 1e-6)
    b = (b - b.mean()) / (b.std() + 1e-6)
    win = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(a * win, b * win)
    return dx, dy, resp


def ref_paths(tag):
    """收集参考 DOM：优先用户指定的单文件，否则在 REF 目录按 tag 搜索。"""
    direct = sp.reference_dom()
    if direct is not None and tag in direct.name:
        return [str(direct)]
    ref_root = str(sp.ref_compare_dir())
    paths = []
    if not os.path.isdir(ref_root):
        return paths
    for root, _, files in os.walk(ref_root):
        for fn in files:
            if fn.endswith(".tif") and tag in fn:
                paths.append(os.path.join(root, fn))
    return sorted(paths)


def compare_one(tag, ours):
    """把我方某视角的 q2/q3/q4 与该视角的 3 个参考变体按 NCC 自动配对，返回报告行。"""
    refs = ref_paths(tag)
    if not refs:
        msg = (
            f"[视角 {tag}] 跳过 NCC 对比：未找到含 '{tag}' 的参考 DOM (.tif)。"
            " 请在界面指定参考底图 DOM，或忽略此步骤。"
        )
        print(f"WARNING: {msg}")
        return [msg]
    print(f"\n########## 视角 {tag}：参考 DOM {len(refs)} 个 ##########")
    our_gray = {k: gray(tifffile.imread(v)) for k, v in ours.items()}
    ref_gray = [gray(tifffile.imread(p)) for p in refs]

    keys = list(our_gray.keys())
    M = np.zeros((len(keys), len(refs)))
    for i, k in enumerate(keys):
        for j in range(len(refs)):
            m = (our_gray[k] > 0) & (ref_gray[j] > 0)
            M[i, j] = ncc(our_gray[k], ref_gray[j], m)

    print("=== NCC 矩阵 (行=我方, 列=参考ref0/1/2) ===")
    print("              ref0     ref1     ref2")
    for i, k in enumerate(keys):
        print(f"{k:12s} " + "  ".join(f"{M[i,j]:7.4f}" for j in range(len(refs))))

    print("=== 配对与残余平移 ===")
    report = [f"[视角 {tag}] NCC 矩阵(行=我方q2/q3/q4, 列=ref0/1/2):"]
    for i, k in enumerate(keys):
        report.append(f"  {k}: " + "  ".join(f"{M[i,j]:.4f}" for j in range(len(refs))))
    report.append(f"[视角 {tag}] 配对与残余平移:")
    for i, k in enumerate(keys):
        if M.shape[1] == 0:
            report.append(f"  {k}: 无参考 DOM，跳过")
            continue
        j = int(np.argmax(M[i]))
        m = (our_gray[k] > 0) & (ref_gray[j] > 0)
        dx, dy, resp = phase_shift(our_gray[k], ref_gray[j], m)
        shift = np.hypot(dx, dy)
        msg = (f"{k} <-> ref{j}  NCC={M[i,j]:.4f}  "
               f"残余平移 dx={dx:+.3f} dy={dy:+.3f} (|d|={shift:.3f} px)")
        print(msg)
        report.append("  " + msg)
        # 棋盘格 + 差异可视化（仅椭球高，最关键）
        if k.startswith("q4"):
            _save_overlay(our_gray[k], ref_gray[j], m, f"q4_ellipH_{tag}")
    return report


def main():
    image_sets = []
    for img in sp.images():
        tag = img[-3:]
        sfx = "" if tag == "001" else f"_{tag}"
        image_sets.append((
            tag,
            {
                "q2_0高程面": os.path.join(OUT, f"q2_dom_0m{sfx}.tif"),
                "q3_水准高": os.path.join(OUT, f"q3_dom_orthoH{sfx}.tif"),
                "q4_椭球高": os.path.join(OUT, f"q4_dom_ellipH{sfx}.tif"),
            },
        ))
    all_report = []
    for tag, ours in image_sets:
        all_report += compare_one(tag, ours)
        all_report.append("")

    with open(os.path.join(OUT, "compare_report.txt"), "w", encoding="utf-8") as f:
        f.write("与参考结果(ArcGIS DOM)定量几何对比 —— 001 与 005 两视角\n\n")
        f.write("\n".join(all_report))
    print(f"\n已输出: {os.path.join(OUT,'compare_report.txt')} 及 results/diff_q4_ellipH_001/005.png")


def _save_overlay(our, ref, mask, tag):
    ys, xs = np.where(mask)
    r0, r1, c0, c1 = ys.min(), ys.max(), xs.min(), xs.max()
    a = our[r0:r1 + 1, c0:c1 + 1]
    b = ref[r0:r1 + 1, c0:c1 + 1]

    def norm(x):
        lo, hi = np.percentile(x[x > 0], (2, 98)) if (x > 0).any() else (0, 1)
        return np.clip((x - lo) / (hi - lo + 1e-6), 0, 1)
    a, b = norm(a), norm(b)
    # 棋盘格
    blk = 64
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    chk = ((yy // blk + xx // blk) % 2).astype(bool)
    board = np.where(chk, a, b)

    fig, ax = plt.subplots(1, 3, figsize=(15, 5))
    ax[0].imshow(a, cmap="gray"); ax[0].set_title("Ours (ellipsoidal H)")
    ax[1].imshow(board, cmap="gray"); ax[1].set_title("Checkerboard ours/ref")
    ax[2].imshow(np.abs(a - b), cmap="hot"); ax[2].set_title("Abs diff (normalized)")
    for x in ax:
        x.axis("off")
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, f"diff_{tag}.png"), dpi=110)
    plt.close()


if __name__ == "__main__":
    main()
