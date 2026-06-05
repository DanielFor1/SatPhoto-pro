import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import cv2
import numpy as np
import tifffile as tiff


# =========================================================
# 1. 路径设置（可由 SatPhoto-Pro 通过环境变量注入）
# =========================================================

from suite_paths import gt_disp, left_epi, out_dir as _suite_out, right_epi

left_path = left_epi()
right_path = right_epi()
gt_disp_path = gt_disp()
out_dir = _suite_out()

out_disp_tif = os.path.join(out_dir, "第一题_census_disparity.tif")
out_disp_png = os.path.join(out_dir, "第一题_census_disparity.png")
out_error_tif = os.path.join(out_dir, "第一题_census_error_vs_gt.tif")
out_error_png = os.path.join(out_dir, "第一题_census_error_vs_gt.png")
out_report = os.path.join(out_dir, "第一题_census_report.txt")


# =========================================================
# 2. 读取影像
# =========================================================

def read_gray_tif(path):
    img = tiff.imread(path)

    if img.ndim == 3:
        if img.shape[0] <= 4:
            img = np.transpose(img, (1, 2, 0))

        if img.shape[2] >= 3:
            img = img[:, :, :3]
            img = img.astype(np.float32)
            img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
            img = img.astype(np.uint8)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            img = img[:, :, 0]

    img = img.astype(np.float32)
    img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
    img = img.astype(np.uint8)

    return img


# =========================================================
# 3. 读取真值视差并确定搜索范围
# =========================================================

def read_gt_and_get_range(gt_path, margin=20):
    gt = tiff.imread(gt_path).astype(np.float32)

    if gt.ndim == 3:
        gt = gt[:, :, 0]

    valid = (
        np.isfinite(gt)
        & (gt > -9999)
        & (gt < 9999)
    )

    if np.sum(valid) == 0:
        raise RuntimeError("真值视差图中没有有效像元。")

    p1 = np.nanpercentile(gt[valid], 1)
    p99 = np.nanpercentile(gt[valid], 99)

    min_disp = int(np.floor(p1)) - margin
    max_disp = int(np.ceil(p99)) + margin

    print("真值视差统计：")
    print(f"min  = {np.nanmin(gt[valid]):.3f}")
    print(f"max  = {np.nanmax(gt[valid]):.3f}")
    print(f"mean = {np.nanmean(gt[valid]):.3f}")
    print(f"p1   = {p1:.3f}")
    print(f"p99  = {p99:.3f}")
    print(f"搜索范围：{min_disp} 到 {max_disp}")

    return gt, min_disp, max_disp


# =========================================================
# 4. Census 变换
# =========================================================

def census_transform(img, win_size=5):
    assert win_size % 2 == 1
    assert win_size <= 9

    h, w = img.shape
    r = win_size // 2

    center = img.astype(np.int16)
    census = np.zeros((h, w), dtype=np.uint64)

    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy == 0 and dx == 0:
                continue

            shifted = np.zeros_like(center)

            y1_src = max(0, -dy)
            y2_src = min(h, h - dy)
            x1_src = max(0, -dx)
            x2_src = min(w, w - dx)

            y1_dst = max(0, dy)
            y2_dst = min(h, h + dy)
            x1_dst = max(0, dx)
            x2_dst = min(w, w + dx)

            shifted[y1_dst:y2_dst, x1_dst:x2_dst] = center[y1_src:y2_src, x1_src:x2_src]

            census <<= 1
            census |= (shifted < center).astype(np.uint64)

    return census


# =========================================================
# 5. 汉明距离
# =========================================================

def hamming_cost(a, b):
    xor_val = np.bitwise_xor(a, b)
    cost = np.zeros(xor_val.shape, dtype=np.uint8)

    temp = xor_val.copy()
    while np.any(temp):
        cost += (temp & 1).astype(np.uint8)
        temp >>= 1

    return cost


# =========================================================
# 6. Census 密集匹配：加入窗口代价聚合
# =========================================================

def census_dense_match(left_census, right_census, min_disp, max_disp, agg_win=21):
    """
    Census 密集匹配。
    视差定义：d = x_right - x_left
    改进点：对每个视差下的汉明距离图进行 agg_win × agg_win 窗口聚合。
    """

    h, w = left_census.shape

    disp = np.full((h, w), np.nan, dtype=np.float32)
    best_cost = np.full((h, w), 1e9, dtype=np.float32)

    kernel = np.ones((agg_win, agg_win), dtype=np.float32)

    for d in range(min_disp, max_disp + 1):
        print(f"正在搜索视差 d = {d}")

        if d >= 0:
            xl1, xl2 = 0, w - d
            xr1, xr2 = d, w
        else:
            xl1, xl2 = -d, w
            xr1, xr2 = 0, w + d

        if xl2 <= xl1 or xr2 <= xr1:
            continue

        left_slice = left_census[:, xl1:xl2]
        right_slice = right_census[:, xr1:xr2]

        cost = hamming_cost(left_slice, right_slice).astype(np.float32)

        cost = cv2.filter2D(
            cost,
            ddepth=-1,
            kernel=kernel,
            borderType=cv2.BORDER_REFLECT
        )

        old_cost = best_cost[:, xl1:xl2]
        old_disp = disp[:, xl1:xl2]

        update = cost < old_cost
        old_cost[update] = cost[update]
        old_disp[update] = d

        best_cost[:, xl1:xl2] = old_cost
        disp[:, xl1:xl2] = old_disp

    return disp


# =========================================================
# 7. RMSE 计算
# =========================================================

