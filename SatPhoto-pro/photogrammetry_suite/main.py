# -*- coding: utf-8 -*-
"""
卫星摄影测量后端处理系统 — 启动入口
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

LOG_FILE = ROOT / "suite_startup.log"


def _show_error(msg: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("启动失败", msg)
        root.destroy()
    except Exception:
        print(msg, file=sys.stderr)


if __name__ == "__main__":
    try:
        from photogrammetry_suite.app.main_window import run_app
        run_app()
    except Exception:
        err = traceback.format_exc()
        LOG_FILE.write_text(err, encoding="utf-8")
        _show_error(f"程序启动出错，详情见:\n{LOG_FILE}\n\n{err[:800]}")
        sys.exit(1)
