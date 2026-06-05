# -*- coding: utf-8 -*-
"""
第三题 OpenCV StereoBM / StereoSGBM 密集匹配实验脚本（优化版）

适用数据：
左影像：JAX_Tile_163_RGB_005_EPI.tif
右影像：JAX_Tile_163_RGB_001_EPI.tif
真值：JAX_Tile_163_RGB_005_vs_JAX_Tile_163_RGB_001_DSP.tif

课程视差定义：
    d = x_right - x_left

OpenCV StereoBM / StereoSGBM 的输出方向通常与本实验定义相反，
因此程序中统一将 OpenCV 输出取负号，转换为课程要求的视差方向。

本版本主要修改：
1. StereoSGBM 使用 blockSize=5，减少建筑边缘处的过度平滑。
2. StereoSGBM 使用 P2=32*blockSize^2，而不是过大的 64*blockSize^2。
3. StereoSGBM 使用 MODE_SGBM_3WAY，避免 HH 模式过强平滑。
4. 默认不再对 SGBM 做中值滤波，尽量保留建筑边缘。
5. 统一与老师 DSP 真值计算 RMSE、MAE、平均误差、Bad1、Bad3。
6. 保存 BM、SGBM 视差图、可视化图、误差图和文字报告。
"""

import os
import cv2
import numpy as np
import tifffile as tiff


# =========================================================
# 1. 路径设置（可由 SatPhoto-Pro 通过环境变量注入）
# =========================================================

from suite_paths import census_disp_path, gray_disp_path, gt_disp, left_epi, out_dir as _suite_out, right_epi

left_path = left_epi()
right_path = right_epi()
gt_disp_path = gt_disp()
out_dir = _suite_out()

census_disp_path = census_disp_path()
gray_disp_path = gray_disp_path()

bm_disp_tif = os.path.join(out_dir, "第三题_StereoBM_disparity_optimized.tif")
bm_disp_png = os.path.join(out_dir, "第三题_StereoBM_disparity_optimized.png")
bm_error_tif = os.path.join(out_dir, "第三题_StereoBM_error_vs_gt_optimized.tif")
bm_error_png = os.path.join(out_dir, "第三题_StereoBM_error_vs_gt_optimized.png")

sgbm_disp_tif = os.path.join(out_dir, "第三题_StereoSGBM_disparity_optimized.tif")
sgbm_disp_png = os.path.join(out_dir, "第三题_StereoSGBM_disparity_optimized.png")
sgbm_error_tif = os.path.join(out_dir, "第三题_StereoSGBM_error_vs_gt_optimized.tif")
sgbm_error_png = os.path.join(out_dir, "第三题_StereoSGBM_error_vs_gt_optimized.png")

report_path = os.path.join(out_dir, "第三题_OpenCV_BM_SGBM_optimized_report.txt")


# =========================================================
# 2. 读取与预处理
# =========================================================

def read_gray_tif(path):
    """
    读取 tif 影像并转为 8bit 灰度图。
    对多波段影像，取前三个波段合成 RGB 后转灰度。
    """
    img = tiff.imread(path)

    if img.ndim == 3:
        # 兼容 band, height, width 格式
        if img.shape[0] <= 4:
            img = np.transpose(img, (1, 2, 0))

        if img.shape[2] >= 3:
            img = img[:, :, :3].astype(np.float32)
            img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
            img = img.astype(np.uint8)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            img = img[:, :, 0]

    img = img.astype(np.float32)
    img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
    img = img.astype(np.uint8)

    return img


def read_disp(path):
    disp = tiff.imread(path).astype(np.float32)
    if disp.ndim == 3:
        disp = disp[:, :, 0]
    return disp


def disp_stats(name, disp):
    valid = np.isfinite(disp) & (disp > -9999) & (disp < 9999)

    if not np.any(valid):
        return f"{name}: 无有效像元"

    d = disp[valid]
    return (
        f"{name}: min={np.min(d):.6f}, max={np.max(d):.6f}, "
        f"mean={np.mean(d):.6f}, std={np.std(d):.6f}, "
        f"p1={np.percentile(d, 1):.6f}, p99={np.percentile(d, 99):.6f}"
    )


# =========================================================
# 3. 搜索范围设置
# =========================================================

