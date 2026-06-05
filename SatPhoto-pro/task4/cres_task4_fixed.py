# -*- coding: utf-8 -*-
"""
Task4：CREStereo 深度学习密集匹配与 DSP 真值视差 RMSE 评价

修改重点：
1. 只把 channel0 作为 CREStereo 的有效视差输出，不再把 channel1 当作候选视差。
2. 同时测试“不乘尺度”和“乘尺度”两种恢复方式，避免把视差错误放大 4 倍。
3. 同时测试正号和负号，适配课程定义 d = x_right - x_left。
4. 前三题结果统一与老师 DSP 真值比较，而不是与 CREStereo 互相比。
5. 跳过 DSP 真值中的 NoData 像元，例如 -99999。
"""

import os
import cv2
import numpy as np
import tifffile as tiff
import onnxruntime as ort


# =========================================================
# 1. 路径设置（可由 SatPhoto-Pro 通过环境变量注入）
# =========================================================

from suite_paths import (
    bm_disp_path,
    census_disp_path,
    cres_model,
    gray_disp_path,
    gt_disp,
    left_epi,
    out_dir as _suite_out,
    right_epi,
    sgbm_disp_path,
)

left_path = left_epi()
right_path = right_epi()
gt_path = gt_disp()
model_path = cres_model()
out_dir = _suite_out()

# 第四题输出
out_best_disp_tif = os.path.join(out_dir, "第四题_CREStereo_disparity_fixed.tif")
out_best_disp_png = os.path.join(out_dir, "第四题_CREStereo_disparity_fixed.png")
out_best_error_tif = os.path.join(out_dir, "第四题_CREStereo_error_vs_gt_fixed.tif")
out_best_error_png = os.path.join(out_dir, "第四题_CREStereo_error_vs_gt_fixed.png")
out_report = os.path.join(out_dir, "第四题_CREStereo_report_fixed.txt")

compare_paths = {
    "第一题 Census": census_disp_path(),
    "第二题 灰度相关": gray_disp_path(),
    "第三题 StereoBM": bm_disp_path(),
    "第三题 StereoSGBM": sgbm_disp_path(),
}


# =========================================================
# 2. 工具函数
# =========================================================

def read_rgb_tif(path):
    img = tiff.imread(path)

    if img.ndim == 2:
        img = img.astype(np.float32)
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
        img = img.astype(np.uint8)
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        return img

    if img.ndim == 3:
        # 兼容 band, height, width 格式
        if img.shape[0] <= 4 and img.shape[0] < img.shape[-1]:
            img = np.transpose(img, (1, 2, 0))

        img = img[:, :, :3].astype(np.float32)
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
        img = img.astype(np.uint8)
        return img

    raise ValueError(f"无法识别影像维度：{img.shape}")


def read_disp(path):
    disp = tiff.imread(path).astype(np.float32)
    if disp.ndim == 3:
        disp = disp[:, :, 0]
    return disp


def preprocess(img, size):
    """
    CREStereo ONNX 输入格式：
    size = (width, height)
    output = [1, 3, H, W]
    """
    img_resized = cv2.resize(img, size, interpolation=cv2.INTER_LINEAR)
    img_resized = img_resized.astype(np.float32) / 255.0
    img_resized = np.transpose(img_resized, (2, 0, 1))
    img_resized = np.expand_dims(img_resized, axis=0)
    return img_resized.astype(np.float32)


def valid_gt_mask(ref):
    """跳过老师 DSP 真值中的 NoData 和异常值。"""
    return (
        np.isfinite(ref)
        & (ref > -9999)
        & (ref < 9999)
    )


