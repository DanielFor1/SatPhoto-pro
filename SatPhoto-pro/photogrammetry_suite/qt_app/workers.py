# -*- coding: utf-8 -*-
"""QThread 异步解算 worker。"""

from __future__ import annotations

import io
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from typing import Callable

from PyQt5.QtCore import QThread, pyqtSignal


@dataclass
class JobResult:
    ok: bool
    message: str
    input_preview: str = ""
    output_preview: str = ""


class _Stream(io.StringIO):
    def __init__(self, emit_fn: Callable[[str], None]) -> None:
        super().__init__()
        self._emit = emit_fn

    def write(self, s: str) -> int:
        super().write(s)
        if s:
            self._emit(s)
        return len(s)


class PipelineWorker(QThread):
    """在后台线程执行解算，通过信号更新 UI。"""

    log = pyqtSignal(str)
    status = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished_job = pyqtSignal(object)  # JobResult

    def __init__(self, job_fn: Callable[[], JobResult], parent=None) -> None:
        super().__init__(parent)
        self._job_fn = job_fn

    def run(self) -> None:
        self.progress.emit(5)
        self.status.emit("正在初始化解算引擎...")
        buf = _Stream(lambda s: self.log.emit(s))
        try:
            with redirect_stdout(buf), redirect_stderr(buf):
                self.progress.emit(15)
                result = self._job_fn()
            self.progress.emit(100)
            self.status.emit("解算完成" if result.ok else "解算失败")
            self.finished_job.emit(result)
        except Exception as exc:
            tb = traceback.format_exc()
            self.log.emit(f"\n[ERROR] {exc}\n{tb}\n")
            self.progress.emit(0)
            self.status.emit(f"错误: {exc}")
            self.finished_job.emit(JobResult(False, str(exc)))


class IndeterminateSpinner(QThread):
    """仅用于进度条不确定模式时的状态轮播（可选）。"""

    tick = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._running = True

    def run(self) -> None:
        i = 0
        while self._running:
            self.msleep(400)
            i = (i + 1) % 4
            self.tick.emit(i)

    def stop(self) -> None:
        self._running = False
