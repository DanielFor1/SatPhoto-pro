# -*- coding: utf-8 -*-
"""根据屏幕 DPI 与窗口尺寸动态缩放界面字体与控件。"""

from __future__ import annotations

import re
from pathlib import Path

from PyQt5.QtWidgets import QApplication

QSS_PATH = Path(__file__).resolve().parent / "styles.qss"
_BASE_QSS = QSS_PATH.read_text(encoding="utf-8") if QSS_PATH.is_file() else ""


def compute_ui_scale(app: QApplication | None = None, width: int = 1280, height: int = 820) -> float:
    """主要按屏幕 DPI 缩放字体；窗口变大时仅轻微放大，避免侧栏字过大。"""
    app = app or QApplication.instance()
    dpi = 96.0
    if app is not None:
        screen = app.primaryScreen()
        if screen is not None:
            dpi = float(screen.logicalDotsPerInchX())
    dpi_boost = max(0.0, dpi / 96.0 - 1.0) * 0.35
    geom = min(max(width, 1) / 1280.0, max(height, 1) / 820.0)
    geom_boost = max(0.0, geom - 1.0) * 0.08
    return max(1.0, min(1.22, 1.0 + dpi_boost + geom_boost))


def scaled_stylesheet(scale: float) -> str:
    """将 QSS 中所有 px 数值按 scale 等比放大。"""
    base = QSS_PATH.read_text(encoding="utf-8") if QSS_PATH.is_file() else _BASE_QSS
    if not base:
        return ""

    def _repl(match: re.Match[str]) -> str:
        value = float(match.group(1))
        return f"{max(1, int(round(value * scale)))}px"

    return re.sub(r"(\d+(?:\.\d+)?)px", _repl, base)


def sidebar_width(window_width: int, scale: float) -> int:
    """侧栏约占窗口 22%，限制在 380–440px，避免占屏过多。"""
    proportional = int(window_width * 0.22)
    return max(380, min(proportional, 440))
