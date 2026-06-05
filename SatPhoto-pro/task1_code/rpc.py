# -*- coding: utf-8 -*-
"""RPC 模型解析与正解（地面 -> 像方）。

仅需正解：给定经纬度+高程，输出像点 (line, sample)。
正射纠正采用间接法（输出像素->地面->RPC正解->原图重采样），全程只用正解。

像素坐标约定：行=line(从上到下)，列=sample(从左到右)，左上角第一个像素中心为原点(0,0)。
参考：教材 P75 公式 3.1（RPC 正解形式）。
"""
import re
import numpy as np


class RPCModel:
    """从 .rpb 文件解析 RPC 模型并提供向量化正解。"""

    def __init__(self, rpb_path):
        text = open(rpb_path, "r", encoding="utf-8", errors="ignore").read()

        def scalar(name):
            m = re.search(name + r"\s*=\s*([-0-9.eE+]+)", text)
            if m is None:
                raise ValueError("缺少字段: " + name)
            return float(m.group(1))

        def coef(name):
            m = re.search(name + r"\s*=\s*\((.*?)\)", text, re.S)
            if m is None:
                raise ValueError("缺少系数: " + name)
            vals = [float(x) for x in re.findall(r"[-0-9.eE+]+", m.group(1))]
            if len(vals) != 20:
                raise ValueError(f"{name} 应有 20 项, 实得 {len(vals)}")
            return np.asarray(vals, dtype=np.float64)

        # 偏移与比例
        self.line_off = scalar("lineOffset")
        self.samp_off = scalar("sampOffset")
        self.lat_off = scalar("latOffset")
        self.lon_off = scalar("longOffset")
        self.h_off = scalar("heightOffset")
        self.line_scale = scalar("lineScale")
        self.samp_scale = scalar("sampScale")
        self.lat_scale = scalar("latScale")
        self.lon_scale = scalar("longScale")
        self.h_scale = scalar("heightScale")
        # 多项式系数（各 20 项）
        self.line_num = coef("lineNumCoef")
        self.line_den = coef("lineDenCoef")
        self.samp_num = coef("sampNumCoef")
        self.samp_den = coef("sampDenCoef")

    @staticmethod
    def _poly(c, P, L, H):
        """RPC00B 20 项三次多项式。

        变量：P=归一化纬度, L=归一化经度, H=归一化高程。
        项序：1, L, P, H, LP, LH, PH, L^2, P^2, H^2,
              PLH, L^3, LP^2, LH^2, L^2P, P^3, PH^2, L^2H, P^2H, H^3
        """
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

    def forward(self, lat, lon, height):
        """地面点(纬度, 经度, 高程) -> 像点(line, sample)。支持标量或同形 ndarray。"""
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        height = np.asarray(height, dtype=np.float64)

        P = (lat - self.lat_off) / self.lat_scale
        L = (lon - self.lon_off) / self.lon_scale
        H = (height - self.h_off) / self.h_scale

        line_n = self._poly(self.line_num, P, L, H) / self._poly(self.line_den, P, L, H)
        samp_n = self._poly(self.samp_num, P, L, H) / self._poly(self.samp_den, P, L, H)

        line = line_n * self.line_scale + self.line_off
        samp = samp_n * self.samp_scale + self.samp_off
        return line, samp

    # 便于第 5 题：给定经纬高范围生成虚拟控制点（用 RPC 正解作"真值"）
    def grid_points(self, lon_rng, lat_rng, h_rng, n_xy=20, n_h=5):
        lons = np.linspace(lon_rng[0], lon_rng[1], n_xy)
        lats = np.linspace(lat_rng[0], lat_rng[1], n_xy)
        hs = np.linspace(h_rng[0], h_rng[1], n_h)
        LON, LAT, H = np.meshgrid(lons, lats, hs, indexing="ij")
        LON, LAT, H = LON.ravel(), LAT.ravel(), H.ravel()
        line, samp = self.forward(LAT, LON, H)
        return LON, LAT, H, line, samp
