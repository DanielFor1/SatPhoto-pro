# -*- coding: utf-8 -*-
"""
Task4 适配器 — 五种立体匹配方法统一入口。

方法:
  1. census       — Census 变换 + 汉明距离
  2. gray_ncc     — 灰度归一化互相关
  3. stereo_bm    — OpenCV StereoBM（推荐，blockSize 关键参数）
  4. stereo_sgbm  — OpenCV StereoSGBM 优化版
  5. cres         — CREStereo ONNX（CPU，可换 GPU Provider）
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import tifffile as tiff

from photogrammetry_suite.config import PROJECT_ROOT, TASK4_ROOT, Task4StereoConfig, ensure_output_dirs, find_python, task_output_dir

DEFAULT_CRES_MODEL = (
    PROJECT_ROOT
    / "ONNX-CREStereo-Depth-Estimation-main"
    / "ONNX-CREStereo-Depth-Estimation-main"
    / "models"
    / "resources_iter20"
    / "crestereo_combined_iter20_480x640.onnx"
)


def _read_gray_tif(path: str | Path) -> np.ndarray:
    img = tiff.imread(str(path))
    if img.ndim == 3:
        if img.shape[0] <= 4:
            img = np.transpose(img, (1, 2, 0))
        if img.shape[2] >= 3:
            img = cv2.normalize(img[:, :, :3].astype(np.float32), None, 0, 255, cv2.NORM_MINMAX)
            img = cv2.cvtColor(img.astype(np.uint8), cv2.COLOR_RGB2GRAY)
        else:
            img = img[:, :, 0]
    img = cv2.normalize(img.astype(np.float32), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return img


def _read_disp(path: str | Path) -> np.ndarray:
    disp = tiff.imread(str(path)).astype(np.float32)
    return disp[:, :, 0] if disp.ndim == 3 else disp


def _search_range_from_gt(gt: np.ndarray, margin: int = 10) -> tuple[int, int, int, int]:
    valid = np.isfinite(gt) & (gt > -9999) & (gt < 9999)
    p1, p99 = np.percentile(gt[valid], [1, 99])
    min_user = int(np.floor(p1)) - margin
    max_user = int(np.ceil(p99)) + margin
    min_cv = -max_user
    num_disp = int(np.ceil((max_user - min_user + 1) / 16.0) * 16)
    return min_user, max_user, min_cv, num_disp


def run_stereo_bm(left: np.ndarray, right: np.ndarray, min_cv: int, num_disp: int, block_size: int = 15) -> np.ndarray:
    if block_size % 2 == 0:
        block_size += 1
    bm = cv2.StereoBM_create(numDisparities=num_disp, blockSize=block_size)
    bm.setMinDisparity(min_cv)
    bm.setTextureThreshold(5)
    bm.setUniquenessRatio(10)
    bm.setSpeckleWindowSize(100)
    bm.setSpeckleRange(2)
    bm.setDisp12MaxDiff(1)
    raw = bm.compute(left, right).astype(np.float32) / 16.0
    disp = -raw
    disp[raw <= (min_cv - 0.5)] = np.nan
    return disp


def run_stereo_sgbm(left: np.ndarray, right: np.ndarray, min_cv: int, num_disp: int, block_size: int = 5) -> np.ndarray:
    if block_size % 2 == 0:
        block_size += 1
    ch = 1
    sgbm = cv2.StereoSGBM_create(
        minDisparity=min_cv,
        numDisparities=num_disp,
        blockSize=block_size,
        P1=8 * ch * block_size * block_size,
        P2=32 * ch * block_size * block_size,
        disp12MaxDiff=1,
        uniquenessRatio=5,
        speckleWindowSize=100,
        speckleRange=2,
        preFilterCap=63,
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
    )
    raw = sgbm.compute(left, right).astype(np.float32) / 16.0
    disp = -raw
    disp[raw <= (min_cv - 0.5)] = np.nan
    return disp


def _crop_pair(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    """裁剪到两幅栅格公共区域（左上对齐）。"""
    h = min(a.shape[0], b.shape[0])
    w = min(a.shape[1], b.shape[1])
    return a[:h, :w], b[:h, :w], (h, w)


def _check_stereo_pair(left: np.ndarray, right: np.ndarray) -> None:
    if left.shape != right.shape:
        raise ValueError(
            f"左右核线影像尺寸不一致：左 {left.shape[:2]}，右 {right.shape[:2]}。"
            "请确保左右来自同一 Task3 输出或同一套参考 EPI。"
        )


def _align_for_metrics(pred: np.ndarray, gt: np.ndarray) -> tuple[np.ndarray, np.ndarray, str | None]:
    if pred.shape[:2] == gt.shape[:2]:
        return pred, gt, None
    note = (
        f"[警告] 真值视差 {gt.shape[:2]} 与解算视差 {pred.shape[:2]} 不一致，"
        f"已裁剪到公共区域 {min(pred.shape[0], gt.shape[0])}×"
        f"{min(pred.shape[1], gt.shape[1])} 再计算 RMSE。"
        "与 PDF 对比请统一数据源：全用 Task3 核线，或全用参考 EPI+DSP。"
    )
    gt_c, pred_c, _ = _crop_pair(gt, pred)
    print(note)
    return pred_c, gt_c, note


def _evaluate(pred: np.ndarray, gt: np.ndarray) -> dict:
    pred_use, gt_use, _ = _align_for_metrics(pred, gt)
    valid = np.isfinite(pred_use) & np.isfinite(gt_use) & (gt_use > -9999) & (gt_use < 9999)
    if not np.any(valid):
        return {"rmse": float("nan"), "mae": float("nan"), "valid": 0}
    err = pred_use[valid] - gt_use[valid]
    return {
        "valid": int(valid.sum()),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "mae": float(np.mean(np.abs(err))),
    }


def _task4_root(cfg: Task4StereoConfig) -> Path:
    return Path(cfg.output_dir or task_output_dir("task4"))


def _task4_subdir(cfg: Task4StereoConfig, name: str) -> Path:
    d = _task4_root(cfg) / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _method_subdir(method: str) -> str:
    return {
        "census": "q1",
        "gray_ncc": "q2",
        "stereo_bm": "q3",
        "stereo_sgbm": "q3",
        "cres": "q4",
    }.get(method.lower(), "q3")


def _write_task4_index(cfg: Task4StereoConfig) -> None:
    root = _task4_root(cfg)
    text = (
        "Task4 输出目录结构\n"
        "==================\n"
        "q1/  第一题 Census\n"
        "q2/  第二题 Gray NCC\n"
        "q3/  第三题 StereoBM / StereoSGBM（Task5 推荐视差也在此）\n"
        "q4/  第四题 CREStereo\n"
    )
    (root / "README_outputs.txt").write_text(text, encoding="utf-8")


def _suite_env_for_subdir(
    cfg: Task4StereoConfig,
    subdir: str,
    *,
    census_disp: str | Path = "",
    gray_disp: str | Path = "",
    bm_disp: str | Path = "",
    sgbm_disp: str | Path = "",
) -> dict:
    env = _suite_env(cfg)
    env["SUITE_OUT_DIR"] = str(_task4_subdir(cfg, subdir))
    if census_disp:
        env["SUITE_CENSUS_DISP"] = str(census_disp)
    if gray_disp:
        env["SUITE_GRAY_DISP"] = str(gray_disp)
    if bm_disp:
        env["SUITE_BM_DISP"] = str(bm_disp)
    if sgbm_disp:
        env["SUITE_SGBM_DISP"] = str(sgbm_disp)
    return env


def run_task4_stereo(cfg: Task4StereoConfig | None = None) -> str:
    """运行选定的立体匹配方法。"""
    ensure_output_dirs()
    cfg = cfg or Task4StereoConfig()
    method = cfg.method.lower()
    out_dir = _task4_subdir(cfg, _method_subdir(method))

    left_p = Path(cfg.left_epi)
    right_p = Path(cfg.right_epi)
    if not left_p.is_file() or not right_p.is_file():
        raise FileNotFoundError(f"核线影像不存在:\n  左: {left_p}\n  右: {right_p}")

    print(f"Task4 方法: {method}")
    print(f"  左影像: {left_p}")
    print(f"  右影像: {right_p}")
    print(f"  输出:   {out_dir}")

    if method in ("census", "gray_ncc", "cres"):
        return _run_legacy_script(method, cfg)

    # OpenCV BM / SGBM — 集成版，支持 blockSize 参数
    left = _read_gray_tif(left_p)
    right = _read_gray_tif(right_p)
    _check_stereo_pair(left, right)
    gt = None
    if cfg.gt_disp and Path(cfg.gt_disp).is_file():
        gt = _read_disp(cfg.gt_disp)
        if gt.shape[:2] != left.shape[:2]:
            print(
                f"[提示] 真值视差 {gt.shape[:2]} 与核线影像 {left.shape[:2]} 尺寸不同。"
                "搜索范围将按裁剪后的公共区域估计；完整检校请统一数据源。"
            )
            gt_crop, _, _ = _crop_pair(gt, left)
            _, _, min_cv, num_disp = _search_range_from_gt(gt_crop, cfg.search_margin)
        else:
            _, _, min_cv, num_disp = _search_range_from_gt(gt, cfg.search_margin)
    else:
        min_cv, num_disp = -128, 128
        print("[警告] 未提供真值视差，使用默认搜索范围")

    if method == "stereo_bm":
        print(f"  StereoBM blockSize = {cfg.bm_block_size}")
        disp = run_stereo_bm(left, right, min_cv, num_disp, cfg.bm_block_size)
        prefix = "StereoBM"
        out_tif = out_dir / "第三题_StereoBM_disparity_optimized.tif"
    elif method == "stereo_sgbm":
        print(f"  StereoSGBM blockSize = {cfg.sgbm_block_size}")
        disp = run_stereo_sgbm(left, right, min_cv, num_disp, cfg.sgbm_block_size)
        prefix = "StereoSGBM"
        out_tif = out_dir / "第三题_StereoSGBM_disparity_optimized.tif"
    else:
        raise ValueError(f"未知方法: {method}")

    # 保存视差（NaN → nodata）
    out_arr = disp.copy()
    out_arr[~np.isfinite(out_arr)] = -99999.0
    tiff.imwrite(str(out_tif), out_arr.astype(np.float32))
    print(f"已保存视差: {out_tif}")

    report_lines = [f"方法: {prefix}", f"输出: {out_tif}"]
    if gt is not None:
        metrics = _evaluate(disp, gt)
        report_lines.append(f"RMSE: {metrics['rmse']:.4f} px")
        report_lines.append(f"MAE:  {metrics['mae']:.4f} px")
        report_lines.append(f"有效像元: {metrics['valid']}")
        print(f"  RMSE = {metrics['rmse']:.4f} px, MAE = {metrics['mae']:.4f} px")

    report_path = out_dir / f"task4_{method}_report.txt"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    _write_task4_index(cfg)
    return f"Task4 {prefix} 完成 → {out_tif}"


def _suite_env(cfg: Task4StereoConfig) -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["SUITE_LEFT_EPI"] = cfg.left_epi
    env["SUITE_RIGHT_EPI"] = cfg.right_epi
    env["SUITE_GT_DISP"] = cfg.gt_disp or ""
    env["SUITE_OUT_DIR"] = cfg.output_dir or str(task_output_dir("task4"))
    return env


def _run_task4_script(
    script_name: str,
    cfg: Task4StereoConfig,
    *,
    optional: bool = False,
    env: dict | None = None,
) -> None:
    script = TASK4_ROOT / script_name
    if not script.is_file():
        raise FileNotFoundError(script)
    py = find_python()
    run_env = env if env is not None else _suite_env(cfg)
    print(f"执行: {py} {script}")
    proc = subprocess.run([py, str(script)], cwd=str(TASK4_ROOT), env=run_env)
    if proc.returncode != 0:
        if optional:
            print(f"[跳过] {script_name} 未成功（可选步骤），退出码 {proc.returncode}")
            return
        raise RuntimeError(f"{script.name} 失败，退出码 {proc.returncode}")


def run_task4_all(cfg: Task4StereoConfig | None = None) -> str:
    """按组员原始脚本顺序运行 Task4 全部 4 道小题（5 种算法）。"""
    ensure_output_dirs()
    cfg = cfg or Task4StereoConfig()
    q1 = _task4_subdir(cfg, "q1")
    q2 = _task4_subdir(cfg, "q2")
    q3 = _task4_subdir(cfg, "q3")
    q4 = _task4_subdir(cfg, "q4")

    steps = [
        ("第1题 Census", "census.py", False, _suite_env_for_subdir(cfg, "q1")),
        ("第2题 Gray NCC", "gray_ncc.py", False, _suite_env_for_subdir(cfg, "q2")),
        (
            "第3题 StereoBM + StereoSGBM",
            "opencv_bm_sgbm_optimized.py",
            False,
            _suite_env_for_subdir(
                cfg,
                "q3",
                census_disp=q1 / "第一题_census_disparity.tif",
                gray_disp=q2 / "第二题_gray_disparity.tif",
            ),
        ),
        (
            "第4题 CREStereo",
            "cres_task4_fixed.py",
            True,
            _suite_env_for_subdir(
                cfg,
                "q4",
                census_disp=q1 / "第一题_census_disparity.tif",
                gray_disp=q2 / "第二题_gray_disparity.tif",
                bm_disp=q3 / "第三题_StereoBM_disparity_optimized.tif",
                sgbm_disp=q3 / "第三题_StereoSGBM_disparity_optimized.tif",
            ),
        ),
    ]
    for title, script, optional, env in steps:
        print("\n" + "=" * 60)
        print(f">>> Task4 {title} ({script})")
        print("=" * 60)
        if script == "cres_task4_fixed.py":
            model = Path(os.environ.get("SUITE_CRES_MODEL") or DEFAULT_CRES_MODEL)
            if not model.is_file():
                print(f"[跳过] 未找到 CREStereo 模型: {model}")
                print("  请将 crestereo_combined_iter20_480x640.onnx 放到项目目录，或设置 SUITE_CRES_MODEL")
                continue
        _run_task4_script(script, cfg, optional=optional, env=env)

    _write_task4_index(cfg)
    bm = q3 / "第三题_StereoBM_disparity_optimized.tif"
    return f"Task4 全部算法完成，输出: {_task4_root(cfg)}（主链视差: {bm}）"


def _run_legacy_script(method: str, cfg: Task4StereoConfig) -> str:
    """通过子进程运行同学原始脚本。"""
    mapping = {
        "census": "census.py",
        "gray_ncc": "gray_ncc.py",
        "cres": "cres_task4_fixed.py",
    }
    script_name = mapping[method]
    print(f"Task4 运行原始脚本: {script_name}")
    if method == "cres":
        q1, q2, q3 = _task4_subdir(cfg, "q1"), _task4_subdir(cfg, "q2"), _task4_subdir(cfg, "q3")
        env = _suite_env_for_subdir(
            cfg,
            "q4",
            census_disp=q1 / "第一题_census_disparity.tif",
            gray_disp=q2 / "第二题_gray_disparity.tif",
            bm_disp=q3 / "第三题_StereoBM_disparity_optimized.tif",
            sgbm_disp=q3 / "第三题_StereoSGBM_disparity_optimized.tif",
        )
    else:
        env = _suite_env_for_subdir(cfg, _method_subdir(method))
    _run_task4_script(script_name, cfg, optional=(method == "cres"), env=env)
    _write_task4_index(cfg)
    return f"Task4 {method} 完成 → {_task4_subdir(cfg, _method_subdir(method))}"
