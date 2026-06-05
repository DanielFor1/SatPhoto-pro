# -*- coding: utf-8 -*-
"""可复用 UI 组件 — 一体化路径输入等。"""

from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _polish_widget(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


class PathInputRow(QWidget):
    """标签 + 输入框与「浏览」无缝融合的复合控件。"""

    def __init__(
        self,
        label: str,
        placeholder: str = "",
        on_browse=None,
        on_clear=None,
        show_clear: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._combo: QFrame | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(5)

        if label:
            lb = QLabel(label)
            lb.setObjectName("FieldLabel")
            root.addWidget(lb)

        combo = QFrame()
        combo.setObjectName("PathInputCombo")
        self._combo = combo
        row = QHBoxLayout(combo)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.edit = QLineEdit()
        self.edit.setObjectName("PathInputEdit")
        if placeholder:
            self.edit.setPlaceholderText(placeholder)
        self.edit.installEventFilter(self)

        self.browse_btn = QPushButton("浏览")
        self.browse_btn.setObjectName("BrowseInline")
        self.browse_btn.setCursor(Qt.PointingHandCursor)
        row.addWidget(self.edit, 1)
        row.addWidget(self.browse_btn)
        self.clear_btn: QPushButton | None = None
        if show_clear:
            self.clear_btn = QPushButton("清空")
            self.clear_btn.setObjectName("ClearInline")
            self.clear_btn.setCursor(Qt.PointingHandCursor)
            self.clear_btn.setToolTip("清除当前路径")
            if on_clear:
                self.clear_btn.clicked.connect(on_clear)
            else:
                self.clear_btn.clicked.connect(self._on_clear_clicked)
            row.addWidget(self.clear_btn)
        if on_browse:
            self.browse_btn.clicked.connect(on_browse)
        root.addWidget(combo)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.edit and self._combo is not None:
            if event.type() == QEvent.FocusIn:
                self._combo.setProperty("hasFocus", True)
                _polish_widget(self._combo)
            elif event.type() == QEvent.FocusOut:
                self._combo.setProperty("hasFocus", False)
                _polish_widget(self._combo)
        return super().eventFilter(obj, event)

    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str) -> None:
        self.edit.setText(text)

    def setReadOnly(self, ro: bool) -> None:
        self.edit.setReadOnly(ro)
        if self.clear_btn is not None:
            self.clear_btn.setEnabled(not ro)

    def _on_clear_clicked(self) -> None:
        self.edit.clear()

    def clear(self) -> None:
        self._on_clear_clicked()


class ControlCard(QFrame):
    """带标题的卡片容器。"""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ControlCard")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 14)
        self._layout.setSpacing(10)

        header = QLabel(title)
        header.setObjectName("CardTitle")
        self._layout.addWidget(header)

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._layout
