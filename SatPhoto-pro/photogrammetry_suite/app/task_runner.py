# -*- coding: utf-8 -*-
"""后台任务执行器 — 在独立线程中运行各 Task 适配器，实时推送日志。"""

from __future__ import annotations

import io
import sys
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class TaskState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult:
    state: TaskState
    message: str = ""
    detail: str = ""


class LogCapture(io.StringIO):
    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self._callback = callback

    def write(self, s: str) -> int:
        super().write(s)
        if s:
            self._callback(s)
        return len(s)


class TaskRunner:
    """在后台线程执行任务，避免 GUI 冻结。"""

    def __init__(self, log_callback: Callable[[str], None] | None = None) -> None:
        self._log = log_callback or print
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self.state = TaskState.IDLE
        self.result = TaskResult(TaskState.IDLE)

    @property
    def is_running(self) -> bool:
        return self.state == TaskState.RUNNING

    def cancel(self) -> None:
        self._cancel.set()
        self._log("\n[系统] 已请求取消（当前步骤完成后停止）\n")

    def run(self, func: Callable[[], str | None], on_done: Callable[[TaskResult], None] | None = None) -> None:
        if self.is_running:
            self._log("[系统] 已有任务在运行\n")
            return

        def _worker() -> None:
            self.state = TaskState.RUNNING
            self._cancel.clear()
            buf = LogCapture(self._log)
            try:
                with redirect_stdout(buf), redirect_stderr(buf):
                    msg = func()
                if self._cancel.is_set():
                    self.result = TaskResult(TaskState.CANCELLED, "用户取消")
                else:
                    self.result = TaskResult(TaskState.SUCCESS, msg or "完成")
                self.state = TaskState.SUCCESS if self.result.state == TaskState.SUCCESS else self.result.state
            except Exception as exc:
                detail = traceback.format_exc()
                self._log(f"\n[错误] {exc}\n{detail}\n")
                self.result = TaskResult(TaskState.FAILED, str(exc), detail)
                self.state = TaskState.FAILED
            finally:
                if on_done:
                    on_done(self.result)

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()
