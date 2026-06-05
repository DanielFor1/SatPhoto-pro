# -*- coding: utf-8 -*-
"""平行投影模型（仿射近似）逼近 RPC，用于加速正射纠正。

平行投影模型（教材 P63 公式 2.97）在局部可写为对象空间到像方的仿射变换。
本实现以 RPC 归一化坐标 (L=归一化经度, P=归一化纬度, H=归一化高程) 为自变量，
拟合 8 参数仿射：
    sample = a0 + a1*L + a2*P + a3*H
    line   = b0 + b1*L + b2*P + b3*H
参数由 RPC 生成的虚拟控制格网（教材 P86）最小二乘解算。

forward() 接口与 RPCModel.forward 一致，可直接代入 ortho.orthorectify。
每像素仅需少量乘加、无有理多项式与除法，故比 RPC 正解快。
"""
import numpy as np


class ParallelProjection:
    def __init__(self, rpc):
        self.rpc = rpc
        self.a = None     # sample 系数 [a0,a1,a2,a3]
        self.b = None     # line   系数 [b0,b1,b2,b3]
        self.fit_rmse = None

    @staticmethod
    def _design(L, P, H):
        ones = np.ones_like(L)
        return np.column_stack([ones, L, P, H])      # (n,4)

    def fit(self, lon_rng, lat_rng, h_rng, n_xy=21, n_h=5):
        """用 RPC 在给定经纬高范围生成虚拟控制点，最小二乘拟合仿射参数。"""
        r = self.rpc
        LON, LAT, Hh, line, samp = r.grid_points(lon_rng, lat_rng, h_rng, n_xy, n_h)
        L = (LON - r.lon_off) / r.lon_scale
        P = (LAT - r.lat_off) / r.lat_scale
        H = (Hh - r.h_off) / r.h_scale
        M = self._design(L, P, H)
        self.a, *_ = np.linalg.lstsq(M, samp, rcond=None)
        self.b, *_ = np.linalg.lstsq(M, line, rcond=None)
        # 拟合残差（虚拟控制点上）
        ds = M @ self.a - samp
        dl = M @ self.b - line
        self.fit_rmse = (float(np.sqrt(np.mean(dl ** 2))),
                         float(np.sqrt(np.mean(ds ** 2))))
        return self

    def forward(self, lat, lon, height):
        """地面点 -> 像点(line, sample)，与 RPCModel.forward 同接口。"""
        r = self.rpc
        L = (np.asarray(lon, float) - r.lon_off) / r.lon_scale
        P = (np.asarray(lat, float) - r.lat_off) / r.lat_scale
        H = (np.asarray(height, float) - r.h_off) / r.h_scale
        a, b = self.a, self.b
        samp = a[0] + a[1] * L + a[2] * P + a[3] * H
        line = b[0] + b[1] * L + b[2] * P + b[3] * H
        return line, samp