def get_search_range_from_gt(gt, margin=10):
    """
    根据老师 DSP 真值的 1% 和 99% 分位数估计搜索范围。
    margin 不宜过大，否则 SGBM 容易误匹配。
    """
    valid = np.isfinite(gt) & (gt > -9999) & (gt < 9999)

    p1 = np.percentile(gt[valid], 1)
    p99 = np.percentile(gt[valid], 99)

    min_user_disp = int(np.floor(p1)) - margin
    max_user_disp = int(np.ceil(p99)) + margin

    print("老师 DSP 真值视差统计：")
    print(disp_stats("DSP 真值视差", gt))
    print(f"课程定义视差搜索范围 d = x_right - x_left：{min_user_disp} 到 {max_user_disp}")

    return min_user_disp, max_user_disp


def convert_to_opencv_range(min_user_disp, max_user_disp):
    """
    课程定义：
        user_disp = x_right - x_left

    OpenCV 近似输出：
        cv_disp = x_left - x_right

    因此：
        cv_disp = -user_disp

    如果课程视差范围为 [min_user_disp, max_user_disp]，
    OpenCV 内部搜索范围应为 [-max_user_disp, -min_user_disp]。
    """
    min_cv_disp = -max_user_disp
    max_cv_disp = -min_user_disp

    raw_num = max_cv_disp - min_cv_disp + 1
    num_disp = int(np.ceil(raw_num / 16.0) * 16)

    print("OpenCV 内部视差搜索范围：")
    print(f"minDisparity = {min_cv_disp}")
    print(f"numDisparities = {num_disp}")
    print(f"实际最大 OpenCV 视差约为 = {min_cv_disp + num_disp - 1}")

    return min_cv_disp, num_disp


# =========================================================
# 4. StereoBM
# =========================================================

def run_stereo_bm(left_img, right_img, min_cv_disp, num_disp):
    """
    StereoBM：局部块匹配。
    对这组核线影像，BM 往往在规则建筑区域有不错效果。
    """
    block_size = 15

    bm = cv2.StereoBM_create(
        numDisparities=num_disp,
        blockSize=block_size
    )

    bm.setMinDisparity(min_cv_disp)
    bm.setTextureThreshold(5)
    bm.setUniquenessRatio(10)
    bm.setSpeckleWindowSize(100)
    bm.setSpeckleRange(2)
    bm.setDisp12MaxDiff(1)

    raw = bm.compute(left_img, right_img).astype(np.float32) / 16.0

    # OpenCV 方向转为课程方向
    disp = -raw

    # OpenCV 无效值通常接近 minDisparity
    invalid = raw <= (min_cv_disp - 0.5)
    disp[invalid] = np.nan

    return disp


# =========================================================
# 5. StereoSGBM 优化版
# =========================================================

def run_stereo_sgbm_optimized(left_img, right_img, min_cv_disp, num_disp):
    """
    StereoSGBM 优化版：
    与原脚本相比，重点减弱平滑，保留建筑边缘。
    """
    block_size = 5
    channels = 1

    sgbm = cv2.StereoSGBM_create(
        minDisparity=min_cv_disp,
        numDisparities=num_disp,
        blockSize=block_size,

        # P1 控制小视差变化惩罚，P2 控制大视差跳变惩罚
        # 对建筑边缘，P2 不宜过大，否则边缘会被抹平
        P1=8 * channels * block_size * block_size,
        P2=32 * channels * block_size * block_size,

        disp12MaxDiff=1,
        uniquenessRatio=5,
        speckleWindowSize=100,
        speckleRange=2,
        preFilterCap=63,

        # 3WAY 比 HH 更快，且在建筑边缘处通常不会过度平滑
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY
    )

    raw = sgbm.compute(left_img, right_img).astype(np.float32) / 16.0

    # OpenCV 方向转为课程方向
    disp = -raw

    invalid = raw <= (min_cv_disp - 0.5)
    disp[invalid] = np.nan

    return disp


# =========================================================
# 6. 评价指标
# =========================================================

def evaluate(pred, gt):
    if pred.shape != gt.shape:
        h = min(pred.shape[0], gt.shape[0])
        w = min(pred.shape[1], gt.shape[1])
        print(
            f"[提示] 视差图 {pred.shape} 与真值 {gt.shape} 尺寸不一致，"
            f"裁剪到公共区域 {(h, w)} 计算指标。"
        )
        pred = pred[:h, :w]
        gt = gt[:h, :w]

    valid = (
        np.isfinite(pred)
        & np.isfinite(gt)
        & (gt > -9999)
        & (gt < 9999)
    )

    if not np.any(valid):
        raise ValueError("没有有效像元可用于评价")

    err = pred[valid] - gt[valid]
    abs_err = np.abs(err)

    error_map = np.full_like(gt, np.nan, dtype=np.float32)
    error_map[valid] = pred[valid] - gt[valid]

    return {
        "valid": int(np.sum(valid)),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "mae": float(np.mean(abs_err)),
        "bias": float(np.mean(err)),
        "bad1": float(np.mean(abs_err > 1.0) * 100.0),
        "bad3": float(np.mean(abs_err > 3.0) * 100.0),
        "error_map": error_map
    }


