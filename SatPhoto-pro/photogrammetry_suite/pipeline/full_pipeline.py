# -*- coding: utf-8 -*-
"""全流程编排：从不准确 RPC 影像到准确 DOM / DSM 产品。

生产顺序（非简单的 1->2->3->4->5，而是符合摄影测量生产链）：

    [输入] 不准确 RPC 的立体像对 + 控制点 + 参考底图 + DEM(可选)
      │
      ├─ Task2  控制点匹配 / 像方仿射改正  ── 把"不准确 RPC"校正为"准确 RPC"
      │           └─ 产出 <stem>_refined.rpb（校正后 RPC），暂存为同名 .rpb
      │
      ├─ Task1  正射纠正（用校正后 RPC）   ── DOM 分支 → 准确 DOM
      │
      └─ Task3  核线纠正（用校正后 RPC）   ── DSM 分支起点
            └─ Task4 密集匹配 → 视差图
                  └─ Task5 前方交会 → 点云 → DSM → 准确 DSM

关键改动：把 Task2 的校正后 RPC 通过"同名 .rpb 暂存"喂给下游 Task1/Task3，
使整条链真正实现"不准确 RPC -> 准确产品"，而不是各自读原始 RPC 独立运行。
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

_SUITE = Path(__file__).resolve().parents[2]   # SatPhoto-pro
if str(_SUITE) not in sys.path:
    sys.path.insert(0, str(_SUITE))

from photogrammetry_suite.config import (  # noqa: E402
    TASK1_CODE, Task4StereoConfig, Task5CloudConfig, ensure_output_dirs, get_output_root, task_output_dir,
)
from photogrammetry_suite.pipeline.rpc_correct import correct_rpc  # noqa: E402


# --------------------------------------------------------------------------- 配置
@dataclass
class PipelineConfig:
    left_image: str = ""
    right_image: str = ""
    left_gcp: str = ""          # 左影像椭球高控制点 CSV
    right_gcp: str = ""         # 右影像椭球高控制点 CSV
    left_check: str = ""        # 左影像检查点 CSV（可选）
    right_check: str = ""       # 右影像检查点 CSV（可选）
    base_dom: str = ""          # 参考底图 DOM（Task2 匹配语境，可选）
    ref_dom_left: str = ""      # 左影像真值 DOM（对比用，可选）
    ref_dom_right: str = ""     # 右影像真值 DOM（对比用，可选）
    ref_dsm: str = ""           # 真值 DSM（对比用，可选）
    ref_dsp: str = ""           # 真值视差（对比用，可选）
    tie_csv: str = ""           # 同名点 CSV（Task5 Q1，可选；缺省由 BM 视差生成）
    dem: str = ""               # 外部 DEM（DOM 高程面，可选；缺省用常数高程面）
    output_root: str = ""       # 统一输出根目录，缺省 suite_outputs
    task4_method: str = "stereo_bm"
    task4_run_all: bool = False
    task5_stride: int = 2
    task5_workers: int = 8
    task5_intersection_method: str = "batch"
    task5_use_gpu: bool = False
    task5_chunk_size: int = 200000
    force: bool = False         # True 时即使已有产物也重算
    stages: tuple = ("rpc", "dom", "epipolar", "match", "dsm")

    def resolved_root(self) -> Path:
        return Path(self.output_root) if self.output_root else get_output_root()


# --------------------------------------------------------------------------- 工具
def _stem(p: str) -> str:
    return Path(p).stem


def _sibling_rpb(image: str) -> Path:
    return Path(image).with_suffix(".rpb")


def _read_kv(path: Path) -> dict:
    """解析 'key: value' 或 'key = value' 文本报告。"""
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        for sep in (":", "="):
            if sep in line:
                k, v = line.split(sep, 1)
                data[k.strip()] = v.strip()
                break
    return data


def _csv_first_row(path: Path) -> dict:
    import pandas as pd
    if not path.is_file():
        return {}
    df = pd.read_csv(path)
    if len(df) == 0:
        return {}
    return {k: (float(v) if isinstance(v, (int, float, np.integer, np.floating)) else v)
            for k, v in df.iloc[0].to_dict().items()}


def _phase_shift(img_a: np.ndarray, img_b: np.ndarray) -> dict:
    """返回 img_b 相对 img_a 的亚像素平移（cv2.phaseCorrelate）。"""
    import cv2

    def gray(x):
        x = np.asarray(x)
        if x.ndim == 3:
            x = x[..., :3].mean(axis=2)
        return x.astype(np.float32)

    a, b = gray(img_a), gray(img_b)
    h = min(a.shape[0], b.shape[0]); w = min(a.shape[1], b.shape[1])
    a, b = a[:h, :w], b[:h, :w]
    mask = (a > 0) & (b > 0)
    if mask.sum() < 0.05 * a.size:
        return {"dx": float("nan"), "dy": float("nan"), "shift_px": float("nan")}
    a = np.where(mask, a, 0.0); b = np.where(mask, b, 0.0)
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    (dx, dy), _ = cv2.phaseCorrelate(a, b, win)
    return {"dx": float(dx), "dy": float(dy), "shift_px": float(np.hypot(dx, dy))}


def _ncc(img_a: np.ndarray, img_b: np.ndarray) -> float:
    a = np.asarray(img_a, dtype=np.float64); b = np.asarray(img_b, dtype=np.float64)
    if a.ndim == 3:
        a = a[..., :3].mean(axis=2)
    if b.ndim == 3:
        b = b[..., :3].mean(axis=2)
    h = min(a.shape[0], b.shape[0]); w = min(a.shape[1], b.shape[1])
    a, b = a[:h, :w], b[:h, :w]
    m = (a > 0) & (b > 0)
    if m.sum() < 100:
        return float("nan")
    a, b = a[m], b[m]
    a = a - a.mean(); b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else float("nan")


# --------------------------------------------------------------------------- 阶段
def _stage_rpc(cfg: PipelineConfig, work: Path, log) -> dict:
    """Task2：校正左右影像的不准确 RPC，产出校正后 .rpb。"""
    rpc_dir = work / "01_rpc_corrected"
    rpc_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for side, image, gcp, check in (
        ("left", cfg.left_image, cfg.left_gcp, cfg.left_check),
        ("right", cfg.right_image, cfg.right_gcp, cfg.right_check),
    ):
        if not image or not gcp:
            log(f"  [{side}] 缺少影像或控制点，跳过 RPC 校正")
            continue
        dst_rpb = rpc_dir / f"{_stem(image)}_refined.rpb"
        res = correct_rpc(_sibling_rpb(image), gcp, dst_rpb, check or None, name=_stem(image))
        out[side] = asdict(res)
        log(f"  [{side}] {res.name}: 检查点 RMSE {res.rmse_before_check:.4f}px → {res.rmse_after_check:.4f}px"
            f"  (平移 dline={res.d_line:.3f}, dsamp={res.d_samp:.3f}; 完整仿射检查点={res.rmse_affine_check:.4f}px)")
    return out


def _stage_stage_inputs(cfg: PipelineConfig, work: Path, rpc_res: dict, log) -> dict:
    """把影像与校正后 RPC 暂存为同名对，供下游 Task1/Task3 读取（实现 RPC 传播）。"""
    staged = work / "02_staged_corrected"
    staged.mkdir(parents=True, exist_ok=True)
    info = {"dir": str(staged), "pairs": {}}
    for side, image in (("left", cfg.left_image), ("right", cfg.right_image)):
        if not image:
            continue
        stem = _stem(image)
        dst_tif = staged / f"{stem}.tif"
        dst_rpb = staged / f"{stem}.rpb"
        if cfg.force or not dst_tif.exists():
            shutil.copy2(image, dst_tif)
        refined = rpc_res.get(side, {}).get("out_rpb", "")
        if refined and Path(refined).is_file():
            shutil.copy2(refined, dst_rpb)
            corrected = True
        else:
            shutil.copy2(_sibling_rpb(image), dst_rpb)
            corrected = False
        info["pairs"][side] = {"image": str(dst_tif), "rpb": str(dst_rpb), "rpc_corrected": corrected}
        log(f"  [{side}] 暂存 {dst_tif.name} + {dst_rpb.name}（{'校正后RPC' if corrected else '原始RPC'}）")
    return info


def _ensure_task1_path() -> None:
    if str(TASK1_CODE) not in sys.path:
        sys.path.insert(0, str(TASK1_CODE))


def _ortho_one(rpb: Path, image: str, ref_dom: str, dem: str, out_tif: Path,
               grid_from_gcp: str = "", const_height: float | None = None) -> dict:
    """用给定 RPC 把影像正射到参考 DOM 网格（常数椭球高或外部 DEM）。"""
    _ensure_task1_path()
    import raster_io as rio
    import rpc as t1rpc
    import ortho as t1ortho

    model = t1rpc.RPCModel(str(rpb))
    if ref_dom and Path(ref_dom).is_file():
        spec = rio.dom_spec_from_reference(ref_dom, _stem(image))
    elif grid_from_gcp and Path(grid_from_gcp).is_file():
        import pandas as pd
        g = pd.read_csv(grid_from_gcp, encoding="utf-8-sig")
        g.columns = [c.strip().lower() for c in g.columns]
        res = 4.6e-6  # ~0.5m，与课程 DOM 分辨率量级一致
        left, right = g["lon"].min(), g["lon"].max()
        bottom, top = g["lat"].min(), g["lat"].max()
        spec = {"width": int((right - left) / res), "height": int((top - bottom) / res),
                "left": float(left), "top": float(top), "res_x": res, "res_y": res, "crs": "EPSG:4326"}
    else:
        raise FileNotFoundError("DOM 正射需要参考 DOM 或控制点 CSV 以确定输出网格")

    src = rio.read_tif(image)
    if dem and Path(dem).is_file() and Path(dem).with_suffix(".tfw").is_file():
        import dem as t1dem
        d = t1dem.DEM(dem, str(Path(dem).with_suffix(".tfw")))
        surface = lambda LON, LAT: d.interp(LON, LAT)  # noqa: E731
        hmode = "外部DEM"
    else:
        hval = float(const_height) if const_height is not None else float(model.h_off)
        surface = hval
        hmode = f"常数椭球高{hval:.1f}m"
    dom = t1ortho.orthorectify(model, src, spec, surface)
    out_tif.parent.mkdir(parents=True, exist_ok=True)
    rio.write_dom(str(out_tif), dom, spec["left"], spec["top"], spec["res_x"], spec["res_y"])
    return {"out": str(out_tif), "height_mode": hmode,
            "spec_wh": [spec["width"], spec["height"]], "array": dom}


def _stage_dom(cfg: PipelineConfig, work: Path, staged: dict, log) -> dict:
    """Task1：用校正后 RPC 正射 DOM；并做校正前/后与真值 DOM 的对齐对比。"""
    _ensure_task1_path()
    import raster_io as rio
    dom_dir = work / "03_dom"
    dom_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    sides = [("left", cfg.left_image, cfg.ref_dom_left, cfg.left_gcp),
             ("right", cfg.right_image, cfg.ref_dom_right, cfg.right_gcp)]
    for side, image, ref_dom, gcp in sides:
        if not image:
            continue
        stem = _stem(image)
        rec: dict = {"image": stem}
        try:
            # 用控制点平均椭球高作为常数高程面（无外部 DEM 时比 RPC h_off 更贴合实际地形）
            mh = None
            if gcp and Path(gcp).is_file():
                import pandas as pd
                gdf = pd.read_csv(gcp, encoding="utf-8-sig")
                gdf.columns = [c.strip().lower() for c in gdf.columns]
                if "height" in gdf.columns:
                    mh = float(gdf["height"].mean())
            # 校正后 RPC 正射
            corr_rpb = Path(staged["pairs"][side]["rpb"])
            after = _ortho_one(corr_rpb, image, ref_dom, cfg.dem,
                               dom_dir / f"{stem}_DOM_corrected.tif", gcp, const_height=mh)
            rec["corrected"] = {k: v for k, v in after.items() if k != "array"}
            # 校正前（原始 RPC）正射，用于"不准确->准确"对比
            before = _ortho_one(_sibling_rpb(image), image, ref_dom, cfg.dem,
                                dom_dir / f"{stem}_DOM_original.tif", gcp, const_height=mh)
            rec["original"] = {k: v for k, v in before.items() if k != "array"}
            # 与真值 DOM 对齐（同网格逐像素，phaseCorrelate 残余平移）
            if ref_dom and Path(ref_dom).is_file():
                ref_arr = rio.read_tif(ref_dom)
                rec["corrected"]["vs_ref"] = {**_phase_shift(ref_arr, after["array"]),
                                              "ncc": _ncc(ref_arr, after["array"])}
                rec["original"]["vs_ref"] = {**_phase_shift(ref_arr, before["array"]),
                                             "ncc": _ncc(ref_arr, before["array"])}
                log(f"  [{side}] DOM 对真值残余平移: 原始RPC={rec['original']['vs_ref']['shift_px']:.2f}px"
                    f" → 校正后={rec['corrected']['vs_ref']['shift_px']:.2f}px"
                    f"  (NCC {rec['original']['vs_ref']['ncc']:.3f}→{rec['corrected']['vs_ref']['ncc']:.3f})")
            else:
                log(f"  [{side}] 已生成 DOM（无真值 DOM，跳过对齐对比）：{after['height_mode']}")
        except Exception as exc:  # noqa: BLE001
            rec["error"] = str(exc)
            log(f"  [{side}] DOM 生成失败: {exc}")
        out[side] = rec
    return out


def _stage_epipolar(cfg: PipelineConfig, staged: dict, log) -> dict:
    """Task3：用校正后 RPC 做核线纠正（复用组员 run_task3_all 适配器）。"""
    from photogrammetry_suite.adapters import task3_adapter
    left = staged["pairs"]["left"]["image"]
    right = staged["pairs"]["right"]["image"]
    out34 = task_output_dir("task3") / "epipolar_rectification" / "epipolar_images_and_rpc"
    left_epi = out34 / f"{_stem(left)}_epipolar.tif"
    right_epi = out34 / f"{_stem(right)}_epipolar.tif"
    if cfg.force or not (left_epi.is_file() and right_epi.is_file()):
        task3_adapter.run_task3_epipolar(left=left, right=right,
                                         ground_csv=cfg.right_gcp or cfg.left_gcp, ref_dir="")
    vp = _read_kv(out34 / "vertical_parallax_report.txt")
    rpc_rep = (out34 / "rpc_consistency_report.txt")
    rpc_lines = [ln.strip() for ln in rpc_rep.read_text(encoding="utf-8", errors="replace").splitlines()
                 if "RMSE" in ln] if rpc_rep.is_file() else []
    res = {"out_dir": str(out34),
           "left_epi": str(left_epi), "right_epi": str(right_epi),
           "left_rpb": str(left_epi.with_suffix(".rpb")), "right_rpb": str(right_epi.with_suffix(".rpb")),
           "left_epi_exists": left_epi.is_file(), "right_epi_exists": right_epi.is_file(),
           "vertical_parallax_RMSE_v": vp.get("RMSE_v", ""),
           "rpc_consistency": rpc_lines}
    log(f"  核线竖直视差 RMSE_v = {res['vertical_parallax_RMSE_v']}")
    return res


def _stage_match(cfg: PipelineConfig, epi: dict, log) -> dict:
    """Task4：核线像对密集匹配（复用组员 task4 适配器）。"""
    from photogrammetry_suite.adapters import task4_adapter
    out4 = task_output_dir("task4")
    bm = out4 / "q3" / "第三题_StereoBM_disparity_optimized.tif"
    config = Task4StereoConfig(
        method=cfg.task4_method, bm_block_size=15, sgbm_block_size=5,
        left_epi=epi["left_epi"], right_epi=epi["right_epi"],
        gt_disp=cfg.ref_dsp, output_dir=str(out4),
    )
    if cfg.force or not bm.is_file():
        if cfg.task4_run_all:
            task4_adapter.run_task4_all(config)
        else:
            task4_adapter.run_task4_stereo(config)
    rep = _read_kv(out4 / "q3" / "task4_stereo_bm_report.txt")
    res = {"disparity": str(bm), "disparity_exists": bm.is_file(),
           "RMSE_px": rep.get("RMSE", ""), "MAE_px": rep.get("MAE", ""),
           "methods": {
               "census": (out4 / "q1" / "第一题_census_disparity.tif").is_file(),
               "gray_ncc": (out4 / "q2" / "第二题_gray_disparity.tif").is_file(),
               "stereo_bm": bm.is_file(),
               "stereo_sgbm": (out4 / "q3" / "第三题_StereoSGBM_disparity_optimized.tif").is_file(),
               "cres": (out4 / "q4" / "第四题_CREStereo_disparity_fixed.tif").is_file(),
           }}
    log(f"  StereoBM 视差 RMSE={res['RMSE_px']} MAE={res['MAE_px']}")
    return res


def _gen_tie_from_bm(disp_path: Path, left_name: str, right_name: str, out_csv: Path, max_points: int = 300) -> Path:
    """无配套同名点时，从 BM 视差稀疏抽样生成同名点 CSV（Task5 Q1 演示用）。"""
    import tifffile as tiff
    import pandas as pd
    disp = tiff.imread(str(disp_path)).astype(np.float32)
    if disp.ndim == 3:
        disp = disp[:, :, 0]
    h, w = disp.shape
    valid = np.isfinite(disp) & (disp > -9999) & (disp < 9999)
    rr, cc = np.indices(disp.shape)
    valid &= (cc + disp >= 0) & (cc + disp < w)
    valid[:40] = valid[-40:] = False
    valid[:, :40] = valid[:, -40:] = False
    sy, sx = max(1, h // 25), max(1, w // 25)
    gm = valid & (rr % sy == 0) & (cc % sx == 0)
    rows, cols = np.where(gm)
    if len(rows) == 0:
        rows, cols = np.where(valid)
    take = np.linspace(0, len(rows) - 1, min(max_points, len(rows)), dtype=int)
    rows, cols = rows[take].astype(float), cols[take].astype(float)
    dv = disp[rows.astype(int), cols.astype(int)].astype(float)
    df = pd.DataFrame({
        "id": [f"bm_{i:04d}" for i in range(len(rows))],
        f"image_{left_name}_line": rows, f"image_{left_name}_sample": cols,
        f"image_{right_name}_line": rows, f"image_{right_name}_sample": cols + dv,
    })
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    return out_csv


def _stage_dsm(cfg: PipelineConfig, epi: dict, match: dict, work: Path, log) -> dict:
    """Task5：前方交会 + 点云 + DSM（复用组员 task5 适配器），并做 Q1 同名点交会。"""
    from photogrammetry_suite.adapters import task5_adapter
    out5 = task_output_dir("task5")
    left_name = _stem(cfg.left_image)
    right_name = _stem(cfg.right_image)

    tie_csv = cfg.tie_csv
    if not tie_csv or not Path(tie_csv).is_file():
        tie_out = work / "04_tie_points" / f"{left_name}_vs_{right_name}_tie_from_bm.csv"
        if match.get("disparity_exists"):
            tie_csv = str(_gen_tie_from_bm(Path(match["disparity"]), left_name, right_name, tie_out))
            log(f"  无配套同名点，已从 BM 视差生成 {tie_csv}")

    cfg5 = Task5CloudConfig(
        stride=cfg.task5_stride,
        workers=cfg.task5_workers,
        intersection_method=cfg.task5_intersection_method,
        use_gpu=cfg.task5_use_gpu,
        chunk_size=cfg.task5_chunk_size,
        disp_path=match["disparity"], rpc_left=epi["left_rpb"], rpc_right=epi["right_rpb"],
        rgb_left=epi["left_epi"], tie_csv=tie_csv or "", grid_spec="",
        ref_dsm=cfg.ref_dsm, output_dir=str(out5),
    )
    metric_path = out5 / "metrics" / "dsm_tin_pure_masked_rmse.csv"
    if cfg.force or not metric_path.is_file():
        task5_adapter.run_task5_all(cfg5)

    res = {
        "tie_csv": tie_csv,
        "tie_intersected": (out5 / "tie_points" / "intersected_points.csv").is_file(),
        "point_cloud": (out5 / "point_cloud" / "point_cloud.csv").is_file(),
        "dsm_idw": str(out5 / "dsm" / "dsm_idw.tif"),
        "dsm_tin_pure_masked": str(out5 / "dsm" / "dsm_tin_pure_masked.tif"),
        "dsm_tin_hybrid": str(out5 / "dsm" / "dsm_tin_hybrid.tif"),
        "metrics": {
            "IDW": _csv_first_row(out5 / "metrics" / "dsm_idw_rmse.csv"),
            "PureTIN": _csv_first_row(out5 / "metrics" / "dsm_tin_pure_masked_rmse.csv"),
            "TIN_hybrid": _csv_first_row(out5 / "metrics" / "dsm_tin_hybrid_rmse.csv"),
        },
    }
    for label, m in res["metrics"].items():
        if m:
            log(f"  DSM {label}: RMSE={m.get('rmse_m', 'NA')} m  MAE={m.get('mae_m', 'NA')} m")
    return res


# --------------------------------------------------------------------------- 主流程
def run_full_pipeline(cfg: PipelineConfig, log=print) -> dict:
    t0 = time.time()
    root = cfg.resolved_root()
    ensure_output_dirs(root)
    work = root / "pipeline"
    work.mkdir(parents=True, exist_ok=True)
    result: dict = {"config": asdict(cfg), "stages": {}, "ok": {}}

    log("=" * 64)
    log("SatPhoto-Pro 全流程：不准确 RPC → 准确 DOM / DSM")
    log(f"左影像={_stem(cfg.left_image)}  右影像={_stem(cfg.right_image)}")
    log("=" * 64)

    rpc_res: dict = {}
    if "rpc" in cfg.stages:
        log("\n[1/5] Task2 控制点 / RPC 校正  ——  把不准确 RPC 校正为准确 RPC")
        try:
            rpc_res = _stage_rpc(cfg, work, log)
            result["stages"]["task2_rpc"] = rpc_res
            result["ok"]["task2_rpc"] = bool(rpc_res)
        except Exception as exc:  # noqa: BLE001
            log(f"  [错误] {exc}"); result["ok"]["task2_rpc"] = False

    staged: dict = {}
    try:
        log("\n[*] 暂存校正后 RPC（同名 .rpb 传播给下游 Task1/Task3）")
        staged = _stage_stage_inputs(cfg, work, rpc_res, log)
        result["stages"]["staged"] = staged
    except Exception as exc:  # noqa: BLE001
        log(f"  [错误] 暂存失败: {exc}")

    if "dom" in cfg.stages and staged.get("pairs"):
        log("\n[2/5] Task1 正射纠正（用校正后 RPC）—— DOM 分支")
        try:
            result["stages"]["task1_dom"] = _stage_dom(cfg, work, staged, log)
            result["ok"]["task1_dom"] = True
        except Exception as exc:  # noqa: BLE001
            log(f"  [错误] {exc}"); result["ok"]["task1_dom"] = False

    epi: dict = {}
    if "epipolar" in cfg.stages and staged.get("pairs"):
        log("\n[3/5] Task3 核线纠正（用校正后 RPC）—— DSM 分支起点")
        try:
            epi = _stage_epipolar(cfg, staged, log)
            result["stages"]["task3_epipolar"] = epi
            result["ok"]["task3_epipolar"] = epi.get("left_epi_exists") and epi.get("right_epi_exists")
        except Exception as exc:  # noqa: BLE001
            log(f"  [错误] {exc}"); result["ok"]["task3_epipolar"] = False

    match: dict = {}
    if "match" in cfg.stages and epi.get("left_epi_exists"):
        log("\n[4/5] Task4 密集匹配 —— 视差图")
        try:
            match = _stage_match(cfg, epi, log)
            result["stages"]["task4_match"] = match
            result["ok"]["task4_match"] = match.get("disparity_exists", False)
        except Exception as exc:  # noqa: BLE001
            log(f"  [错误] {exc}"); result["ok"]["task4_match"] = False

    if "dsm" in cfg.stages and match.get("disparity_exists"):
        log("\n[5/5] Task5 前方交会 → 点云 → DSM —— DSM 分支")
        try:
            result["stages"]["task5_dsm"] = _stage_dsm(cfg, epi, match, work, log)
            result["ok"]["task5_dsm"] = True
        except Exception as exc:  # noqa: BLE001
            log(f"  [错误] {exc}"); result["ok"]["task5_dsm"] = False

    result["elapsed_sec"] = round(time.time() - t0, 2)
    result["all_ok"] = all(result["ok"].values()) if result["ok"] else False
    (work / "pipeline_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log("\n" + "=" * 64)
    log(f"全流程结束，用时 {result['elapsed_sec']}s；结果 JSON: {work / 'pipeline_result.json'}")
    log("各阶段状态: " + ", ".join(f"{k}={'OK' if v else 'FAIL'}" for k, v in result["ok"].items()))
    log("=" * 64)
    return result
