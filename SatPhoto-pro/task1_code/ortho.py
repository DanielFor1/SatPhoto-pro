# -*- coding: utf-8 -*-
"""间接法（反向映射）正射纠正核心。

流程（教材 P112）：
  遍历输出 DOM 每个像素 -> 由其中心地理坐标(lon,lat)与高程 Z 用 RPC 正解
  得到原始影像坐标(line,sample) -> 在原图上双线性内插灰度 -> 赋给该 DOM 像素。

整幅向量化构造坐标网格 + cv2.remap 双线性重采样，速度快。
像素中心约定：lon=left+(col+0.5)*res_x, lat=top-(row+0.5)*res_y。
"""
import numpy as np
import cv2


def dom_pixel_centers(spec):
    """返回 DOM 每个像素中心的经纬度网格 (LON, LAT)，形状均为 (height, width)。"""
    cols = np.arange(spec["width"])
    rows = np.arange(spec["height"])
    lon = spec["left"] + (cols + 0.5) * spec["res_x"]      # (W,)
    lat = spec["top"] - (rows + 0.5) * spec["res_y"]       # (H,)
    LON, LAT = np.meshgrid(lon, lat)                       # (H, W)
    return LON, LAT


def orthorectify(rpc, src_img, spec, height_surface, return_coords=False):
    """生成正射影像 DOM。

    rpc            : RPCModel
    src_img        : 原始影像 ndarray (H,W) 或 (H,W,C)
    spec           : DOM 规格 dict（load_dom_spec 返回）
    height_surface : 函数 (LON,LAT)->Z 高程面，或标量(常数高程)
    return_coords  : 若 True 额外返回 (line, samp) 坐标网格（第5题计时/对比用）
    """
    LON, LAT = dom_pixel_centers(spec)
    if np.isscalar(height_surface):
        Z = np.full(LON.shape, float(height_surface))
    else:
        Z = height_surface(LON, LAT)

    line, samp = rpc.forward(LAT, LON, Z)                  # 原图 行/列

    map_x = samp.astype(np.float32)                        # cv2: x=列=sample
    map_y = line.astype(np.float32)                        # cv2: y=行=line
    border = 0 if src_img.ndim == 2 else (0,) * src_img.shape[2]
    dom = cv2.remap(src_img, map_x, map_y, interpolation=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=border)

    if return_coords:
        return dom, line, samp
    return dom


def valid_mask(line, samp, src_shape):
    """落在原图范围内（可有效重采样）的像素掩膜。"""
    h, w = src_shape[0], src_shape[1]
    return (samp >= 0) & (samp <= w - 1) & (line >= 0) & (line <= h - 1)
