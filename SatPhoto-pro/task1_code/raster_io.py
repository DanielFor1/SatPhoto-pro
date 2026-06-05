# -*- coding: utf-8 -*-
"""栅格 I/O：读源影像/DEM（tifffile），读写世界文件 .tfw，输出带地理参考的 DOM。

本机无 GDAL/rasterio，故用 tifffile 读像素，地理参考靠 .tfw + .prj 边文件，
ArcGIS 可直接识别 (tif + tfw + prj) 进行卷帘叠加。
"""
import os
import csv
import numpy as np
import tifffile

# ESRI 风格 WGS84 地理坐标系 WKT（EPSG:4326），写入 .prj 供 ArcGIS 识别
WGS84_WKT = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)


def read_tif(path):
    """读取 GeoTIFF 像素为 ndarray（不含地理参考）。"""
    return tifffile.imread(path)


def read_tfw(path):
    """读取世界文件 .tfw -> (A, D, B, E, C, F)。

    A=x 像元尺寸, E=y 像元尺寸(通常为负), C/F=左上角像素中心的地理坐标。
    地理坐标 -> 像素：col=(x-C)/A, row=(y-F)/E。
    """
    with open(path) as f:
        v = [float(x.strip()) for x in f.readlines()[:6]]
    A, D, B, E, C, F = v
    return A, D, B, E, C, F


def load_dom_spec(csv_path, image_name):
    """从 正射影像范围.csv 读取某影像的 DOM 输出规格。

    返回 dict: width,height,left,right,top,bottom,res_x,res_y,crs。
    注意 left/top 是边界（非像素中心）。
    """
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["image"] == image_name:
                return {
                    "width": int(row["width"]),
                    "height": int(row["height"]),
                    "left": float(row["left"]),
                    "right": float(row["right"]),
                    "top": float(row["top"]),
                    "bottom": float(row["bottom"]),
                    "res_x": float(row["res_x"]),
                    "res_y": float(row["res_y"]),
                    "crs": row["crs"],
                }
    raise ValueError("未找到影像规格: " + image_name)


def dom_spec_from_reference(dom_tif_path, image_name=None):
    """从参考 DOM 推导正射输出网格规格（优先 .tfw，否则读 GeoTIFF 内嵌地理参考）。"""
    base = os.path.splitext(dom_tif_path)[0]
    tfw = base + ".tfw"
    if os.path.isfile(tfw):
        res_x, _, _, res_y_neg, cx, cy = read_tfw(tfw)
        res_y = abs(res_y_neg)
        img = read_tif(dom_tif_path)
        height, width = img.shape[:2]
        left = cx - 0.5 * res_x
        top = cy + 0.5 * res_y
    else:
        try:
            from osgeo import gdal
        except ImportError as exc:
            raise FileNotFoundError(
                "参考 DOM 缺少 .tfw，且未安装 GDAL 读取内嵌地理参考"
            ) from exc
        ds = gdal.Open(str(dom_tif_path))
        if ds is None:
            raise FileNotFoundError("无法打开参考 DOM: " + str(dom_tif_path))
        gt = ds.GetGeoTransform()
        width, height = ds.RasterXSize, ds.RasterYSize
        res_x, res_y = abs(gt[1]), abs(gt[5])
        left = gt[0]
        top = gt[3]
        ds = None
    right = left + width * res_x
    bottom = top - height * res_y
    return {
        "width": width,
        "height": height,
        "left": left,
        "right": right,
        "top": top,
        "bottom": bottom,
        "res_x": res_x,
        "res_y": res_y,
        "crs": "EPSG:4326",
        "image": image_name or os.path.basename(base),
    }


def write_dom(path, array, left, top, res_x, res_y):
    """写出 DOM：tif + 同名 .tfw + .prj。

    left/top 为影像边界；.tfw 的 C/F 需为左上角像素中心，故 +0.5 像元。
    """
    tifffile.imwrite(path, array)
    base = os.path.splitext(path)[0]
    C = left + 0.5 * res_x           # 左上像素中心经度
    F = top - 0.5 * res_y            # 左上像素中心纬度
    with open(base + ".tfw", "w") as f:
        f.write(f"{res_x:.12f}\n0.0\n0.0\n{-res_y:.12f}\n{C:.12f}\n{F:.12f}\n")
    with open(base + ".prj", "w") as f:
        f.write(WGS84_WKT)
    return path
