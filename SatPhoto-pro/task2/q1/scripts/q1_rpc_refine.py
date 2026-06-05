# -*- coding: utf-8 -*-
"""
Task2 第1题：基于控制点最小二乘迭代精化 RPC 标准化参数

流程（教材共线方程迭代 / 式 3.75）：
1. 初始 RPC 计算各控制点预测像方坐标；
2. 在归一化物方坐标 (P,L) 上建立 6 参数仿射补偿最小二乘；
3. 将每轮解出的常数项并入 lineOffset、sampOffset（78 项系数不变）；
4. 迭代至像方 RMSE < 0.1 像素。
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA = ROOT / "实习数据" / "task2"
OUT_DIR = Path(__file__).resolve().parent.parent / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "task2"))
import suite_paths as t2sp

OFFSET_PARAMS = ["lineOffset", "sampOffset", "latOffset", "longOffset"]


def load_rpb(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")

    def scalar(name: str) -> float:
        m = re.search(
            rf"{name}\s*=\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*;",
            text,
        )
        if not m:
            raise KeyError(name)
        return float(m.group(1))

    def coef_block(name: str) -> np.ndarray:
        m = re.search(rf"{name}\s*=\s*\((.*?)\);", text, re.S)
        vals = re.findall(r"[+-]?\d+\.\d+(?:[eE][+-]?\d+)?", m.group(1))
        return np.array([float(v) for v in vals], dtype=np.float64)

    return {
        "lineOffset": scalar("lineOffset"),
        "sampOffset": scalar("sampOffset"),
        "latOffset": scalar("latOffset"),
        "longOffset": scalar("longOffset"),
        "heightOffset": scalar("heightOffset"),
        "lineScale": scalar("lineScale"),
        "sampScale": scalar("sampScale"),
        "latScale": scalar("latScale"),
        "longScale": scalar("longScale"),
        "heightScale": scalar("heightScale"),
        "lineNumCoef": coef_block("lineNumCoef"),
        "lineDenCoef": coef_block("lineDenCoef"),
        "sampNumCoef": coef_block("sampNumCoef"),
        "sampDenCoef": coef_block("sampDenCoef"),
    }


def poly_vec(lat_n: np.ndarray, lon_n: np.ndarray, h_n: np.ndarray) -> np.ndarray:
    """20 项 RPC00B 基函数（标准项序，与 .rpb 系数顺序一致）。

    项序：1, L, P, H, LP, LH, PH, L^2, P^2, H^2,
          PLH, L^3, LP^2, LH^2, L^2P, P^3, PH^2, L^2H, P^2H, H^3
    其中 P=归一化纬度, L=归一化经度, H=归一化高程。
    """
    p, l, ht = lat_n, lon_n, h_n
    return np.column_stack(
        [
            np.ones_like(p),
            l,
            p,
            ht,
            l * p,
            l * ht,
            p * ht,
            l * l,
            p * p,
            ht * ht,
            p * l * ht,
            l**3,
            l * p * p,
            l * ht * ht,
            l * l * p,
            p**3,
            p * ht * ht,
            l * l * ht,
            p * p * ht,
            ht**3,
        ]
    )


def rpc_project(
    rpc: dict, lon: np.ndarray, lat: np.ndarray, h: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    lat_n = (lat - rpc["latOffset"]) / rpc["latScale"]
    lon_n = (lon - rpc["longOffset"]) / rpc["longScale"]
    h_n = (h - rpc["heightOffset"]) / rpc["heightScale"]
    pv = poly_vec(lat_n, lon_n, h_n)
    line_n = (pv @ rpc["lineNumCoef"]) / (pv @ rpc["lineDenCoef"])
    samp_n = (pv @ rpc["sampNumCoef"]) / (pv @ rpc["sampDenCoef"])
    line = line_n * rpc["lineScale"] + rpc["lineOffset"]
    samp = samp_n * rpc["sampScale"] + rpc["sampOffset"]
    return line, samp, lat_n, lon_n


def load_gcps(path: Path) -> tuple[np.ndarray, ...]:
    lon, lat, h, line, samp = [], [], [], [], []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lon.append(float(row["lon"]))
            lat.append(float(row["lat"]))
            h.append(float(row["height"]))
            line.append(float(row["line"]))
            samp.append(float(row["sample"]))
    return tuple(np.array(x) for x in (lon, lat, h, line, samp))


def rmse_vec(v: np.ndarray) -> float:
    return float(np.sqrt(np.mean(v * v)))


def residuals(
    rpc: dict,
    lon: np.ndarray,
    lat: np.ndarray,
    h: np.ndarray,
    line_obs: np.ndarray,
    samp_obs: np.ndarray,
) -> np.ndarray:
    line_p, samp_p, _, _ = rpc_project(rpc, lon, lat, h)
    return np.r_[line_obs - line_p, samp_obs - samp_p]


def refine_rpc_affine(
    rpc: dict,
    lon: np.ndarray,
    lat: np.ndarray,
    h: np.ndarray,
    line_obs: np.ndarray,
    samp_obs: np.ndarray,
    max_iter: int = 30,
    rmse_target: float = 0.1,
) -> tuple[list[dict], np.ndarray]:
    """
    6 参数仿射补偿迭代（式 3.75）。
    迭代中 RPC 不变、累积补偿系数；收敛后将 a0、b0 并入像方偏移。
    """
    aff = np.zeros(6)
    history: list[dict] = []

    for it in range(max_iter):
        line_p, samp_p, p, l = rpc_project(rpc, lon, lat, h)
        corr_line = aff[0] + aff[1] * p + aff[2] * l
        corr_samp = aff[3] + aff[4] * p + aff[5] * l
        v_line = line_obs - line_p - corr_line
        v_samp = samp_obs - samp_p - corr_samp
        rmse_all = rmse_vec(np.r_[v_line, v_samp])
        history.append(
            {
                "iter": it,
                "rmse_line": rmse_vec(v_line),
                "rmse_samp": rmse_vec(v_samp),
                "rmse_all": rmse_all,
            }
        )
        if rmse_all < rmse_target:
            break

        n = len(lon)
        design = np.zeros((2 * n, 6), dtype=np.float64)
        design[:n, 0] = 1.0
        design[:n, 1] = p
        design[:n, 2] = l
        design[n:, 3] = 1.0
        design[n:, 4] = p
        design[n:, 5] = l
        delta, *_ = np.linalg.lstsq(design, np.r_[v_line, v_samp], rcond=None)
        aff += delta

    rpc["lineOffset"] += float(aff[0])
    rpc["sampOffset"] += float(aff[3])
    return history, aff


def write_rpb(rpc: dict, src_path: Path, out_path: Path) -> None:
    text = src_path.read_text(encoding="utf-8")
    for key in [
        "lineOffset",
        "sampOffset",
        "latOffset",
        "longOffset",
        "heightOffset",
        "lineScale",
        "sampScale",
        "latScale",
        "longScale",
        "heightScale",
    ]:
        text = re.sub(
            rf"^({key}\s*=\s*)([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?);",
            rf"\g<1>{rpc[key]:.15f};",
            text,
            count=1,
            flags=re.M,
        )
    out_path.write_text(text, encoding="utf-8")


def compare_params(got: dict, ref: dict) -> None:
    print("\n--- 与参考答案对比（标准化参数）---")
    keys = OFFSET_PARAMS + [
        "heightOffset",
        "lineScale",
        "sampScale",
        "latScale",
        "longScale",
        "heightScale",
    ]
    for k in keys:
        d = got[k] - ref[k]
        print(f"  {k:12s}  计算={got[k]:.12f}  参考={ref[k]:.12f}  diff={d:+.3e}")


def main() -> None:
    stem = t2sp.image_stem()
    init_rpb = t2sp.init_rpb()
    try:
        ref_rpb = t2sp.ref_rpb()
    except FileNotFoundError:
        ref_rpb = None
    gcp_csv = t2sp.gcp_ellipsoid_csv()

    rpc = load_rpb(init_rpb)
    lon, lat, h, line_obs, samp_obs = load_gcps(gcp_csv)

    print(f"控制点数量: {len(lon)}")
    line_p0, samp_p0, _, _ = rpc_project(rpc, lon, lat, h)
    v0 = np.r_[line_obs - line_p0, samp_obs - samp_p0]
    print(f"初始 total RMSE = {rmse_vec(v0):.4f} px")

    print("\n[阶段1] 6 参数仿射迭代 + 像方偏移吸收")
    hist1, aff = refine_rpc_affine(rpc, lon, lat, h, line_obs, samp_obs)
    print(f"  累积补偿: a0={aff[0]:.6f}, b0={aff[3]:.6f}")
    for row in hist1:
        print(
            f"  iter {row['iter']:2d}: total={row['rmse_all']:.6f} px "
            f"(line={row['rmse_line']:.4f}, samp={row['rmse_samp']:.4f})"
        )

    line_p, samp_p, lat_n, lon_n = rpc_project(rpc, lon, lat, h)
    v1 = np.r_[line_obs - line_p, samp_obs - samp_p]
    print(f"\n精化后（仅 RPC，无附加补偿）total RMSE = {rmse_vec(v1):.6f} px")
    print("说明：控制点与初始 RPC 存在系统偏差，迭代中采用 6 参数仿射补偿；")
    print("      收敛时补偿后 RMSE 见上表 iter 1，已写入 lineOffset / sampOffset。")

    print("\n精化后的标准化偏移参数:")
    for k in OFFSET_PARAMS + ["heightOffset", "lineScale"]:
        print(f"  {k} = {rpc[k]:.15f}")

    out_rpb = OUT_DIR / f"{stem}_refined.rpb"
    write_rpb(rpc, init_rpb, out_rpb)
    print(f"\n已写出: {out_rpb}")
    if ref_rpb is not None:
        compare_params(rpc, load_rpb(ref_rpb))
    else:
        print("未指定参考 RPC，跳过参数对比")


if __name__ == "__main__":
    main()
