# -*- coding: utf-8 -*-
"""EGM2008 大地水准面（高程异常 N）读取与双线性内插。

数据：GeographicLib 的 egm2008-5.pgm（5' 全球格网，16bit）。
头部含 Offset/Scale：高程异常 N = Offset + Scale * 像素原始值。
格网原点 90N/0E，经度 0..360、纬度 90..-90，分辨率 1/12 度。
索引（GeographicLib 约定）：col = lon360 * (W/360)，row = (90 - lat) * ((H-1)/180)。

正常高(H) -> 椭球高(h)：  h = H + N
"""
import re
import numpy as np


class EGM2008Geoid:
    def __init__(self, pgm_path):
        with open(pgm_path, "rb") as f:
            raw = f.read()

        # 解析 PGM (P5) 头部：magic、注释(含 Offset/Scale)、宽高、maxval
        assert raw[:2] == b"P5", "不是 P5 PGM 文件"
        pos = 2
        tokens = []           # 收集 width,height,maxval 三个数值 token
        self.offset = None
        self.scale = None
        while len(tokens) < 3:
            # 跳过空白
            while pos < len(raw) and raw[pos:pos + 1].isspace():
                pos += 1
            if raw[pos:pos + 1] == b"#":
                eol = raw.index(b"\n", pos)
                line = raw[pos:eol].decode("latin1")
                m = re.search(r"Offset\s+([-0-9.eE+]+)", line)
                if m:
                    self.offset = float(m.group(1))
                m = re.search(r"Scale\s+([-0-9.eE+]+)", line)
                if m:
                    self.scale = float(m.group(1))
                pos = eol + 1
            else:
                eol = pos
                while eol < len(raw) and not raw[eol:eol + 1].isspace():
                    eol += 1
                tokens.append(int(raw[pos:eol]))
                pos = eol
        self.width, self.height, maxval = tokens
        assert self.offset is not None and self.scale is not None, "缺少 Offset/Scale"
        pos += 1              # maxval 后单个空白符，随后为二进制数据

        n = self.width * self.height
        self.grid = np.frombuffer(raw, dtype=">u2", count=n, offset=pos).astype(
            np.float64).reshape(self.height, self.width)

        self.lon_res = self.width / 360.0          # 每度像素数(经度)
        self.lat_res = (self.height - 1) / 180.0   # 每度像素数(纬度)

    def undulation(self, lon, lat):
        """返回经纬度处的高程异常 N（米）。双线性内插，经度自动环绕。"""
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        lon360 = np.mod(lon, 360.0)
        fx = lon360 * self.lon_res
        fy = (90.0 - lat) * self.lat_res

        ix = np.floor(fx).astype(np.int64)
        iy = np.clip(np.floor(fy).astype(np.int64), 0, self.height - 2)
        dx = fx - ix
        dy = fy - iy
        ix0 = np.mod(ix, self.width)
        ix1 = np.mod(ix + 1, self.width)

        g = self.grid
        v00 = g[iy, ix0]
        v01 = g[iy, ix1]
        v10 = g[iy + 1, ix0]
        v11 = g[iy + 1, ix1]
        val = (v00 * (1 - dx) * (1 - dy) + v01 * dx * (1 - dy)
               + v10 * (1 - dx) * dy + v11 * dx * dy)
        return self.offset + self.scale * val
