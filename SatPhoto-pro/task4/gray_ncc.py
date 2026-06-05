# -*- coding: utf-8 -*-
"""Gray-level normalized cross-correlation dense matching.

This is the parameter set that produced about RMSE = 17.7569 px
against the provided truth disparity in the previous full experiment.

Disparity convention:
    d = x_right - x_left
"""

from __future__ import annotations

from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image


from suite_paths import gt_disp, left_epi, out_dir as _suite_out, right_epi

LEFT = Path(left_epi())
RIGHT = Path(right_epi())
GT = Path(gt_disp())
OUT = Path(_suite_out())
OUT.mkdir(parents=True, exist_ok=True)

DISP_MIN = -32
DISP_MAX = 32
WINDOW = 11
NODATA_THRESHOLD = -10000.0


def read_gray(path: Path) -> np.ndarray:
    rgb = np.array(Image.open(path).convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def read_float(path: Path) -> np.ndarray:
    return np.array(Image.open(path), dtype=np.float32)


def save_float_tif(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr.astype(np.float32), mode="F").save(path, format="TIFF")


def save_disp_png(path: Path, disp: np.ndarray) -> None:
    valid = np.isfinite(disp)
    scaled = np.zeros(disp.shape, dtype=np.uint8)
    scaled[valid] = np.clip((disp[valid] - DISP_MIN) * 255 / (DISP_MAX - DISP_MIN), 0, 255).astype(np.uint8)
    color = cv2.applyColorMap(scaled, cv2.COLORMAP_TURBO)
    color[~valid] = (245, 245, 245)
    Image.fromarray(cv2.cvtColor(color, cv2.COLOR_BGR2RGB)).save(path)


def gray_ncc_dense_match(left_gray: np.ndarray, right_gray: np.ndarray, window: int = WINDOW) -> np.ndarray:
    """Winner-takes-all dense matching with local normalized cross correlation."""
    left = left_gray.astype(np.float32)
    right = right_gray.astype(np.float32)
    h, w = left.shape
    best_score = np.full((h, w), -np.inf, dtype=np.float32)
    best_disp = np.zeros((h, w), dtype=np.float32)
    kernel = (window, window)
    eps = 1e-6
    min_count = max(9, int(window * window * 0.55))

    for disp in range(DISP_MIN, DISP_MAX + 1):
        shifted = np.zeros_like(right, dtype=np.float32)
        valid = np.zeros_like(right, dtype=np.float32)
        if disp >= 0:
            shifted[:, : w - disp] = right[:, disp:w]
            valid[:, : w - disp] = 1.0
        else:
            shifted[:, -disp:w] = right[:, : w + disp]
            valid[:, -disp:w] = 1.0

        lv = left * valid
        rv = shifted * valid
        n = cv2.boxFilter(valid, cv2.CV_32F, kernel, normalize=False, borderType=cv2.BORDER_CONSTANT)
        sum_l = cv2.boxFilter(lv, cv2.CV_32F, kernel, normalize=False, borderType=cv2.BORDER_CONSTANT)
        sum_r = cv2.boxFilter(rv, cv2.CV_32F, kernel, normalize=False, borderType=cv2.BORDER_CONSTANT)
        sum_lr = cv2.boxFilter(lv * rv, cv2.CV_32F, kernel, normalize=False, borderType=cv2.BORDER_CONSTANT)
        sum_l2 = cv2.boxFilter(lv * lv, cv2.CV_32F, kernel, normalize=False, borderType=cv2.BORDER_CONSTANT)
        sum_r2 = cv2.boxFilter(rv * rv, cv2.CV_32F, kernel, normalize=False, borderType=cv2.BORDER_CONSTANT)

        denom_l = sum_l2 - (sum_l * sum_l) / np.maximum(n, 1.0)
        denom_r = sum_r2 - (sum_r * sum_r) / np.maximum(n, 1.0)
        denom = np.sqrt(np.maximum(denom_l * denom_r, 0.0)) + eps
        score = (sum_lr - (sum_l * sum_r) / np.maximum(n, 1.0)) / denom
        score[n < min_count] = -np.inf

        update = score > best_score
        best_score[update] = score[update]
        best_disp[update] = float(disp)

    best_disp[~np.isfinite(best_score)] = np.nan
    return best_disp


def metrics(pred: np.ndarray, gt: np.ndarray) -> dict[str, float | int]:
    if pred.shape != gt.shape:
        h = min(pred.shape[0], gt.shape[0])
        w = min(pred.shape[1], gt.shape[1])
        print(
            f"[提示] 视差图 {pred.shape} 与真值 {gt.shape} 尺寸不一致，"
            f"裁剪到公共区域 {(h, w)} 计算指标。"
        )
        pred = pred[:h, :w]
        gt = gt[:h, :w]
    valid = np.isfinite(pred) & np.isfinite(gt) & (gt > NODATA_THRESHOLD)
    err = pred[valid] - gt[valid]
    abs_err = np.abs(err)
    return {
        "valid": int(valid.sum()),
        "mae": float(abs_err.mean()),
        "rmse": float(np.sqrt((err * err).mean())),
        "bad1": float((abs_err > 1.0).mean()),
        "bias": float(err.mean()),
    }


def main() -> None:
    t0 = time.perf_counter()
    left = read_gray(LEFT)
    right = read_gray(RIGHT)
    gt = read_float(GT)
    disp = gray_ncc_dense_match(left, right, WINDOW)

    out_tif = OUT / "第二题_gray_disparity.tif"
    out_png = OUT / "第二题_gray_disparity.png"
    save_float_tif(out_tif, disp)
    save_disp_png(out_png, disp)

    m = metrics(disp, gt)
    seconds = time.perf_counter() - t0
    report = (
        "第二题 灰度归一化相关 NCC 参数\n\n"
        f"方法：局部归一化互相关 NCC，winner-takes-all\n"
        f"窗口大小：{WINDOW} x {WINDOW}\n"
        f"视差范围：[{DISP_MIN}, {DISP_MAX}] 像素\n"
        f"视差定义：d = x_right - x_left\n"
        f"边界处理：候选视差越界处不参与，窗口有效像元不足 {max(9, int(WINDOW * WINDOW * 0.55))} 则无效\n"
        f"输出：{out_tif}\n\n"
        f"valid={m['valid']}, MAE={m['mae']:.4f}, RMSE={m['rmse']:.4f}, "
        f"Bad1={m['bad1']:.4f}, bias={m['bias']:.4f}, time={seconds:.1f}s\n"
    )
    (OUT / "第二题_gray_ncc_report.txt").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