def calc_metrics(pred, ref):
    if pred.shape != ref.shape:
        h = min(pred.shape[0], ref.shape[0])
        w = min(pred.shape[1], ref.shape[1])
        print(
            f"[提示] 视差图 {pred.shape} 与真值 {ref.shape} 尺寸不一致，"
            f"裁剪到公共区域 {(h, w)} 计算指标。"
        )
        pred = pred[:h, :w]
        ref = ref[:h, :w]

    valid = valid_gt_mask(ref) & np.isfinite(pred)
    if not np.any(valid):
        raise ValueError("没有可用于评价的有效像元，请检查 NoData 掩膜。")

    diff = pred[valid] - ref[valid]

    rmse = float(np.sqrt(np.mean(diff ** 2)))
    mae = float(np.mean(np.abs(diff)))
    mean_error = float(np.mean(diff))
    bad1 = float(np.mean(np.abs(diff) > 1.0) * 100.0)
    bad3 = float(np.mean(np.abs(diff) > 3.0) * 100.0)

    error_map = np.full_like(ref, np.nan, dtype=np.float32)
    error_map[valid] = pred[valid] - ref[valid]

    return {
        "rmse": rmse,
        "mae": mae,
        "mean_error": mean_error,
        "bad1": bad1,
        "bad3": bad3,
        "count": int(np.sum(valid)),
        "error_map": error_map,
    }


def disp_stats(name, disp, mask=None):
    if mask is not None and mask.shape != disp.shape:
        h = min(disp.shape[0], mask.shape[0])
        w = min(disp.shape[1], mask.shape[1])
        disp = disp[:h, :w]
        mask = mask[:h, :w]

    if mask is None:
        valid = np.isfinite(disp)
    else:
        valid = mask & np.isfinite(disp)

    if not np.any(valid):
        return f"{name}: 全部无效"

    data = disp[valid]
    return (
        f"{name}: "
        f"min={np.nanmin(data):.6f}, "
        f"max={np.nanmax(data):.6f}, "
        f"mean={np.nanmean(data):.6f}, "
        f"std={np.nanstd(data):.6f}, "
        f"p1={np.nanpercentile(data, 1):.6f}, "
        f"p99={np.nanpercentile(data, 99):.6f}"
    )


def save_disp_png(disp, save_path, mask=None):
    if mask is not None and mask.shape != disp.shape:
        h = min(disp.shape[0], mask.shape[0])
        w = min(disp.shape[1], mask.shape[1])
        disp = disp[:h, :w]
        mask = mask[:h, :w]

    if mask is None:
        valid = np.isfinite(disp)
    else:
        valid = mask & np.isfinite(disp)

    vis = np.zeros_like(disp, dtype=np.uint8)

    if np.any(valid):
        vmin = np.nanpercentile(disp[valid], 2)
        vmax = np.nanpercentile(disp[valid], 98)
        tmp = (disp - vmin) / (vmax - vmin + 1e-6) * 255
        tmp = np.clip(tmp, 0, 255)
        vis[valid] = tmp[valid].astype(np.uint8)

    color = cv2.applyColorMap(vis, cv2.COLORMAP_TURBO)
    color[~valid] = (245, 245, 245)
    cv2.imwrite(save_path, color)


def save_error_png(error_map, save_path):
    valid = np.isfinite(error_map)
    vis = np.zeros_like(error_map, dtype=np.uint8)

    if np.any(valid):
        abs_error = np.abs(error_map)
        vmax = np.nanpercentile(abs_error[valid], 98)
        tmp = abs_error / (vmax + 1e-6) * 255
        tmp = np.clip(tmp, 0, 255)
        vis[valid] = tmp[valid].astype(np.uint8)

    color = cv2.applyColorMap(vis, cv2.COLORMAP_JET)
    color[~valid] = (245, 245, 245)
    cv2.imwrite(save_path, color)


def format_metric_line(name, metrics):
    return (
        f"{name}: "
        f"RMSE={metrics['rmse']:.6f}, "
        f"MAE={metrics['mae']:.6f}, "
        f"平均误差={metrics['mean_error']:.6f}, "
        f"Bad1={metrics['bad1']:.2f}%, "
        f"Bad3={metrics['bad3']:.2f}%, "
        f"有效像元={metrics['count']}"
    )


