# -*- coding: utf-8 -*-
"""SatPhoto-Pro Qt 入口。"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
LOG = ROOT / "suite_startup.log"


def main() -> None:
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        from photogrammetry_suite.qt_app.main_window import run_qt_app
        run_qt_app()
    except Exception:
        err = traceback.format_exc()
        LOG.write_text(err, encoding="utf-8")
        try:
            from PyQt5.QtWidgets import QApplication, QMessageBox
            app = QApplication(sys.argv)
            QMessageBox.critical(None, "SatPhoto-Pro 启动失败", f"{err[:1200]}\n\n详见 {LOG}")
        except Exception:
            print(err, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
