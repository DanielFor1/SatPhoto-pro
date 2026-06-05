# -*- coding: utf-8 -*-
"""DEM 读取与双线性内插。

DEM 为 GeoTIFF + 世界文件 .tfw，存储正常高（水准高/正高）。
地理坐标 -> DEM 像素：col=(lon-C)/A, row=(lat-F)/E（C/F 为左上像素中心）。
对任意经纬度做双线性内插得高程 Z。
"""
import numpy as np
from scipy.ndimage import map_coordinates
import raster_io as rio


class DEM:
    def __init__(self, tif_path, tfw_path):
        self.data = rio.read_tif(tif_path).astype(np.float64)
        if self.data.ndim == 3:
            self.data = self.data[..., 0]
        self.A, self.D, self.B, self.E, self.C, self.F = rio.read_tfw(tfw_path)
        self.h, self.w = self.data.shape

    def interp(self, lon, lat):
        """对经纬度（标量或同形 ndarray）双线性内插高程，越界取最近邻。"""
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        col = (lon - self.C) / self.A
        row = (lat - self.F) / self.E
        Z = map_coordinates(self.data, [row.ravel(), col.ravel()],
                            order=1, mode="nearest")
        return Z.reshape(lon.shape)