# =========================================================
# 3. 主程序
# =========================================================

if __name__ == "__main__":

    report_lines = []

    print("正在读取影像...")
    left = read_rgb_tif(left_path)
    right = read_rgb_tif(right_path)

    h, w = left.shape[:2]
    print(f"原始影像尺寸：{h} × {w}")

    print("正在读取老师 DSP 真值视差图...")
    gt = read_disp(gt_path)
    gt_mask = valid_gt_mask(gt)

    print(disp_stats("老师 DSP 真值视差（有效区域）", gt, gt_mask))

    print("正在加载 CREStereo ONNX 模型...")
    session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])

    print("模型输入：")
    for inp in session.get_inputs():
        print(inp.name, inp.shape, inp.type)

    print("模型输出：")
    for out in session.get_outputs():
        print(out.name, out.shape, out.type)

    print("正在准备输入...")
    init_left = preprocess(left, (320, 240))
    init_right = preprocess(right, (320, 240))
    next_left = preprocess(left, (640, 480))
    next_right = preprocess(right, (640, 480))

    inputs = {
        "init_left": init_left,
        "init_right": init_right,
        "next_left": next_left,
        "next_right": next_right,
    }

    print("正在进行 CREStereo 推理...")
    output = session.run(None, inputs)[0]
    print("模型原始输出尺寸：", output.shape)

    pred0 = output[0, 0].astype(np.float32)
    pred1 = output[0, 1].astype(np.float32)

    print(disp_stats("原始 channel0 480x640", pred0))
    print(disp_stats("原始 channel1 480x640", pred1))

    # =====================================================
    # 关键修改：
    # channel0 是 CREStereo 的视差输出。
    # channel1 近似为 0，不作为视差候选，只在报告里记录。
    # =====================================================

    scale_x = w / 640.0

    pred0_no_scale = cv2.resize(pred0, (w, h), interpolation=cv2.INTER_LINEAR)
    pred0_scaled = pred0_no_scale * scale_x

    # 课程定义：d = x_right - x_left。
    # 深度学习模型常用定义可能相反，所以同时测试正负号。
    candidates = {
        "channel0_no_scale": pred0_no_scale,
        "-channel0_no_scale": -pred0_no_scale,
        "channel0_scaled": pred0_scaled,
        "-channel0_scaled": -pred0_scaled,
    }

    report_lines.append("第四题 CREStereo 深度学习密集匹配实验结果（修正版）")
    report_lines.append("")
    report_lines.append(f"左影像：{left_path}")
    report_lines.append(f"右影像：{right_path}")
    report_lines.append(f"老师 DSP 真值视差图：{gt_path}")
    report_lines.append(f"模型：{model_path}")
    report_lines.append("课程视差定义：d = x_right - x_left")
    report_lines.append("模型输入尺寸：init_left/init_right = 240×320，next_left/next_right = 480×640")
    report_lines.append("模型输出尺寸：[1, 2, 480, 640]")
    report_lines.append("")

    report_lines.append("一、老师 DSP 真值视差统计")
    report_lines.append(disp_stats("老师 DSP 真值视差（有效区域）", gt, gt_mask))
    report_lines.append(f"有效像元数量：{int(np.sum(gt_mask))}")
    report_lines.append("")

    report_lines.append("二、CREStereo 原始输出统计")
    report_lines.append(disp_stats("原始 channel0 480x640", pred0))
    report_lines.append(disp_stats("原始 channel1 480x640", pred1))
    report_lines.append("说明：channel0 为主要视差输出；channel1 数值接近 0，不作为最终视差图。")
    report_lines.append("")

    best_name = None
    best_disp = None
    best_metrics = None

    report_lines.append("三、channel0 不同尺度与方向候选结果")
    for name, disp in candidates.items():
        metrics = calc_metrics(disp, gt)
        print(disp_stats(name, disp, gt_mask))
        print(format_metric_line(name, metrics))

        report_lines.append(disp_stats(name, disp, gt_mask))
        report_lines.append(format_metric_line(name, metrics))
        report_lines.append("")

        safe_name = name.replace("-", "neg_")
        tif_path = os.path.join(out_dir, f"第四题_CREStereo_{safe_name}_fixed.tif")
        png_path = os.path.join(out_dir, f"第四题_CREStereo_{safe_name}_fixed.png")
        err_tif_path = os.path.join(out_dir, f"第四题_CREStereo_{safe_name}_error_fixed.tif")
        err_png_path = os.path.join(out_dir, f"第四题_CREStereo_{safe_name}_error_fixed.png")

        tiff.imwrite(tif_path, disp.astype(np.float32))
        tiff.imwrite(err_tif_path, metrics["error_map"].astype(np.float32))
        save_disp_png(disp, png_path, gt_mask)
        save_error_png(metrics["error_map"], err_png_path)

        if best_metrics is None or metrics["rmse"] < best_metrics["rmse"]:
            best_name = name
            best_disp = disp
            best_metrics = metrics

    print("\n最佳 CREStereo 输出：", best_name)
    print(format_metric_line(best_name, best_metrics))

    report_lines.append("四、最终采用的 CREStereo 结果")
    report_lines.append(f"最终采用输出：{best_name}")
    report_lines.append(format_metric_line(best_name, best_metrics))
    report_lines.append("说明：最终结果只在 channel0 的尺度和方向候选中选择，避免把近似全零的 channel1 误认为有效视差。")
    report_lines.append("")

    tiff.imwrite(out_best_disp_tif, best_disp.astype(np.float32))
    tiff.imwrite(out_best_error_tif, best_metrics["error_map"].astype(np.float32))
    save_disp_png(best_disp, out_best_disp_png, gt_mask)
    save_error_png(best_metrics["error_map"], out_best_error_png)

    # =====================================================
    # 与前三题比较：统一和老师 DSP 真值比较
    # =====================================================

    report_lines.append("五、与第一题、第二题、第三题结果对比（均与老师 DSP 真值比较）")
    report_lines.append(format_metric_line("第四题 CREStereo", best_metrics))

    print("\n========== 与老师 DSP 真值对比 ==========")
    print(format_metric_line("第四题 CREStereo", best_metrics))

    for title, path in compare_paths.items():
        if os.path.exists(path):
            disp = read_disp(path)
            if disp.shape != gt.shape:
                note = (
                    f"{title}: 视差图 {disp.shape} 与真值 {gt.shape} 尺寸不一致，"
                    "裁剪到公共区域后评价。"
                )
                print(note)
                report_lines.append(note)

            metrics = calc_metrics(disp, gt)
            print(format_metric_line(title, metrics))
            report_lines.append(format_metric_line(title, metrics))
        else:
            print(f"{title}: 未找到文件 {path}")
            report_lines.append(f"{title}: 未找到文件 {path}")

    report_lines.append("")
    report_lines.append("六、实验说明")
    report_lines.append(
        "本脚本采用开源 CREStereo ONNX 模型对两幅核线影像进行密集匹配。"
        "原始程序把 channel0、-channel0、channel1、-channel1 都作为候选视差比较，"
        "其中 channel1 的数值几乎为 0，因此虽然可能得到较小 RMSE，但本质上不是有效的密集匹配结果。"
        "修正后只采用 channel0 作为视差来源，并同时检查是否需要乘以宽度尺度系数以及是否需要取反。"
        "评价时只在老师 DSP 真值视差图的有效区域内计算 RMSE、MAE、Bad1 和 Bad3，自动跳过 -99999 等 NoData 像元。"
    )

    with open(out_report, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    print("\n========== 第四题完成（修正版） ==========")
    print("最佳视差图：", out_best_disp_tif)
    print("最佳视差可视化：", out_best_disp_png)
    print("误差图：", out_best_error_tif)
    print("误差可视化：", out_best_error_png)
    print("报告：", out_report)
