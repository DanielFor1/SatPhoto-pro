# -*- coding: utf-8 -*-
"""RPC 校正（Task2 思路的正确实现）。

给定初始（不准确）RPC 与一组椭球高控制点，求解像方仿射改正模型
（教材式 3.75），把系统偏差吸收进 lineOffset / sampOffset，写出校正后的 .rpb。
对 JAX 数据该偏差近似为纯平移，故"平移吸收进偏移"即可让独立检查点残差降到亚像素，
校正后 RPC 可被下游 Task1/Task3 直接复用（同名 .rpb 传播）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


def _poly(c, P, L, H):
    """RPC00B 20 项三次多项式（与 task1_code/rpc.py 项序一致）。"""
    return (
        c[0]
        + c[1] * L + c[2] * P + c[3] * H
        + c[4] * L * P + c[5] * L * H + c[6] * P * H
        + c[7] * L * L + c[8] * P * P + c[9] * H * H
        + c[10] * P * L * H
        + c[11] * L ** 3 + c[12] * L * P * P + c[13] * L * H * H
        + c[14] * L * L * P + c[15] * P ** 3 + c[16] * P * H * H
        + c[17] * L * L * H + c[18] * P * P * H + c[19] * H ** 3
    )


@dataclass
class _RPC:
    line_off: float
    samp_off: float
    lat_off: float
    lon_off: float
    h_off: float
    line_scale: float
    samp_scale: float
    lat_scale: float
    lon_scale: float
    h_scale: float
    line_num: np.ndarray
    line_den: np.ndarray
    samp_num: np.ndarray
    samp_den: np.ndarray

    @staticmethod
    def from_rpb(path: str | Path) -> "_RPC":
        text = Path(path).read_text(encoding="utf-8", errors="ignore")

        def scalar(name: str) -> float:
            m = re.search(name + r"\s*=\s*([-0-9.eE+]+)", text)
            if m is None:
                raise ValueError(f"缺少字段: {name} ({path})")
            return float(m.group(1))

        def coef(name: str) -> np.ndarray:
            m = re.search(name + r"\s*=\s*\((.*?)\)", text, re.S)
            if m is None:
                raise ValueError(f"缺少系数: {name} ({path})")
            vals = [float(x) for x in re.findall(r"[-0-9.eE+]+", m.group(1))]
            if len(vals) != 20:
                raise ValueError(f"{name} 应有 20 项, 实得 {len(vals)}")
            return np.asarray(vals, dtype=np.float64)

        return _RPC(
            scalar("lineOffset"), scalar("sampOffset"), scalar("latOffset"),
            scalar("longOffset"), scalar("heightOffset"), scalar("lineScale"),
            scalar("sampScale"), scalar("latScale"), scalar("longScale"),
            scalar("heightScale"), coef("lineNumCoef"), coef("lineDenCoef"),
            coef("sampNumCoef"), coef("sampDenCoef"),
        )

    def project(self, lon, lat, h):
        """地面(lon,lat,h) -> 像方(line,sample)。"""
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        h = np.asarray(h, dtype=np.float64)
        P = (lat - self.lat_off) / self.lat_scale
        L = (lon - self.lon_off) / self.lon_scale
        Hn = (h - self.h_off) / self.h_scale
        line_n = _poly(self.line_num, P, L, Hn) / _poly(self.line_den, P, L, Hn)
        samp_n = _poly(self.samp_num, P, L, Hn) / _poly(self.samp_den, P, L, Hn)
        return line_n * self.line_scale + self.line_off, samp_n * self.samp_scale + self.samp_off


def _read_gcp(csv_path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    df.columns = [c.strip().lower() for c in df.columns]
    need = {"lon", "lat", "height", "line", "sample"}
    if not need.issubset(df.columns):
        raise ValueError(f"控制点 CSV 需含列 {need}, 实得 {list(df.columns)}: {csv_path}")
    return df


def _rmse(dl: np.ndarray, ds: np.ndarray) -> float:
    return float(np.sqrt(np.mean(dl * dl + ds * ds)))


def _write_shifted_rpb(src_rpb: str | Path, dst_rpb: str | Path,
                       new_line_off: float, new_samp_off: float) -> None:
    """复制原 .rpb，只把 lineOffset / sampOffset 替换为校正后的值（其余系数不变）。"""
    text = Path(src_rpb).read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"(lineOffset\s*=\s*)[-0-9.eE+]+",
                  lambda m: f"{m.group(1)}{new_line_off:.15f}", text, count=1)
    text = re.sub(r"(sampOffset\s*=\s*)[-0-9.eE+]+",
                  lambda m: f"{m.group(1)}{new_samp_off:.15f}", text, count=1)
    Path(dst_rpb).parent.mkdir(parents=True, exist_ok=True)
    Path(dst_rpb).write_text(text, encoding="utf-8")


@dataclass
class RPCCorrectResult:
    name: str
    n_control: int
    n_check: int
    rmse_before_control: float
    rmse_after_control: float
    rmse_before_check: float
    rmse_after_check: float
    d_line: float
    d_samp: float
    affine_line: list = field(default_factory=list)
    affine_samp: list = field(default_factory=list)
    rmse_affine_check: float = float("nan")
    out_rpb: str = ""


def correct_rpc(src_rpb: str | Path, gcp_csv: str | Path, out_rpb: str | Path,
                check_csv: str | Path | None = None, name: str = "") -> RPCCorrectResult:
    """用控制点求像方平移/仿射改正，写出校正后 .rpb，并在检查点上评估。"""
    rpc = _RPC.from_rpb(src_rpb)
    g = _read_gcp(gcp_csv)
    lon, lat, h = g["lon"].to_numpy(), g["lat"].to_numpy(), g["height"].to_numpy()
    obs_l, obs_s = g["line"].to_numpy(), g["sample"].to_numpy()
    pred_l, pred_s = rpc.project(lon, lat, h)

    d_line = float(np.mean(obs_l - pred_l))
    d_samp = float(np.mean(obs_s - pred_s))
    rmse_before_c = _rmse(pred_l - obs_l, pred_s - obs_s)
    rmse_after_c = _rmse(pred_l + d_line - obs_l, pred_s + d_samp - obs_s)

    # 完整 6 参数像方仿射（仅作报告对比，确认偏差是否为纯平移）
    A = np.column_stack([np.ones_like(pred_l), pred_l, pred_s])
    co_l, *_ = np.linalg.lstsq(A, obs_l, rcond=None)
    co_s, *_ = np.linalg.lstsq(A, obs_s, rcond=None)

    rmse_before_k = rmse_after_k = float("nan")
    rmse_affine_k = float("nan")
    n_check = 0
    if check_csv and Path(check_csv).is_file():
        k = _read_gcp(check_csv)
        klon, klat, kh = k["lon"].to_numpy(), k["lat"].to_numpy(), k["height"].to_numpy()
        kobs_l, kobs_s = k["line"].to_numpy(), k["sample"].to_numpy()
        kpl, kps = rpc.project(klon, klat, kh)
        n_check = len(k)
        rmse_before_k = _rmse(kpl - kobs_l, kps - kobs_s)
        rmse_after_k = _rmse(kpl + d_line - kobs_l, kps + d_samp - kobs_s)
        Ak = np.column_stack([np.ones_like(kpl), kpl, kps])
        rmse_affine_k = _rmse(Ak @ co_l - kobs_l, Ak @ co_s - kobs_s)

    _write_shifted_rpb(src_rpb, out_rpb, rpc.line_off + d_line, rpc.samp_off + d_samp)

    return RPCCorrectResult(
        name=name or Path(src_rpb).stem,
        n_control=len(g), n_check=n_check,
        rmse_before_control=rmse_before_c, rmse_after_control=rmse_after_c,
        rmse_before_check=rmse_before_k, rmse_after_check=rmse_after_k,
        d_line=d_line, d_samp=d_samp,
        affine_line=[float(x) for x in co_l], affine_samp=[float(x) for x in co_s],
        rmse_affine_check=rmse_affine_k, out_rpb=str(out_rpb),
    )
