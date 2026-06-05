# -*- coding: utf-8 -*-
"""GIS 网格画布 + 影像预览。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPainter, QColor, QPixmap
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget, QFrame, QSizePolicy


class GridCanvas(QFrame):
    """带灰白网格背景的影像预览区。"""

    def __init__(self, title: str = "", placeholder: str = "暂无影像", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CanvasPanel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._title = title
        self._pixmap: QPixmap | None = None
        self._placeholder = placeholder

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("CanvasTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        self.image_label = QLabel(self._placeholder)
        self.image_label.setObjectName("CanvasPlaceholder")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(320, 240)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.image_label, 1)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.image_label.geometry()
        if rect.width() < 10:
            return
        grid = 18
        light = QColor(20, 24, 34)
        dark = QColor(13, 17, 26)
        for x in range(rect.left(), rect.right(), grid):
            for y in range(rect.top(), rect.bottom(), grid):
                gx = (x - rect.left()) // grid
                gy = (y - rect.top()) // grid
                painter.fillRect(x, y, grid, grid, light if (gx + gy) % 2 == 0 else dark)

    def set_image_path(self, path: str | None) -> None:
        if not path or not Path(path).is_file():
            self._pixmap = None
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(self._placeholder)
            self.image_label.setStyleSheet("")
            self.update()
            return
        pm = self._load_pixmap(path)
        if pm is None:
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(f"无法预览:\n{Path(path).name}")
            return
        self._pixmap = pm
        self._refresh_scaled()
        self.update()

    def _refresh_scaled(self) -> None:
        if self._pixmap is None:
            return
        sz = self.image_label.size()
        if sz.width() < 20 or sz.height() < 20:
            return
        scaled = self._pixmap.scaled(sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.image_label.setText("")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_scaled()

    @staticmethod
    def _load_pixmap(path: str) -> QPixmap | None:
        p = Path(path)
        suffix = p.suffix.lower()
        try:
            if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}:
                pm = QPixmap(str(p))
                return pm if not pm.isNull() else None
            if suffix in {".tif", ".tiff"}:
                try:
                    import tifffile
                    arr = tifffile.imread(str(p))
                except ImportError:
                    from osgeo import gdal
                    ds = gdal.Open(str(p))
                    arr = ds.ReadAsArray()
                if arr is None:
                    return None
                if arr.ndim == 3:
                    if arr.shape[0] <= 4:
                        arr = np.transpose(arr, (1, 2, 0))
                    if arr.shape[2] >= 3:
                        rgb = arr[:, :, :3].astype(np.float64)
                        rgb = (rgb - rgb.min()) / max(rgb.max() - rgb.min(), 1e-6) * 255
                        arr = rgb.astype(np.uint8)
                    else:
                        arr = arr[:, :, 0]
                if arr.ndim == 2:
                    arr = np.stack([arr, arr, arr], axis=-1)
                arr = np.ascontiguousarray(arr.astype(np.uint8))
                h, w, ch = arr.shape
                bytes_per_line = ch * w
                qimg = QImage(arr.tobytes(), w, h, bytes_per_line, QImage.Format_RGB888)
                return QPixmap.fromImage(qimg)
        except Exception:
            return None
        return None


class DualCanvasWidget(QWidget):
    """双屏对比：左输入 / 右成果。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CanvasArea")
        from PyQt5.QtWidgets import QHBoxLayout
        lay = QHBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(8, 8, 8, 8)
        self.left = GridCanvas(
            "原始影像（传感器方向）",
            placeholder="浏览选择输入影像",
        )
        self.right = GridCanvas(
            "正射成果（北向 DOM）",
            placeholder="解算完成后显示成果",
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.left, 1)
        lay.addWidget(self.right, 1)

    def configure(
        self,
        *,
        left_title: str,
        right_title: str,
        left_placeholder: str = "浏览选择输入影像",
        right_placeholder: str = "解算完成后显示成果",
    ) -> None:
        self.left.title_label.setText(left_title)
        self.right.title_label.setText(right_title)
        self.left._placeholder = left_placeholder
        self.right._placeholder = right_placeholder

    def clear(self) -> None:
        self.left.set_image_path(None)
        self.right.set_image_path(None)

    def set_input(self, path: str | None) -> None:
        self.left.set_image_path(path)

    def set_output(self, path: str | None) -> None:
        self.right.set_image_path(path)

    def set_previews(self, left: str | None, right: str | None) -> None:
        self.left.set_image_path(left)
        self.right.set_image_path(right)

    def apply_scale(self, scale: float) -> None:
        min_w = max(280, int(360 * scale))
        min_h = max(240, int(320 * scale))
        for panel in (self.left, self.right):
            panel.image_label.setMinimumSize(min_w, min_h)
            panel._refresh_scaled()