def calculate_rmse(my_disp, gt_disp):
    if gt_disp.ndim == 3:
        gt_disp = gt_disp[:, :, 0]

    if my_disp.shape != gt_disp.shape:
        h = min(my_disp.shape[0], gt_disp.shape[0])
        w = min(my_disp.shape[1], gt_disp.shape[1])
        print(
            f"[提示] 视差图 {my_disp.shape} 与真值 {gt_disp.shape} 尺寸不一致，"
            f"裁剪到公共区域 {(h, w)} 计算 RMSE。"
        )
        my_disp = my_disp[:h, :w]
        gt_disp = gt_disp[:h, :w]

    valid = (
        np.isfinite(my_disp)
        & np.isfinite(gt_disp)
        & (gt_disp > -9999)
        & (gt_disp < 9999)
    )

    diff = my_disp[valid] - gt_disp[valid]

    rmse = np.sqrt(np.mean(diff ** 2))
    mae = np.mean(np.abs(diff))
    mean_error = np.mean(diff)

    error_map = np.full_like(gt_disp, np.nan, dtype=np.float32)
    error_map[valid] = diff

    return rmse, mae, mean_error, int(np.sum(valid)), error_map


# =========================================================
# 8. 保存可视化
# =========================================================

def save_disp_png(disp, save_path):
    valid = np.isfinite(disp)
    vis = np.zeros_like(disp, dtype=np.uint8)

    if np.any(valid):
        vmin = np.nanpercentile(disp[valid], 2)
        vmax = np.nanpercentile(disp[valid], 98)

        tmp = (disp - vmin) / (vmax - vmin + 1e-6) * 255
        tmp = np.clip(tmp, 0, 255)

        vis[valid] = tmp[valid].astype(np.uint8)

    cv2.imwrite(save_path, vis)


def save_error_png(error_map, save_path):
    valid = np.isfinite(error_map)
    vis = np.zeros_like(error_map, dtype=np.uint8)

    if np.any(valid):
        abs_error = np.abs(error_map)
        vmax = np.nanpercentile(abs_error[valid], 98)

        tmp = abs_error / (vmax + 1e-6) * 255
        tmp = np.clip(tmp, 0, 255)

        vis[valid] = tmp[valid].astype(np.uint8)

    cv2.imwrite(save_path, vis)


# =========================================================
# 9. 主程序
# =========================================================

if __name__ == "__main__":

    census_win = 7
    agg_win = 21

    print("正在读取影像...")
    left_img = read_gray_tif(left_path)
    right_img = read_gray_tif(right_path)

    if left_img.shape != right_img.shape:
        raise ValueError(f"左右影像尺寸不一致：left={left_img.shape}, right={right_img.shape}")

    print("影像尺寸：", left_img.shape)

    print("正在读取真值视差图...")
    gt_disp, min_disp, max_disp = read_gt_and_get_range(gt_disp_path, margin=20)

    print("正在进行 Census 变换...")
    left_census = census_transform(left_img, win_size=census_win)
    right_census = census_transform(right_img, win_size=census_win)

    print("正在进行 Census 密集匹配...")
    disp = census_dense_match(
        left_census,
        right_census,
        min_disp=min_disp,
        max_disp=max_disp,
        agg_win=agg_win
    )

    border = max(abs(min_disp), abs(max_disp)) + agg_win + 5
    disp[:, :border] = np.nan
    disp[:, -border:] = np.nan
    disp[:border, :] = np.nan
    disp[-border:, :] = np.nan

    nan_mask = ~np.isfinite(disp)
    temp = disp.copy()
    temp[nan_mask] = 0

    disp_filtered = cv2.medianBlur(temp.astype(np.float32), 5)
    disp_filtered[nan_mask] = np.nan

    print("正在保存结果...")
    tiff.imwrite(out_disp_tif, disp_filtered.astype(np.float32))
    save_disp_png(disp_filtered, out_disp_png)

    print("正在计算 RMSE...")
    rmse, mae, mean_error, valid_count, error_map = calculate_rmse(disp_filtered, gt_disp)

    tiff.imwrite(out_error_tif, error_map.astype(np.float32))
    save_error_png(error_map, out_error_png)

    report = f"""第一题 Census 算子密集匹配实验结果（改进版）

左影像：
{left_path}

右影像：
{right_path}

真值视差图：
{gt_disp_path}

我的 Census 视差图：
{out_disp_tif}

视差定义：
d = x_right - x_left

Census 窗口大小：
{census_win} × {census_win}

汉明距离代价聚合窗口：
{agg_win} × {agg_win}

视差搜索范围：
{min_disp} 到 {max_disp} 像素

有效像元数量：
{valid_count}

RMSE：
{rmse:.6f} 像素

MAE：
{mae:.6f} 像素

平均误差：
{mean_error:.6f} 像素

说明：
本程序直接使用老师给定的两幅核线影像进行密集匹配，没有重新进行核线纠正。
Census 算子先通过比较邻域像素与中心像素的灰度大小关系形成二进制描述子，
再用汉明距离衡量左右影像候选像素之间的相似性。
与基础版本相比，本程序对每一个视差下的汉明距离代价图进行了局部窗口聚合，
能够降低单像素匹配造成的随机噪声，使视差图更加连续。
"""

    with open(out_report, "w", encoding="utf-8") as f:
        f.write(report)

    print("\n========== Census 改进版完成 ==========")
    print(f"视差图 tif：{out_disp_tif}")
    print(f"视差图 png：{out_disp_png}")
    print(f"误差图 tif：{out_error_tif}")
    print(f"误差图 png：{out_error_png}")
    print(f"报告 txt：{out_report}")
    print(f"RMSE = {rmse:.6f} 像素")
    print(f"MAE  = {mae:.6f} 像素")
    print(f"平均误差 = {mean_error:.6f} 像素")
