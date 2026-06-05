# -*- coding: utf-8 -*-
"""
SatPhoto-Pro 主窗口 — 暗黑工业风三栏布局 + QThread 异步解算
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QProgressBar,
    QFileDialog,
)

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_RUNTIME_LOG = _ROOT / "suite_runtime.log"
_DEFAULT_TC = _ROOT.parent / "全流程测试用例"
_DEFAULT_LEFT = "JAX_Tile_163_RGB_011"
_DEFAULT_RIGHT = "JAX_Tile_163_RGB_007"

from photogrammetry_suite.config import (
    SuiteConfig,
    Task4StereoConfig,
    Task5CloudConfig,
    ensure_output_dirs,
    task_output_dir,
)
from photogrammetry_suite.qt_app.canvas import DualCanvasWidget
from photogrammetry_suite.qt_app.widgets import ControlCard, PathInputRow
from photogrammetry_suite.qt_app.ui_scale import (
    compute_ui_scale,
    scaled_stylesheet,
    sidebar_width,
)
from photogrammetry_suite.qt_app.workers import JobResult, PipelineWorker

MODULES = [
    ("pipeline", "★ 全流程\n一键"),
    ("task1", "Task1\n正射"),
    ("task2", "Task2\nRPC"),
    ("task3", "Task3\n核线"),
    ("task4", "Task4\n匹配"),
    ("task5", "Task5\n点云"),
]

IMAGE_EXTS = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp", ".webp"}
PLACEHOLDER = "点击「浏览」选择文件…"

PREVIEW_META = {
    "pipeline": {
        "hint": "全流程：Task2 校正不准确 RPC → Task1 DOM / Task3 核线 → Task4 视差 → Task5 DSM。左：左影像｜右：最终 DSM/DOM 成果",
        "left_title": "左影像（不准确 RPC）",
        "right_title": "最终成果（DSM / DOM）",
        "left_placeholder": "浏览选择左影像",
        "right_placeholder": "全流程完成后显示 DSM / DOM",
    },
    "task1": {
        "hint": "左：原始传感器影像　|　右：正射北向 DOM（与左图方向不同属正常，非显示错误）",
        "left_title": "原始影像（传感器方向）",
        "right_title": "正射成果（北向 DOM）",
        "left_placeholder": "浏览选择待纠正影像",
        "right_placeholder": "解算完成后显示正射 DOM",
    },
    "task2": {
        "hint": "左：待精化卫星影像　|　右：运行解算后显示 SIFT 匹配可视化（非参考 DOM）",
        "left_title": "待精化影像",
        "right_title": "SIFT 匹配结果",
        "left_placeholder": "浏览选择待纠正影像",
        "right_placeholder": "解算完成后显示匹配图",
    },
    "task3": {
        "hint": "左：左影像　|　右：核线纠正完成后显示右 EPI 成果",
        "left_title": "左影像",
        "right_title": "核线成果（右 EPI）",
        "left_placeholder": "浏览选择左影像",
        "right_placeholder": "解算完成后显示核线影像",
    },
    "task4": {
        "hint": "左：左核线 EPI　|　右：立体匹配视差图",
        "left_title": "左核线 EPI",
        "right_title": "视差图成果",
        "left_placeholder": "浏览选择左核线影像",
        "right_placeholder": "解算完成后显示视差图",
    },
    "task5": {
        "hint": "左：视差图或左 RGB　|　右：DSM 成果（点云为 PLY，此处预览栅格）",
        "left_title": "视差 / 左 RGB",
        "right_title": "DSM 栅格成果",
        "left_placeholder": "浏览选择视差图或 RGB",
        "right_placeholder": "解算完成后显示 DSM",
    },
}


class SatPhotoProWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SatPhoto-Pro 本地卫星摄影测量解算系统")
        self.resize(1280, 820)
        self.setMinimumSize(1024, 680)

        self.cfg = SuiteConfig.load()
        ensure_output_dirs(self.cfg.output_root)
        self._worker: PipelineWorker | None = None
        self._module = "task1"
        self._tab_buttons: list[QPushButton] = []
        self._session_output_ready: set[str] = set()
        self._ui_scale = 1.0
        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.timeout.connect(self._apply_ui_scale)

        root = QWidget()
        root.setObjectName("RootWidget")
        self.setCentralWidget(root)
        main_lay = QVBoxLayout(root)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        main_lay.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)
        sidebar = self._build_sidebar()
        self._sidebar = sidebar
        body.addWidget(sidebar)
        body.addWidget(self._build_center(), 1)
        main_lay.addLayout(body, 1)

        self._build_statusbar()
        self._reset_session_state()
        self._fill_pipeline_defaults(silent=True)
        self._select_module("pipeline")
        self._append_log("SatPhoto-Pro 系统就绪。全流程页已填入测试用例默认路径，可直接运行或手动替换。\n")
        self._append_log(f"当前输出目录: {self.cfg.output_root}\n")
        self._apply_ui_scale()

    def _collect_input_edits(self) -> list[QLineEdit]:
        edits: list[QLineEdit] = []
        for attr in (
            "tp_left", "tp_right", "tp_lgcp", "tp_rgcp", "tp_lchk", "tp_rchk",
            "tp_base_dom", "tp_ref_dom_l", "tp_ref_dom_r", "tp_ref_dsm", "tp_ref_dsp",
            "tp_dem", "tp_tie",
            "t1_image", "t1_dom", "t1_dem", "t1_dom_spec", "t1_ground",
            "t2_image", "t2_dom", "t2_dem", "t2_gcp", "t2_check", "t2_corners", "t2_ref_rpc",
            "t3_left", "t3_right", "t3_ground", "t3_ref",
            "t4_left", "t4_right", "t4_gt",
            "t5_disp", "t5_rpc_l", "t5_rpc_r", "t5_rgb",
            "t5_tie", "t5_grid", "t5_ref_dsm", "t5_ref_tie",
        ):
            w = getattr(self, attr, None)
            if isinstance(w, QLineEdit):
                edits.append(w)
        return edits

    def _reset_session_state(self) -> None:
        """启动时清空：不保留上次浏览路径、不加载磁盘历史成果。"""
        self._session_output_ready.clear()
        for edit in self._collect_input_edits():
            edit.clear()
        if hasattr(self, "log_console"):
            self.log_console.clear()
        if hasattr(self, "canvas"):
            self.canvas.clear()

    def _pipeline_default_paths(self) -> dict[str, str]:
        tc = _DEFAULT_TC
        truth = tc / "参考真值数据" / f"{_DEFAULT_LEFT}_vs_{_DEFAULT_RIGHT}"
        return {
            "tp_left": str(tc / f"{_DEFAULT_LEFT}.tif"),
            "tp_right": str(tc / f"{_DEFAULT_RIGHT}.tif"),
            "tp_lgcp": str(tc / f"{_DEFAULT_LEFT}_gcps_ellipsoid.csv"),
            "tp_rgcp": str(tc / f"{_DEFAULT_RIGHT}_gcps_ellipsoid.csv"),
            "tp_lchk": str(tc / f"{_DEFAULT_LEFT}_gcps_check.csv"),
            "tp_rchk": str(tc / f"{_DEFAULT_RIGHT}_gcps_check.csv"),
            "tp_base_dom": str(tc / "底图DOM" / "JAX_Tile_163_RGB_016_DOM.tif"),
            "tp_ref_dom_l": str(tc / "参考真值数据" / "DOM" / f"{_DEFAULT_LEFT}_DOM.tif"),
            "tp_ref_dom_r": str(tc / "参考真值数据" / "DOM" / f"{_DEFAULT_RIGHT}_DOM.tif"),
            "tp_ref_dsm": str(truth / f"{_DEFAULT_LEFT}_vs_{_DEFAULT_RIGHT}_DSM.tif"),
            "tp_ref_dsp": str(truth / f"{_DEFAULT_LEFT}_vs_{_DEFAULT_RIGHT}_DSP.tif"),
            "tp_dem": "",
            "tp_tie": "",
        }

    def _fill_pipeline_defaults(self, silent: bool = False) -> None:
        missing: list[str] = []
        for attr, value in self._pipeline_default_paths().items():
            edit = getattr(self, attr, None)
            if not isinstance(edit, QLineEdit):
                continue
            edit.setText(value)
            if value and not Path(value).exists():
                missing.append(value)
        if missing:
            self._append_log("测试用例默认路径中有文件不存在，请检查数据目录。\n")
            if not silent:
                QMessageBox.warning(self, "默认数据不完整", "部分默认测试用例文件不存在，请检查数据目录。")
        elif not silent:
            self._append_log("已填入测试用例默认数据路径。\n")

    def _apply_output_root(self, path: str) -> None:
        self.cfg.set_output_root(path)
        self.cfg.save()
        ensure_output_dirs(self.cfg.output_root)
        self.output_edit.setText(self.cfg.output_root)

    def _browse_output_dir(self) -> None:
        start = self._browse_start_dir(self.output_edit)
        path = QFileDialog.getExistingDirectory(self, "选择结果输出目录", start)
        if not path:
            return
        self._remember_browse_dir(path)
        self._apply_output_root(path)
        self._append_log(f"输出目录已设为: {path}\n")

    def _open_output_dir(self) -> None:
        root = Path(self.cfg.output_root)
        root.mkdir(parents=True, exist_ok=True)
        for name in ("task1", "task2", "task3", "task4", "task5"):
            (root / name).mkdir(parents=True, exist_ok=True)
        os.startfile(str(root))

    # ------------------------------------------------------------------ Header
    def _build_header(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("HeaderBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 14, 16, 14)

        logo = QLabel("SP")
        logo.setObjectName("LogoBadge")
        logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        t1 = QLabel("SatPhoto-Pro 本地卫星摄影测量解算系统")
        t1.setObjectName("AppTitle")
        t2 = QLabel("Satellite Photogrammetry Local Processing Suite")
        t2.setObjectName("AppSubtitle")
        title_box.addWidget(t1)
        title_box.addWidget(t2)
        lay.addLayout(title_box)
        lay.addSpacing(24)

        for key, label in MODULES:
            btn = QPushButton(label)
            btn.setObjectName("ModuleTab")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, k=key: self._select_module(k))
            self._tab_buttons.append(btn)
            lay.addWidget(btn)

        lay.addStretch(1)
        return bar

    # ------------------------------------------------------------------ Sidebar
    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        outer = QVBoxLayout(sidebar)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget()
        inner.setObjectName("SidebarInner")
        self.sidebar_lay = QVBoxLayout(inner)
        self.sidebar_lay.setContentsMargins(10, 10, 10, 10)
        self.sidebar_lay.setSpacing(10)

        out_card = ControlCard("结果输出")
        out_row_w = QWidget()
        out_h = QHBoxLayout(out_row_w)
        out_h.setContentsMargins(0, 0, 0, 0)
        out_h.setSpacing(8)
        self.output_row = PathInputRow(
            "",
            placeholder="选择解算结果保存位置…",
            on_browse=self._browse_output_dir,
            show_clear=False,
        )
        self.output_edit = self.output_row.edit
        self.output_edit.setReadOnly(True)
        self.output_edit.setText(self.cfg.output_root)
        out_open = QPushButton("打开")
        out_open.setObjectName("SecondaryBtn")
        out_open.setCursor(Qt.PointingHandCursor)
        out_open.clicked.connect(self._open_output_dir)
        out_h.addWidget(self.output_row, 1)
        out_h.addWidget(out_open)
        out_card.content_layout.addWidget(out_row_w)
        self.sidebar_lay.addWidget(out_card)

        self.sidebar_stack = QStackedWidget()
        self._panels = {}
        for key, _ in MODULES:
            self._panels[key] = self._make_module_panel(key)
            self.sidebar_stack.addWidget(self._panels[key])
        self.sidebar_lay.addWidget(self.sidebar_stack)

        log_card = ControlCard("运行日志")
        self.log_console = QTextEdit()
        self.log_console.setObjectName("LogConsole")
        self.log_console.setReadOnly(True)
        self.log_console.setMaximumHeight(130)
        log_card.content_layout.addWidget(self.log_console)
        self.sidebar_lay.addWidget(log_card)

        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        run_wrap = QFrame()
        run_wrap.setObjectName("RunCard")
        run_lay = QVBoxLayout(run_wrap)
        run_lay.setContentsMargins(0, 0, 0, 0)
        self.run_btn = QPushButton("▶  开始自动化解算")
        self.run_btn.setObjectName("PrimaryRunBtn")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.clicked.connect(self._on_run)
        run_lay.addWidget(self.run_btn)
        outer.addWidget(run_wrap)
        return sidebar

    def _make_module_panel(self, key: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        input_card = ControlCard("文件输入")
        input_lay = input_card.content_layout

        if key == "pipeline":
            self.tp_left = self._file_row(input_lay, "左影像 (.tif)", preview=True)
            self.tp_right = self._file_row(input_lay, "右影像 (.tif)")
            self.tp_lgcp = self._file_row(input_lay, "左控制点 CSV (椭球高)")
            self.tp_rgcp = self._file_row(input_lay, "右控制点 CSV (椭球高)")
            self.tp_lchk = self._file_row(input_lay, "左检查点 CSV (可选)")
            self.tp_rchk = self._file_row(input_lay, "右检查点 CSV (可选)")
            self.tp_base_dom = self._file_row(input_lay, "参考底图 DOM (可选)")
            self.tp_ref_dom_l = self._file_row(input_lay, "左真值 DOM (可选)")
            self.tp_ref_dom_r = self._file_row(input_lay, "右真值 DOM (可选)")
            self.tp_ref_dsm = self._file_row(input_lay, "参考 DSM (可选)", kind="tiff")
            self.tp_ref_dsp = self._file_row(input_lay, "参考视差 DSP (可选)", kind="tiff")
            self.tp_dem = self._file_row(input_lay, "外部 DEM (可选)", kind="tiff")
            self.tp_tie = self._file_row(input_lay, "同名点 CSV (可选)")
            fill_defaults = QPushButton("填入测试用例默认数据")
            fill_defaults.setCursor(Qt.PointingHandCursor)
            fill_defaults.clicked.connect(self._fill_pipeline_defaults)
            input_lay.addWidget(fill_defaults)
            lay.addWidget(input_card)
            pg = self._param_group("全流程阶段", [])
            self.tp_stage_checks = {}
            for k, lb in [("rpc", "① Task2 校正 RPC"), ("dom", "② Task1 DOM"),
                          ("epipolar", "③ Task3 核线"), ("match", "④ Task4 视差"),
                          ("dsm", "⑤ Task5 DSM")]:
                cb = QCheckBox(lb)
                cb.setChecked(True)
                self.tp_stage_checks[k] = cb
                pg.content_layout.addWidget(cb)
            gl2 = QGridLayout()
            pg.content_layout.addLayout(gl2)
            gl2.addWidget(QLabel("Task4 方法"), 0, 0)
            self.tp_t4_method = QComboBox()
            self.tp_t4_method.addItems(["StereoBM (推荐)", "StereoSGBM", "Census", "Gray NCC", "CREStereo"])
            gl2.addWidget(self.tp_t4_method, 0, 1)
            gl2.addWidget(QLabel("Task5 后端"), 1, 0)
            self.tp_t5_compute = QComboBox()
            gpu_ok, gpu_msg = self._task5_gpu_status()
            self.tp_t5_compute.addItems([
                "CPU 批量 (batch，推荐)",
                "CPU 多进程 (scipy)",
                f"GPU (CUDA + CuPy){'' if gpu_ok else ' — 不可用'}",
            ])
            if not gpu_ok:
                self.tp_t5_compute.model().item(2).setEnabled(False)
            self.tp_t5_compute.setCurrentIndex(0)
            gl2.addWidget(self.tp_t5_compute, 1, 1)
            tp_gpu_hint = QLabel(f"GPU: {gpu_msg}" if gpu_ok else f"无 GPU: {gpu_msg}，请选 CPU")
            tp_gpu_hint.setObjectName("MutedLabel")
            tp_gpu_hint.setWordWrap(True)
            pg.content_layout.addWidget(tp_gpu_hint)
            gl2.addWidget(QLabel("Task5 stride"), 2, 0)
            self.tp_t5_stride = QSpinBox()
            self.tp_t5_stride.setRange(1, 8)
            self.tp_t5_stride.setValue(2)
            gl2.addWidget(self.tp_t5_stride, 2, 1)
            gl2.addWidget(QLabel("Task5 workers"), 3, 0)
            self.tp_t5_workers = QSpinBox()
            self.tp_t5_workers.setRange(1, 32)
            self.tp_t5_workers.setValue(self.cfg.task5.workers)
            gl2.addWidget(self.tp_t5_workers, 3, 1)
            gl2.addWidget(QLabel("Task5 chunk_size"), 4, 0)
            self.tp_t5_chunk = QSpinBox()
            self.tp_t5_chunk.setRange(10000, 500000)
            self.tp_t5_chunk.setSingleStep(10000)
            self.tp_t5_chunk.setValue(max(10000, self.cfg.task5.chunk_size))
            gl2.addWidget(self.tp_t5_chunk, 4, 1)
            self.tp_t4_all = QCheckBox("Task4 运行全部 5 种算法")
            pg.content_layout.addWidget(self.tp_t4_all)
            self.tp_force = QCheckBox("强制重算（忽略已有产物）")
            self.tp_force.setChecked(True)
            pg.content_layout.addWidget(self.tp_force)
            lay.addWidget(pg)

        elif key == "task1":
            self.t1_image = self._file_row(input_lay, "待纠正影像 (.tif)", preview=True)
            self.t1_dom = self._file_row(input_lay, "参考底图 DOM (.tif)")
            self.t1_dem = self._file_row(input_lay, "DEM (.tif)")
            self.t1_dom_spec = self._file_row(input_lay, "正射范围 CSV (可选)")
            self.t1_ground = self._file_row(input_lay, "地面检核点 CSV (可选)")
            lay.addWidget(input_card)
            lay.addWidget(self._param_group("参数", []))

        elif key == "task2":
            self.t2_image = self._file_row(input_lay, "待纠正影像 (.tif)", preview=True)
            self.t2_dom = self._file_row(input_lay, "参考底图 DOM (.tif)")
            self.t2_dem = self._file_row(input_lay, "DEM (.tif)")
            self.t2_gcp = self._file_row(input_lay, "椭球高控制点 CSV")
            self.t2_check = self._file_row(input_lay, "检查点 CSV")
            self.t2_corners = self._file_row(input_lay, "四角点 CSV")
            self.t2_ref_rpc = self._file_row(input_lay, "参考 RPC (.rpb，可选)", kind="rpb")
            lay.addWidget(input_card)
            self.t2_checks = {}
            pg = self._param_group("运行步骤", [])
            for k, lb in [("q1", "Q1 RPC精化"), ("q2", "Q2 SIFT匹配"), ("q3", "Q3 DEM"),
                          ("q4", "Q4 椭球高"), ("q5", "Q5 粗差剔除")]:
                cb = QCheckBox(lb)
                cb.setChecked(True)
                self.t2_checks[k] = cb
                pg.content_layout.addWidget(cb)
            lay.addWidget(pg)

        elif key == "task3":
            self.t3_left = self._file_row(input_lay, "左影像 (.tif)", preview=True)
            self.t3_right = self._file_row(input_lay, "右影像 (.tif)")
            self.t3_ground = self._file_row(input_lay, "地面检核点 CSV")
            self.t3_ref = self._file_row(input_lay, "参考核线目录 (可选)", kind="dir")
            lay.addWidget(input_card)
            self.t3_skip = QCheckBox("跳过影像重采样（调试）")
            lay.addWidget(self.t3_skip)

        elif key == "task4":
            self.t4_left = self._file_row(input_lay, "左核线 EPI", preview=True)
            self.t4_right = self._file_row(input_lay, "右核线 EPI")
            self.t4_gt = self._file_row(input_lay, "真值视差(可选)")
            lay.addWidget(input_card)
            pg = self._param_group("立体匹配参数", [])
            gl = QGridLayout()
            pg.content_layout.addLayout(gl)
            gl.addWidget(QLabel("方法"), 0, 0)
            self.t4_method = QComboBox()
            self.t4_method.addItems([
                "StereoBM (推荐)", "StereoSGBM", "Census", "Gray NCC", "CREStereo",
            ])
            self.t4_method.setCurrentIndex(0)
            gl.addWidget(self.t4_method, 0, 1)
            gl.addWidget(QLabel("BM blockSize"), 1, 0)
            self.t4_bm_bs = QSpinBox()
            self.t4_bm_bs.setRange(5, 51)
            self.t4_bm_bs.setSingleStep(2)
            self.t4_bm_bs.setValue(self.cfg.task4.bm_block_size)
            gl.addWidget(self.t4_bm_bs, 1, 1)
            gl.addWidget(QLabel("SGBM blockSize"), 2, 0)
            self.t4_sgbm_bs = QSpinBox()
            self.t4_sgbm_bs.setRange(3, 21)
            self.t4_sgbm_bs.setSingleStep(2)
            self.t4_sgbm_bs.setValue(self.cfg.task4.sgbm_block_size)
            gl.addWidget(self.t4_sgbm_bs, 2, 1)
            self.t4_run_all = QCheckBox("运行全部算法（复现组员 Task4 四题成果）")
            self.t4_run_all.setChecked(False)
            self.t4_run_all.toggled.connect(self._on_t4_run_all_toggled)
            pg.content_layout.addWidget(self.t4_run_all)
            lay.addWidget(pg)

        elif key == "task5":
            self.t5_disp = self._file_row(input_lay, "视差图", preview=True, kind="tiff")
            self.t5_rpc_l = self._file_row(input_lay, "左 RPC (.rpb)", kind="rpb")
            self.t5_rpc_r = self._file_row(input_lay, "右 RPC (.rpb)", kind="rpb")
            self.t5_rgb = self._file_row(input_lay, "左 RGB (可选)", preview=True, kind="tiff")
            self.t5_tie = self._file_row(input_lay, "同名点 CSV")
            self.t5_grid = self._file_row(input_lay, "DSM 格网规格 CSV")
            self.t5_ref_dsm = self._file_row(input_lay, "参考 DSM (可选)", kind="tiff")
            self.t5_ref_tie = self._file_row(input_lay, "参考物方坐标 CSV (可选)")
            lay.addWidget(input_card)
            pg = self._param_group("点云 / DSM 参数", [])
            gl = QGridLayout()
            pg.content_layout.addLayout(gl)
            gl.addWidget(QLabel("计算后端"), 0, 0)
            self.t5_compute = QComboBox()
            gpu_ok, gpu_msg = self._task5_gpu_status()
            self.t5_compute.addItems([
                "CPU 批量 (batch，推荐)",
                "CPU 多进程 (scipy)",
                f"GPU (CUDA + CuPy){'' if gpu_ok else ' — 不可用'}",
            ])
            if not gpu_ok:
                self.t5_compute.model().item(2).setEnabled(False)
            idx_map = {"batch": 0, "scipy": 1, "gpu": 2}
            method = self.cfg.task5.resolved_intersection_method()
            self.t5_compute.setCurrentIndex(idx_map.get(method, 0))
            self.t5_compute.currentIndexChanged.connect(self._on_t5_compute_changed)
            gl.addWidget(self.t5_compute, 0, 1)
            self._t5_gpu_hint = QLabel(
                f"GPU: {gpu_msg}" if gpu_ok else f"无 GPU: {gpu_msg}，请选 CPU"
            )
            self._t5_gpu_hint.setObjectName("MutedLabel")
            self._t5_gpu_hint.setWordWrap(True)
            pg.content_layout.addWidget(self._t5_gpu_hint)
            gl.addWidget(QLabel("stride"), 1, 0)
            self.t5_stride = QSpinBox()
            self.t5_stride.setRange(1, 8)
            self.t5_stride.setValue(self.cfg.task5.stride)
            gl.addWidget(self.t5_stride, 1, 1)
            gl.addWidget(QLabel("workers"), 2, 0)
            self.t5_workers = QSpinBox()
            self.t5_workers.setRange(1, 32)
            self.t5_workers.setValue(self.cfg.task5.workers)
            gl.addWidget(self.t5_workers, 2, 1)
            gl.addWidget(QLabel("chunk_size"), 3, 0)
            self.t5_chunk = QSpinBox()
            self.t5_chunk.setRange(10000, 500000)
            self.t5_chunk.setSingleStep(10000)
            self.t5_chunk.setValue(self.cfg.task5.chunk_size)
            gl.addWidget(self.t5_chunk, 3, 1)
            self.t5_mode = QComboBox()
            self.t5_mode.addItems([
                "完整流程（复现组员成果）",
                "快速：点云 + IDW",
                "仅点云",
                "仅 IDW DSM",
            ])
            pg.content_layout.addWidget(QLabel("模式"))
            pg.content_layout.addWidget(self.t5_mode)
            lay.addWidget(pg)
            self._on_t5_compute_changed()

        lay.addStretch(1)
        return w

    def _param_group(self, title: str, widgets: list) -> ControlCard:
        frame = ControlCard(title)
        for w in widgets:
            frame.content_layout.addWidget(w)
        return frame

    def _file_row(
        self,
        parent_lay,
        label: str,
        preview: bool = False,
        kind: str = "any",
    ) -> QLineEdit:
        row = PathInputRow(label, placeholder=PLACEHOLDER)
        row.browse_btn.clicked.connect(
            lambda _checked=False, r=row, pv=preview, k=kind: self._browse(r.edit, pv, k)
        )
        if row.clear_btn is not None:
            row.clear_btn.clicked.connect(
                lambda _checked=False, r=row, pv=preview: self._clear_path(r.edit, pv)
            )
        parent_lay.addWidget(row)
        return row.edit

    def _clear_path(self, edit: QLineEdit, preview: bool = False) -> None:
        if not edit.text().strip():
            return
        edit.clear()
        self._append_log("已清空该输入路径\n")
        self._session_output_ready.discard(self._module)
        self._refresh_module_preview(self._module)

    @staticmethod
    def _browse_filter(kind: str) -> str:
        if kind == "rpb":
            return "RPC 模型 (*.rpb);;所有文件 (*.*)"
        if kind == "tiff":
            return "GeoTIFF/影像 (*.tif *.tiff);;所有文件 (*.*)"
        return "所有文件 (*.*)"

    @staticmethod
    def _task5_gpu_status() -> tuple[bool, str]:
        from photogrammetry_suite.adapters import task5_adapter
        return task5_adapter.gpu_available()

    def _on_t5_compute_changed(self) -> None:
        if not hasattr(self, "t5_workers"):
            return
        scipy = self.t5_compute.currentIndex() == 1
        self.t5_workers.setEnabled(scipy)
        if hasattr(self, "_t5_gpu_hint") and self.t5_compute.currentIndex() == 2:
            ok, msg = self._task5_gpu_status()
            if not ok:
                self.t5_compute.setCurrentIndex(0)
                self._append_log(f"GPU 不可用，已切换 CPU: {msg}\n")

    def _on_t4_run_all_toggled(self, checked: bool) -> None:
        if not hasattr(self, "t4_method"):
            return
        self.t4_method.setEnabled(not checked)
        self.t4_bm_bs.setEnabled(not checked)
        self.t4_sgbm_bs.setEnabled(not checked)

    def _build_t5_cfg(self) -> Task5CloudConfig:
        methods = ["batch", "scipy", "gpu"]
        idx = self.t5_compute.currentIndex()
        use_gpu = idx == 2
        if use_gpu:
            ok, msg = self._task5_gpu_status()
            if not ok:
                raise RuntimeError(f"GPU 不可用: {msg}")
        return Task5CloudConfig(
            stride=self.t5_stride.value(),
            workers=self.t5_workers.value(),
            intersection_method=methods[max(0, min(idx, 2))],
            use_gpu=use_gpu,
            chunk_size=self.t5_chunk.value(),
            max_edge=self.cfg.task5.max_edge,
            support_radius=self.cfg.task5.support_radius,
            disp_path=self.t5_disp.text(),
            rpc_left=self.t5_rpc_l.text(),
            rpc_right=self.t5_rpc_r.text(),
            rgb_left=self.t5_rgb.text(),
            tie_csv=self.t5_tie.text().strip(),
            grid_spec=self.t5_grid.text().strip(),
            ref_dsm=self.t5_ref_dsm.text().strip(),
            ref_tie_csv=self.t5_ref_tie.text().strip(),
            output_dir=str(Path(self.cfg.output_root) / "task5"),
        )

    def _browse_start_dir(self, edit: QLineEdit) -> str:
        text = edit.text().strip()
        if text:
            candidate = Path(text).expanduser()
            if candidate.is_file():
                candidate = candidate.parent
            if candidate.is_dir():
                return str(candidate)
        last = (self.cfg.last_browse_dir or "").strip()
        if last and Path(last).is_dir():
            return last
        project = Path(self.cfg.project_root)
        if project.is_dir():
            return str(project)
        return str(Path.home())

    def _remember_browse_dir(self, path: str) -> None:
        selected = Path(path).expanduser()
        directory = selected if selected.is_dir() else selected.parent
        if not directory.is_dir():
            return
        folder = str(directory.resolve())
        if self.cfg.last_browse_dir == folder:
            return
        self.cfg.last_browse_dir = folder
        self.cfg.save()

    def _browse(self, edit: QLineEdit, preview: bool = False, kind: str = "any") -> None:
        try:
            start_dir = self._browse_start_dir(edit)
            if kind == "dir":
                path = QFileDialog.getExistingDirectory(self, "选择目录", start_dir)
                if not path:
                    return
                self._remember_browse_dir(path)
                edit.setText(path)
                self._append_log(f"已选择目录: {path}\n")
                self._session_output_ready.discard(self._module)
                QTimer.singleShot(0, lambda m=self._module: self._refresh_module_preview(m))
                return

            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择文件",
                start_dir,
                self._browse_filter(kind),
            )
            if not path:
                return
            suffix = Path(path).suffix.lower()
            if kind == "rpb" and suffix != ".rpb":
                QMessageBox.warning(
                    self,
                    "文件类型错误",
                    "左/右 RPC 必须选择 .rpb 文件，不能选 .tif 影像。",
                )
                return
            self._remember_browse_dir(path)
            edit.setText(path)
            self._append_log(f"已选择: {path}\n")
            self._session_output_ready.discard(self._module)
            QTimer.singleShot(0, lambda m=self._module: self._refresh_module_preview(m))
        except Exception:
            err = traceback.format_exc()
            _RUNTIME_LOG.write_text(err, encoding="utf-8")
            self._append_log(f"浏览文件失败:\n{err}\n")
            QMessageBox.critical(
                self,
                "浏览失败",
                f"打开文件选择框时出错，详情已写入:\n{_RUNTIME_LOG}\n\n{err[:800]}",
            )

    @staticmethod
    def _path_if_image(path: str) -> str:
        p = path.strip()
        if not p or Path(p).suffix.lower() not in IMAGE_EXTS:
            return ""
        return p if Path(p).is_file() else ""

    @staticmethod
    def _first_file(*candidates: str | Path) -> str:
        for item in candidates:
            p = Path(item)
            if p.is_file():
                return str(p)
        return ""

    def _task3_epipolar_dir(self) -> Path:
        return (
            task_output_dir("task3", self.cfg.output_root)
            / "epipolar_rectification"
            / "epipolar_images_and_rpc"
        )

    def _resolve_left_preview(self, key: str) -> str:
        if key == "pipeline" and hasattr(self, "tp_left"):
            return self._path_if_image(self.tp_left.text())

        if key == "task1" and hasattr(self, "t1_image"):
            return self._path_if_image(self.t1_image.text())

        if key == "task2" and hasattr(self, "t2_image"):
            return self._path_if_image(self.t2_image.text())

        if key == "task3" and hasattr(self, "t3_left"):
            if key in self._session_output_ready:
                epi_dir = self._task3_epipolar_dir()
                return self._first_file(
                    epi_dir / "JAX_Tile_163_RGB_005_epipolar.tif",
                    self._path_if_image(self.t3_left.text()),
                )
            return self._path_if_image(self.t3_left.text())

        if key == "task4" and hasattr(self, "t4_left"):
            return self._path_if_image(self.t4_left.text())

        if key == "task5" and hasattr(self, "t5_disp"):
            return self._first_file(
                self._path_if_image(self.t5_rgb.text()),
                self._path_if_image(self.t5_disp.text()),
            )

        return ""

    def _resolve_right_preview(self, key: str) -> str:
        if key not in self._session_output_ready:
            return ""

        out_root = Path(self.cfg.output_root)

        if key == "pipeline":
            stem = Path(self.tp_left.text().strip()).stem if hasattr(self, "tp_left") and self.tp_left.text().strip() else ""
            return self._first_file(
                out_root / "pipeline" / "03_dom" / f"{stem}_DOM_corrected.tif",
                out_root / "task5" / "dsm" / "dsm_tin_hybrid.png",
                out_root / "task5" / "dsm" / "dsm_idw.tif",
            )

        if key == "task1":
            return self._first_file(
                out_root / "task1" / "q4_dom_ellipH.tif",
                out_root / "task1" / "q3_dom_orthoH.tif",
                out_root / "task1" / "q2_dom_0m.tif",
                _ROOT / "results" / "q4_dom_ellipH.tif",
                _ROOT / "results" / "q2_dom_0m.tif",
            )

        if key == "task2":
            return self._first_file(
                _ROOT / "task2" / "q2" / "results" / "match_sift_ransac.png",
                out_root / "task2" / "q2" / "match_sift_ransac.png",
            )

        if key == "task3":
            epi_dir = self._task3_epipolar_dir()
            return self._first_file(
                epi_dir / "JAX_Tile_163_RGB_001_epipolar.tif",
            )

        if key == "task4":
            out4 = Path(self.cfg.task4.output_dir or out_root / "task4")
            q3 = out4 / "q3"
            return self._first_file(
                q3 / "第三题_StereoBM_disparity_optimized.png",
                q3 / "第三题_StereoSGBM_disparity_optimized.png",
                q3 / "第三题_StereoBM_disparity_optimized.tif",
                q3 / "第三题_StereoSGBM_disparity_optimized.tif",
                out4 / "q1" / "第一题_census_disparity.png",
                out4 / "q2" / "第二题_gray_disparity.png",
                out4 / "q4" / "第四题_CREStereo_disparity_fixed.png",
                out4 / "第三题_StereoBM_disparity_optimized.tif",
            )

        if key == "task5":
            out5 = out_root / "task5"
            return self._first_file(
                out5 / "dsm" / "dsm_idw.tif",
                out5 / "dsm" / "dsm_tin.tif",
            )

        return ""

    def _refresh_module_preview(self, key: str) -> None:
        meta = PREVIEW_META.get(key, PREVIEW_META["task1"])
        self.preview_hint.setText(meta["hint"])
        self.canvas.configure(
            left_title=meta["left_title"],
            right_title=meta["right_title"],
            left_placeholder=meta["left_placeholder"],
            right_placeholder=meta["right_placeholder"],
        )
        left = self._resolve_left_preview(key)
        right = self._resolve_right_preview(key)
        self.canvas.set_previews(left or None, right or None)

    # ------------------------------------------------------------------ Center
    def _build_center(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(0)

        preview_card = ControlCard("影像预览")
        preview_card.setObjectName("PreviewCard")
        preview_card._layout.setContentsMargins(12, 10, 12, 10)
        preview_card._layout.setSpacing(6)
        header = preview_card._layout.itemAt(0).widget()
        if header is not None:
            header.setObjectName("PreviewSectionTitle")

        hint = QLabel("")
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        self.preview_hint = hint
        preview_card.content_layout.addWidget(hint)
        self.canvas = DualCanvasWidget()
        self._canvas_wrap = self.canvas
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        preview_card.content_layout.addWidget(self.canvas, 1)
        lay.addWidget(preview_card, 1)
        return w

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale_timer.start(150)

    def _apply_ui_scale(self) -> None:
        app = QApplication.instance()
        scale = compute_ui_scale(app, self.width(), self.height())
        if app is not None and abs(scale - self._ui_scale) >= 0.03:
            self._ui_scale = scale
            app.setStyleSheet(scaled_stylesheet(scale))
        elif app is not None:
            self._ui_scale = scale
        if hasattr(self, "_sidebar"):
            self._sidebar.setFixedWidth(sidebar_width(self.width(), scale))
        if hasattr(self, "_canvas_wrap"):
            min_h = max(420, int(self.height() * 0.58))
            self._canvas_wrap.setMinimumHeight(min_h)
            self._canvas_wrap.setMaximumHeight(16777215)
            self._canvas_wrap.apply_scale(scale)

    def _build_statusbar(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_label = QLabel("● 系统就绪")
        self.status_label.setObjectName("StatusLabel")
        sb.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        sb.addPermanentWidget(self.progress)
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse_progress)
        self._pulse_val = 0

    def _pulse_progress(self) -> None:
        self._pulse_val = (self._pulse_val + 3) % 100
        if self._worker and self._worker.isRunning():
            v = self.progress.value()
            if v < 90:
                self.progress.setValue(min(v + 1, 90))

    # ------------------------------------------------------------------ Logic
    def _select_module(self, key: str) -> None:
        self._module = key
        idx = [m[0] for m in MODULES].index(key)
        self.sidebar_stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tab_buttons):
            btn.setChecked(i == idx)
        names = {"pipeline": "全流程", "task1": "正射纠正", "task2": "RPC精化",
                 "task3": "核线纠正", "task4": "立体匹配", "task5": "点云/DSM"}
        self._set_status(f"已切换: {names.get(key, key)}", "#d1d5db")
        self._refresh_module_preview(key)

    def _validate_required(self, fields: list[tuple[str, QLineEdit]]) -> bool:
        missing = [name for name, edit in fields if not edit.text().strip()]
        if missing:
            QMessageBox.warning(
                self, "缺少输入文件",
                "请先通过「浏览」选择以下文件：\n• " + "\n• ".join(missing),
            )
            return False
        bad: list[str] = []
        for name, edit in fields:
            p = edit.text().strip()
            if p and not Path(p).is_file():
                bad.append(f"{name}（不存在）: {p}")
        if bad:
            QMessageBox.warning(self, "文件不存在", "请检查路径：\n• " + "\n• ".join(bad))
            return False
        return True

    def _set_status(self, text: str, color: str = "#9ca3af") -> None:
        self.status_label.setText(f"● {text}")
        self.status_label.setStyleSheet(f"color: {color}; font-weight: 600;")

    def _append_log(self, text: str) -> None:
        self.log_console.moveCursor(self.log_console.textCursor().End)
        self.log_console.insertPlainText(text)
        self.log_console.ensureCursorVisible()

    def _on_run(self) -> None:
        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, "提示", "解算正在进行中")
            return
        if not self._validate_before_run():
            return
        if self._module == "task5":
            try:
                t5 = self._build_t5_cfg()
                self.cfg.task5 = t5
            except RuntimeError as exc:
                QMessageBox.warning(self, "Task5 配置", str(exc))
                return
        self.cfg.save()
        ensure_output_dirs(self.cfg.output_root)
        self.run_btn.setEnabled(False)
        self.progress.setValue(0)
        self._pulse_timer.start(120)
        self._set_status("正在启动解算线程...", "#a78bfa")

        job_fn = {
            "pipeline": self._job_pipeline,
            "task1": self._job_task1,
            "task2": self._job_task2,
            "task3": self._job_task3,
            "task4": self._job_task4,
            "task5": self._job_task5,
        }[self._module]

        self._worker = PipelineWorker(job_fn)
        self._worker.log.connect(self._append_log)
        self._worker.status.connect(lambda s: self._set_status(s, "#c4b5fd"))
        self._worker.progress.connect(self.progress.setValue)
        self._worker.finished_job.connect(self._on_job_done)
        self._worker.start()

    def _validate_before_run(self) -> bool:
        m = self._module
        if m == "pipeline":
            ok = self._validate_required([
                ("左影像", self.tp_left), ("右影像", self.tp_right),
                ("左控制点 CSV", self.tp_lgcp), ("右控制点 CSV", self.tp_rgcp),
            ])
            if not ok:
                return False
            for label, w in (("左", self.tp_left), ("右", self.tp_right)):
                rpb = Path(w.text().strip()).with_suffix(".rpb")
                if not rpb.is_file():
                    QMessageBox.warning(self, "缺少 RPC", f"{label}影像缺少同名 .rpb:\n{rpb}")
                    return False
            return True
        if m == "task1":
            ok = self._validate_required([
                ("待纠正影像", self.t1_image), ("参考底图 DOM", self.t1_dom), ("DEM", self.t1_dem),
            ])
            if not ok:
                return False
            rpb = Path(self.t1_image.text().strip()).with_suffix(".rpb")
            if not rpb.is_file():
                QMessageBox.warning(self, "缺少 RPC", f"未找到与影像同名的 RPC:\n{rpb}")
                return False
            return True
        if m == "task2":
            ok = self._validate_required([
                ("待纠正影像", self.t2_image),
                ("参考底图 DOM", self.t2_dom),
                ("DEM", self.t2_dem),
                ("椭球高控制点", self.t2_gcp),
                ("检查点", self.t2_check),
                ("四角点", self.t2_corners),
            ])
            if not ok:
                return False
            rpb = Path(self.t2_image.text().strip()).with_suffix(".rpb")
            if not rpb.is_file():
                QMessageBox.warning(self, "缺少 RPC", f"未找到与影像同名的 RPC:\n{rpb}")
                return False
            return True
        if m == "task3":
            ok = self._validate_required([
                ("左影像", self.t3_left),
                ("右影像", self.t3_right),
                ("地面检核点", self.t3_ground),
            ])
            if not ok:
                return False
            for label, path in (("左", self.t3_left), ("右", self.t3_right)):
                rpb = Path(path.text().strip()).with_suffix(".rpb")
                if not rpb.is_file():
                    QMessageBox.warning(self, "缺少 RPC", f"{label}影像缺少同名 .rpb:\n{rpb}")
                    return False
            ref = self.t3_ref.text().strip()
            if ref and not Path(ref).is_dir():
                QMessageBox.warning(self, "目录无效", f"参考核线目录不存在:\n{ref}")
                return False
            return True
        if m == "task4":
            return self._validate_required([
                ("左核线 EPI", self.t4_left), ("右核线 EPI", self.t4_right),
            ])
        if m == "task5":
            if not self._validate_required([
                ("视差图", self.t5_disp),
                ("左 RPC", self.t5_rpc_l),
                ("右 RPC", self.t5_rpc_r),
            ]):
                return False
            if not self.t5_grid.text().strip() and not self.t5_ref_dsm.text().strip():
                QMessageBox.warning(
                    self,
                    "缺少 DSM 格网",
                    "请指定 DSM 格网规格 CSV，或指定参考 DSM。\n"
                    "有参考 DSM 时软件会自动读取其地理变换作为输出格网。",
                )
                return False
            return self._validate_task5_files()
        return True

    def _validate_task5_files(self) -> bool:
        disp = Path(self.t5_disp.text().strip())
        rpc_l = Path(self.t5_rpc_l.text().strip())
        rpc_r = Path(self.t5_rpc_r.text().strip())
        rgb = self.t5_rgb.text().strip()
        tie = self.t5_tie.text().strip()
        grid = self.t5_grid.text().strip()
        ref_dsm = self.t5_ref_dsm.text().strip()
        ref_tie = self.t5_ref_tie.text().strip()
        errors: list[str] = []
        if disp.suffix.lower() not in {".tif", ".tiff"}:
            errors.append(f"视差图应为 .tif：{disp.name}")
        if rpc_l.suffix.lower() != ".rpb":
            errors.append(f"左 RPC 应为 .rpb（不是影像 .tif）：{rpc_l.name}")
        if rpc_r.suffix.lower() != ".rpb":
            errors.append(f"右 RPC 应为 .rpb（不是影像 .tif）：{rpc_r.name}")
        if rgb:
            p = Path(rgb)
            if p.suffix.lower() not in {".tif", ".tiff"}:
                errors.append(f"左 RGB 应为 .tif 影像：{p.name}")
            if "dsp" in p.name.lower() or "disparity" in p.name.lower():
                errors.append("左 RGB 不能选视差图(DSP)，应选 005_EPI.tif")
        for label, text in (
            ("同名点 CSV", tie),
            ("DSM 格网规格 CSV", grid),
            ("参考物方坐标 CSV", ref_tie),
        ):
            if text and not Path(text).is_file():
                errors.append(f"{label} 不存在：{text}")
            if text and Path(text).suffix.lower() != ".csv":
                errors.append(f"{label} 应为 .csv：{Path(text).name}")
        if ref_dsm:
            p = Path(ref_dsm)
            if not p.is_file():
                errors.append(f"参考 DSM 不存在：{ref_dsm}")
            elif p.suffix.lower() not in {".tif", ".tiff"}:
                errors.append(f"参考 DSM 应为 .tif：{p.name}")
        if errors:
            QMessageBox.warning(
                self,
                "Task5 文件类型错误",
                "请检查以下输入：\n• " + "\n• ".join(errors)
                + "\n\n说明：RPC 选 .rpb；视差选 .tif；左 RGB 选核线/原始影像，不要选视差图。"
                + "\n同名点 CSV 可留空；有参考 DSM 时 DSM 格网 CSV 也可留空。",
            )
            return False
        return True

    def _on_job_done(self, result: JobResult) -> None:
        self._pulse_timer.stop()
        self.run_btn.setEnabled(True)
        self.progress.setValue(100 if result.ok else 0)
        color = "#a78bfa" if result.ok else "#f87171"
        self._set_status(result.message if result.ok else f"失败: {result.message}", color)
        if result.ok:
            self._session_output_ready.add(self._module)
            self._refresh_module_preview(self._module)
            QMessageBox.information(self, "完成", result.message)
        else:
            QMessageBox.critical(self, "错误", result.message)

    # ------------------------------------------------------------------ Jobs
    def _job_pipeline(self) -> JobResult:
        from photogrammetry_suite.pipeline import PipelineConfig, run_full_pipeline
        method_map = {0: "stereo_bm", 1: "stereo_sgbm", 2: "census", 3: "gray_ncc", 4: "cres"}
        task5_methods = ["batch", "scipy", "gpu"]
        task5_idx = self.tp_t5_compute.currentIndex()
        task5_use_gpu = task5_idx == 2
        if task5_use_gpu:
            ok, msg = self._task5_gpu_status()
            if not ok:
                raise RuntimeError(f"GPU 不可用: {msg}")
        stages = tuple(k for k, cb in self.tp_stage_checks.items() if cb.isChecked())
        cfg = PipelineConfig(
            left_image=self.tp_left.text().strip(),
            right_image=self.tp_right.text().strip(),
            left_gcp=self.tp_lgcp.text().strip(),
            right_gcp=self.tp_rgcp.text().strip(),
            left_check=self.tp_lchk.text().strip(),
            right_check=self.tp_rchk.text().strip(),
            base_dom=self.tp_base_dom.text().strip(),
            ref_dom_left=self.tp_ref_dom_l.text().strip(),
            ref_dom_right=self.tp_ref_dom_r.text().strip(),
            ref_dsm=self.tp_ref_dsm.text().strip(),
            ref_dsp=self.tp_ref_dsp.text().strip(),
            dem=self.tp_dem.text().strip(),
            tie_csv=self.tp_tie.text().strip(),
            output_root=self.cfg.output_root,
            task4_method=method_map[self.tp_t4_method.currentIndex()],
            task4_run_all=self.tp_t4_all.isChecked(),
            task5_stride=self.tp_t5_stride.value(),
            task5_workers=self.tp_t5_workers.value(),
            task5_intersection_method=task5_methods[max(0, min(task5_idx, 2))],
            task5_use_gpu=task5_use_gpu,
            task5_chunk_size=self.tp_t5_chunk.value(),
            force=self.tp_force.isChecked(),
            stages=stages,
        )
        self._worker.status.emit("全流程：Task2→Task1/Task3→Task4→Task5 ...")
        res = run_full_pipeline(cfg)
        out_root = Path(self.cfg.output_root)
        stem = Path(self.tp_left.text().strip()).stem
        dom = out_root / "pipeline" / "03_dom" / f"{stem}_DOM_corrected.tif"
        dsm = out_root / "task5" / "dsm" / "dsm_tin_hybrid.tif"
        if not dsm.is_file():
            dsm = out_root / "task5" / "dsm" / "dsm_idw.tif"
        preview = str(dom if dom.is_file() else dsm if dsm.is_file() else "")
        ok = bool(res.get("all_ok"))
        msg = "全流程完成：" + ", ".join(
            f"{k}={'OK' if v else 'FAIL'}" for k, v in res.get("ok", {}).items())
        return JobResult(ok, msg, self.tp_left.text(), preview)

    def _job_task1(self) -> JobResult:
        from photogrammetry_suite.adapters import task1_adapter
        self._worker.status.emit("Task1: RPC 正射纠正...")
        msg = task1_adapter.run_task1_all(
            image=self.t1_image.text().strip(),
            dom=self.t1_dom.text().strip(),
            dem=self.t1_dem.text().strip(),
            dom_spec=self.t1_dom_spec.text().strip(),
            ground_points=self.t1_ground.text().strip(),
        )
        out_dir = task_output_dir("task1")
        stem = Path(self.t1_image.text().strip()).stem if self.t1_image.text().strip() else ""
        tag = stem[-3:] if stem else "001"
        sfx = "" if tag == "001" else f"_{tag}"
        out = out_dir / f"q4_dom_ellipH{sfx}.tif"
        if not out.is_file():
            out = out_dir / f"q2_dom_0m{sfx}.tif"
        if not out.is_file():
            legacy = _ROOT / "results" / "q4_dom_ellipH.tif"
            out = legacy if legacy.is_file() else _ROOT / "results" / "q2_dom_0m.tif"
        return JobResult(True, msg, self.t1_image.text(), str(out) if out.is_file() else "")

    def _job_task2(self) -> JobResult:
        from photogrammetry_suite.adapters import task2_adapter
        steps = [k for k, cb in self.t2_checks.items() if cb.isChecked()]
        self._worker.status.emit("Task2: 正在提取 SIFT 特征 / RPC 精化...")
        msg = task2_adapter.run_task2_pipeline(
            steps,
            image=self.t2_image.text().strip(),
            dom=self.t2_dom.text().strip(),
            dem=self.t2_dem.text().strip(),
            gcp_ellipsoid=self.t2_gcp.text().strip(),
            gcp_check=self.t2_check.text().strip(),
            corners=self.t2_corners.text().strip(),
            ref_rpc=self.t2_ref_rpc.text().strip(),
        )
        match_png = _ROOT / "task2" / "q2" / "results" / "match_sift_ransac.png"
        return JobResult(True, msg, self.t2_image.text(),
                         str(match_png) if match_png.is_file() else "")

    def _job_task3(self) -> JobResult:
        from photogrammetry_suite.adapters import task3_adapter
        self._worker.status.emit("Task3: 核线网格生成...")
        msg = task3_adapter.run_task3_epipolar(
            skip_images=self.t3_skip.isChecked(),
            left=self.t3_left.text().strip(),
            right=self.t3_right.text().strip(),
            ground_csv=self.t3_ground.text().strip(),
            ref_dir=self.t3_ref.text().strip(),
        )
        out = task_output_dir("task3") / "epipolar_rectification" / "epipolar_images_and_rpc"
        left_stem = Path(self.t3_left.text().strip()).stem if self.t3_left.text().strip() else "JAX_Tile_163_RGB_005"
        right_stem = Path(self.t3_right.text().strip()).stem if self.t3_right.text().strip() else "JAX_Tile_163_RGB_001"
        left = out / f"{left_stem}_epipolar.tif"
        right = out / f"{right_stem}_epipolar.tif"
        return JobResult(True, msg, self.t3_left.text(),
                         str(left) if left.is_file() else str(right) if right.is_file() else "")

    def _job_task4(self) -> JobResult:
        from photogrammetry_suite.adapters import task4_adapter
        method_map = {0: "stereo_bm", 1: "stereo_sgbm", 2: "census", 3: "gray_ncc", 4: "cres"}
        out_task4 = str(Path(self.cfg.output_root) / "task4")
        cfg = Task4StereoConfig(
            method=method_map[self.t4_method.currentIndex()],
            bm_block_size=self.t4_bm_bs.value(),
            sgbm_block_size=self.t4_sgbm_bs.value(),
            left_epi=self.t4_left.text(),
            right_epi=self.t4_right.text(),
            gt_disp=self.t4_gt.text(),
            output_dir=out_task4,
        )
        if self.t4_run_all.isChecked():
            self._worker.status.emit("Task4: 运行全部 5 种匹配算法（组员原始脚本）...")
            msg = task4_adapter.run_task4_all(cfg)
            out_tif = Path(cfg.output_dir) / "q3" / "第三题_StereoBM_disparity_optimized.tif"
        else:
            cfg.method = method_map[self.t4_method.currentIndex()]
            self._worker.status.emit("Task4: OpenCV 立体匹配解算...")
            msg = task4_adapter.run_task4_stereo(cfg)
            sub = {"stereo_bm": "q3", "stereo_sgbm": "q3", "census": "q1", "gray_ncc": "q2", "cres": "q4"}[
                cfg.method
            ]
            out_tif = Path(cfg.output_dir) / sub / "第三题_StereoBM_disparity_optimized.tif"
            if cfg.method == "stereo_sgbm":
                out_tif = Path(cfg.output_dir) / sub / "第三题_StereoSGBM_disparity_optimized.tif"
            elif cfg.method == "census":
                out_tif = Path(cfg.output_dir) / sub / "第一题_census_disparity.tif"
            elif cfg.method == "gray_ncc":
                out_tif = Path(cfg.output_dir) / sub / "第二题_gray_disparity.tif"
            elif cfg.method == "cres":
                out_tif = Path(cfg.output_dir) / sub / "第四题_CREStereo_disparity_fixed.tif"
        out_png = out_tif.with_suffix(".png")
        preview = str(out_png if out_png.is_file() else out_tif)
        return JobResult(True, msg, self.t4_left.text(), preview)

    def _job_task5(self) -> JobResult:
        from photogrammetry_suite.adapters import task5_adapter
        cfg = self._build_t5_cfg()
        backend = cfg.resolved_intersection_method()
        mode = self.t5_mode.currentIndex()
        mode_labels = [
            "完整流程（复现组员成果）",
            "快速：点云 + IDW",
            "仅点云",
            "仅 IDW DSM",
        ]
        self._worker.status.emit(f"Task5: {mode_labels[mode]} ({backend})...")
        if mode == 0:
            msg = task5_adapter.run_task5_all(cfg)
        elif mode == 1:
            msg = task5_adapter.run_task5_quick(cfg)
        elif mode == 2:
            msg = task5_adapter.run_task5_point_cloud(cfg)
        else:
            msg = task5_adapter.run_task5_dsm_idw(cfg)
        ply = Path(self.cfg.output_root) / "task5" / "point_cloud" / "point_cloud_visual_local_m.ply"
        return JobResult(True, msg, self.t5_disp.text(), str(ply) if ply.is_file() else "")


def _install_runtime_excepthook() -> None:
    """pythonw 无控制台时，未捕获异常写入日志并弹窗，避免静默退出。"""

    def _hook(exc_type, exc, tb):
        err = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            _RUNTIME_LOG.write_text(err, encoding="utf-8")
        except OSError:
            pass
        try:
            app = QApplication.instance()
            if app is not None:
                QMessageBox.critical(None, "程序错误", f"{err[:1200]}\n\n详见 {_RUNTIME_LOG}")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook


def run_qt_app() -> None:
    _install_runtime_excepthook()
    app = QApplication(sys.argv)
    app.setOrganizationName("SatPhotoPro")
    app.setOrganizationDomain("satphoto.local")
    app.setApplicationName("SatPhoto-Pro")
    win = SatPhotoProWindow()
    initial_scale = compute_ui_scale(app, win.width(), win.height())
    app.setStyleSheet(scaled_stylesheet(initial_scale))
    win.show()
    win._apply_ui_scale()
    sys.exit(app.exec_())