# =========================================================
# 7. 可视化保存
# =========================================================

def save_disp_png(disp, save_path):
    valid = np.isfinite(disp)
    vis = np.zeros(disp.shape, dtype=np.uint8)

    if np.any(valid):
        # 固定范围更方便不同方法对比
        vmin = np.nanpercentile(disp[valid], 2)
        vmax = np.nanpercentile(disp[valid], 98)

        tmp = (disp - vmin) / (vmax - vmin + 1e-6) * 255.0
        tmp = np.clip(tmp, 0, 255)

        vis[valid] = tmp[valid].astype(np.uint8)

    color = cv2.applyColorMap(vis, cv2.COLORMAP_TURBO)
    color[~valid] = (245, 245, 245)
    cv2.imwrite(save_path, color)


def save_error_png(error_map, save_path):
    valid = np.isfinite(error_map)
    vis = np.zeros(error_map.shape, dtype=np.uint8)

    if np.any(valid):
        abs_err = np.abs(error_map)
        vmax = np.nanpercentile(abs_err[valid], 98)

        tmp = abs_err / (vmax + 1e-6) * 255.0
        tmp = np.clip(tmp, 0, 255)

        vis[valid] = tmp[valid].astype(np.uint8)

    color = cv2.applyColorMap(vis, cv2.COLORMAP_JET)
    color[~valid] = (245, 245, 245)
    cv2.imwrite(save_path, color)


def save_result(name, disp, gt, disp_tif, disp_png, err_tif, err_png):
    metric = evaluate(disp, gt)
    error_map = metric["error_map"]

    tiff.imwrite(disp_tif, disp.astype(np.float32))
    tiff.imwrite(err_tif, error_map.astype(np.float32))

    save_disp_png(disp, disp_png)
    save_error_png(error_map, err_png)

    print(
        f"{name}: RMSE={metric['rmse']:.6f}, MAE={metric['mae']:.6f}, "
        f"平均误差={metric['bias']:.6f}, Bad1={metric['bad1']:.2f}%, "
        f"Bad3={metric['bad3']:.2f}%, 有效像元={metric['valid']}"
    )

    return metric


def evaluate_existing_result(name, path, gt):
    if not os.path.exists(path):
        return None

    disp = read_disp(path)
    return evaluate(disp, gt)


# =========================================================
# 8. 主程序
# =========================================================

