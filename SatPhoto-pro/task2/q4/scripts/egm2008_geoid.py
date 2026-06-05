# -*- coding: utf-8 -*-
"""EGM2008 高程异常查询（pygeodesy + 本地 egm2008-1.pgm）。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pygeodesy.geoids import GeoidKarney

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def find_egm2008_pgm() -> Path:
    """查找本地 EGM2008 PGM 网格文件。"""
    search_dirs = [
        ROOT,
        ROOT / "task2" / "q4" / "data",
    ]
    names = ("egm2008-1.pgm", "EGM2008 - 1'.pgm", "EGM2008 - 1.pgm")
    for folder in search_dirs:
        for name in names:
            path = folder / name
            if path.is_file():
                return path
    matches = sorted(ROOT.glob("*EGM*.pgm"))
    if matches:
        return matches[0]
    raise FileNotFoundError(
        "未找到 EGM2008 PGM 文件。请将 egm2008-1.pgm 放在项目根目录或 task2/q4/data/ 下。"
    )


class EGM2008Geoid:
    """EGM2008 高程异常 N（米），满足 h_椭球 = H_正高 + N。"""

    def __init__(self, pgm_path: Path | None = None) -> None:
        self.pgm_path = pgm_path or find_egm2008_pgm()
        self._geoid = GeoidKarney(str(self.pgm_path))

    def close(self) -> None:
        self._geoid.close()

    def __enter__(self) -> EGM2008Geoid:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def height_anomaly(self, lat: np.ndarray | float, lon: np.ndarray | float) -> np.ndarray | float:
        """查询高程异常 N（lat, lon 单位：度）。"""
        lat_a = np.atleast_1d(np.asarray(lat, dtype=np.float64))
        lon_a = np.atleast_1d(np.asarray(lon, dtype=np.float64))
        out = np.empty(lat_a.shape, dtype=np.float64)
        for i, (la, lo) in enumerate(zip(lat_a, lon_a)):
            out[i] = float(self._geoid.height(float(la), float(lo)))
        return float(out[0]) if out.size == 1 else out

    def orthometric_to_ellipsoid(
        self,
        lat: np.ndarray | float,
        lon: np.ndarray | float,
        h_ortho: np.ndarray | float,
    ) -> np.ndarray | float:
        """正高/正常高 -> WGS84 椭球高。"""
        n = self.height_anomaly(lat, lon)
        if np.isscalar(h_ortho):
            return float(h_ortho) + float(n)  # type: ignore[arg-type]
        return np.asarray(h_ortho, dtype=np.float64) + np.asarray(n, dtype=np.float64)


if __name__ == "__main__":
    path = find_egm2008_pgm()
    print(f"PGM: {path.name} ({path.stat().st_size // 1024 // 1024} MB)")
    with EGM2008Geoid(path) as geoid:
        n = geoid.height_anomaly(30.3228647441, -81.6722135880)
        print(f"N(JAX) = {n:.4f} m")