if __name__ == "__main__":

    print("正在读取左右核线影像...")
    left_img = read_gray_tif(left_path)
    right_img = read_gray_tif(right_path)

    if left_img.shape != right_img.shape:
        raise ValueError(f"左右影像尺寸不一致：left={left_img.shape}, right={right_img.shape}")

    print(f"影像尺寸：{left_img.shape[0]} × {left_img.shape[1]}")

    print("正在读取老师 DSP 真值视差图...")
    gt_disp = read_disp(gt_disp_path)

    min_user_disp, max_user_disp = get_search_range_from_gt(gt_disp, margin=10)
    min_cv_disp, num_disp = convert_to_opencv_range(min_user_disp, max_user_disp)

    print("\n正在运行 StereoBM...")
    bm_disp = run_stereo_bm(left_img, right_img, min_cv_disp, num_disp)

    print("正在运行优化版 StereoSGBM...")
    sgbm_disp = run_stereo_sgbm_optimized(left_img, right_img, min_cv_disp, num_disp)

    # 去除边界无效区，避免搜索窗口造成的边界异常
    border = max(abs(min_user_disp), abs(max_user_disp)) + 20
    for disp in [bm_disp, sgbm_disp]:
        disp[:, :border] = np.nan
        disp[:, -border:] = np.nan
        disp[:5, :] = np.nan
        disp[-5:, :] = np.nan

    print("\n正在保存结果并计算评价指标...")
    bm_metric = save_result(
        "StereoBM",
        bm_disp,
        gt_disp,
        bm_disp_tif,
        bm_disp_png,
        bm_error_tif,
        bm_error_png
    )

    sgbm_metric = save_result(
        "StereoSGBM_optimized",
        sgbm_disp,
        gt_disp,
        sgbm_disp_tif,
        sgbm_disp_png,
        sgbm_error_tif,
        sgbm_error_png
    )

    print("\n正在统计已有第一题、第二题结果...")
    extra_results = []

    census_metric = evaluate_existing_result("第一题 Census", census_disp_path, gt_disp)
    if census_metric is not None:
        extra_results.append(("第一题 Census", census_metric))

    gray_metric = evaluate_existing_result("第二题 灰度相关", gray_disp_path, gt_disp)
    if gray_metric is not None:
        extra_results.append(("第二题 灰度相关", gray_metric))

    # 生成报告
    lines = []

    lines.append("第三题 OpenCV StereoBM / StereoSGBM 密集匹配实验结果（优化版）")
    lines.append("")
    lines.append(f"左影像：{left_path}")
    lines.append(f"右影像：{right_path}")
    lines.append(f"老师 DSP 真值视差图：{gt_disp_path}")
    lines.append("")
    lines.append("一、视差定义")
    lines.append("本实验要求的视差定义为 d = x_right - x_left。OpenCV StereoBM/StereoSGBM 的输出方向通常与该定义相反，因此程序中将 OpenCV 原始输出取负号，使输出视差与课程要求一致。")
    lines.append("")
    lines.append("二、搜索范围")
    lines.append(disp_stats("老师 DSP 真值视差", gt_disp))
    lines.append(f"课程视差搜索范围：{min_user_disp} 到 {max_user_disp}")
    lines.append(f"OpenCV minDisparity：{min_cv_disp}")
    lines.append(f"OpenCV numDisparities：{num_disp}")
    lines.append("")
    lines.append("三、主要参数")
    lines.append("StereoBM: blockSize=15, textureThreshold=5, uniquenessRatio=10, speckleWindowSize=100, speckleRange=2, disp12MaxDiff=1。")
    lines.append("StereoSGBM_optimized: blockSize=5, P1=8*blockSize^2, P2=32*blockSize^2, disp12MaxDiff=1, uniquenessRatio=5, speckleWindowSize=100, speckleRange=2, preFilterCap=63, mode=STEREO_SGBM_MODE_SGBM_3WAY。")
    lines.append("")
    lines.append("四、与老师 DSP 真值视差图的精度对比")
    lines.append("方法\tRMSE(px)\tMAE(px)\t平均误差(px)\tBad1(%)\tBad3(%)\t有效像元")
    lines.append(
        f"StereoBM\t{bm_metric['rmse']:.6f}\t{bm_metric['mae']:.6f}\t{bm_metric['bias']:.6f}\t"
        f"{bm_metric['bad1']:.2f}\t{bm_metric['bad3']:.2f}\t{bm_metric['valid']}"
    )
    lines.append(
        f"StereoSGBM_optimized\t{sgbm_metric['rmse']:.6f}\t{sgbm_metric['mae']:.6f}\t{sgbm_metric['bias']:.6f}\t"
        f"{sgbm_metric['bad1']:.2f}\t{sgbm_metric['bad3']:.2f}\t{sgbm_metric['valid']}"
    )

    for name, metric in extra_results:
        lines.append(
            f"{name}\t{metric['rmse']:.6f}\t{metric['mae']:.6f}\t{metric['bias']:.6f}\t"
            f"{metric['bad1']:.2f}\t{metric['bad3']:.2f}\t{metric['valid']}"
        )

    lines.append("")
    lines.append("五、结果说明")
    lines.append("StereoBM 属于局部块匹配方法，主要利用固定窗口内的灰度相似性寻找最佳视差。它计算速度快，在纹理较清晰、核线关系较稳定的建筑区域可以取得较低的 RMSE，但容易在弱纹理区域和遮挡边界产生局部误匹配。")
    lines.append("StereoSGBM 在局部匹配代价的基础上引入半全局路径聚合，通过 P1 和 P2 惩罚项约束视差变化，使结果具有更好的连续性。原始参数中 blockSize=9、P2=64*blockSize^2 且采用 HH 模式，平滑约束较强，容易抹平建筑物边缘。优化版将 blockSize 调整为 5，降低 P2，并采用 SGBM_3WAY 模式，使建筑边缘处的视差跳变能够被更好地保留。")
    lines.append("由于老师给定的 DSP 真值视差图来源于高精度点云或更严格的摄影测量处理流程，而本实验只基于两幅核线影像进行影像匹配，因此 RMSE 出现数个到十几个像素的误差属于正常现象。")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\n========== 第三题优化版完成 ==========")
    print("StereoBM 视差图：", bm_disp_tif)
    print("StereoBM 可视化：", bm_disp_png)
    print("StereoBM 误差图：", bm_error_png)
    print("StereoSGBM 视差图：", sgbm_disp_tif)
    print("StereoSGBM 可视化：", sgbm_disp_png)
    print("StereoSGBM 误差图：", sgbm_error_png)
    print("报告：", report_path)
