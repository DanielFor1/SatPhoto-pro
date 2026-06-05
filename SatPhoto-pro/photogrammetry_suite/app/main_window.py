# -*- coding: utf-8 -*-
"""卫星摄影测量后端处理系统 — 主窗口（美化版）。"""

from __future__ import annotations

import os
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from photogrammetry_suite.app.task_runner import TaskResult, TaskRunner, TaskState
from photogrammetry_suite.app.theme import (
    ACCENT,
    BG,
    BORDER,
    CARD_BG,
    FONT_BODY,
    FONT_MONO,
    FONT_SUB,
    FONT_TITLE,
    HEADER_BG,
    HEADER_FG,
    LOG_BG,
    LOG_FG,
    PIPELINE_STEPS,
    SUCCESS,
    TEXT,
    TEXT_MUTED,
)
from photogrammetry_suite.config import (
    OUTPUT_ROOT,
    PROJECT_ROOT,
    SuiteConfig,
    Task4StereoConfig,
    Task5CloudConfig,
    ensure_output_dirs,
)
from photogrammetry_suite.adapters import task1_adapter, task2_adapter, task3_adapter, task4_adapter, task5_adapter


class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("卫星摄影测量后端处理系统")
        self.geometry("1060x760")
        self.minsize(920, 640)
        self.configure(bg=BG)

        self.cfg = SuiteConfig.load()
        ensure_output_dirs()
        self.runner = TaskRunner(log_callback=self._append_log)

        self._setup_styles()
        self._build_ui()
        self._append_log(f"系统就绪\n项目: {PROJECT_ROOT}\n输出: {OUTPUT_ROOT}\n\n")

    def _setup_styles(self) -> None:
        style = ttk.Style(self)
        for theme in ("vista", "clam", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break

        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("TLabel", background=BG, foreground=TEXT, font=FONT_BODY)
        style.configure("Card.TLabel", background=CARD_BG, foreground=TEXT, font=FONT_BODY)
        style.configure("Muted.TLabel", background=BG, foreground=TEXT_MUTED, font=FONT_BODY)
        style.configure("CardTitle.TLabel", background=CARD_BG, foreground=TEXT, font=FONT_SUB)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8), font=FONT_BODY)
        style.configure("Primary.TButton", font=FONT_BODY, padding=(12, 6))
        style.configure("TLabelframe", background=CARD_BG)
        style.configure("TLabelframe.Label", background=CARD_BG, font=FONT_BODY)

    def _build_ui(self) -> None:
        # ---- 顶栏 ----
        header = tk.Frame(self, bg=HEADER_BG, height=72)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(
            header,
            text="卫星摄影测量后端处理系统",
            font=FONT_TITLE,
            fg=HEADER_FG,
            bg=HEADER_BG,
        ).pack(side=tk.LEFT, padx=24, pady=16)

        tk.Label(
            header,
            text="Satellite Photogrammetry Suite  v0.1",
            font=("Segoe UI", 9),
            fg="#94A3B8",
            bg=HEADER_BG,
        ).pack(side=tk.LEFT, pady=20)

        btn_frame = tk.Frame(header, bg=HEADER_BG)
        btn_frame.pack(side=tk.RIGHT, padx=16)
        self._header_btn(btn_frame, "打开输出", self._open_output).pack(side=tk.RIGHT, padx=4)
        self._header_btn(btn_frame, "保存配置", self._save_config).pack(side=tk.RIGHT, padx=4)

        # ---- 主体 ----
        body = ttk.Frame(self, padding=(12, 8))
        body.pack(fill=tk.BOTH, expand=True)

        nb = ttk.Notebook(body)
        nb.pack(fill=tk.BOTH, expand=True)

        self._tab_overview(nb)
        self._tab_task1(nb)
        self._tab_task2(nb)
        self._tab_task3(nb)
        self._tab_task4(nb)
        self._tab_task5(nb)

        # ---- 日志区 ----
        log_outer = tk.Frame(self, bg=BORDER, padx=1, pady=1)
        log_outer.pack(fill=tk.BOTH, expand=False, padx=12, pady=(0, 10))

        log_inner = tk.Frame(log_outer, bg=LOG_BG)
        log_inner.pack(fill=tk.BOTH, expand=True)

        log_head = tk.Frame(log_inner, bg=LOG_BG)
        log_head.pack(fill=tk.X, padx=8, pady=(6, 0))
        tk.Label(log_head, text="运行日志", font=FONT_BODY, fg=LOG_FG, bg=LOG_BG).pack(side=tk.LEFT)
        tk.Button(
            log_head, text="清空", font=("Microsoft YaHei UI", 9),
            bg="#334155", fg=LOG_FG, relief=tk.FLAT, padx=8, pady=2,
            command=self._clear_log,
        ).pack(side=tk.RIGHT)

        self.log_text = scrolledtext.ScrolledText(
            log_inner, height=10, font=FONT_MONO,
            bg=LOG_BG, fg=LOG_FG, insertbackground=LOG_FG,
            relief=tk.FLAT, padx=8, pady=6,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ---- 状态栏 ----
        status_bar = tk.Frame(self, bg="#E2E8F0", height=28)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        status_bar.pack_propagate(False)
        self.status_var = tk.StringVar(value="就绪")
        self.status_dot = tk.Label(status_bar, text="●", fg=SUCCESS, bg="#E2E8F0", font=("Arial", 10))
        self.status_dot.pack(side=tk.LEFT, padx=(12, 4))
        tk.Label(status_bar, textvariable=self.status_var, bg="#E2E8F0", fg=TEXT, font=FONT_BODY).pack(side=tk.LEFT)

    def _header_btn(self, parent: tk.Frame, text: str, cmd) -> tk.Button:
        return tk.Button(
            parent, text=text, command=cmd,
            font=FONT_BODY, bg="#334155", fg=HEADER_FG,
            activebackground=ACCENT, activeforeground="white",
            relief=tk.FLAT, padx=12, pady=4, cursor="hand2",
        )

    def _card(self, parent, title: str) -> ttk.Frame:
        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        outer.pack(fill=tk.X, pady=6)
        inner = ttk.Frame(outer, style="Card.TFrame", padding=14)
        inner.pack(fill=tk.BOTH, expand=True)
        if title:
            ttk.Label(inner, text=title, style="CardTitle.TLabel").pack(anchor=tk.W, pady=(0, 8))
        return inner

    def _primary_btn(self, parent, text: str, cmd) -> tk.Button:
        btn = tk.Button(
            parent, text=text, command=cmd,
            font=FONT_BODY, bg=ACCENT, fg="white",
            activebackground="#1D4ED8", activeforeground="white",
            relief=tk.FLAT, padx=16, pady=8, cursor="hand2",
        )
        return btn

    def _tab_overview(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=16)
        nb.add(f, text="  总览  ")

        # 流程图
        flow = tk.Frame(f, bg=BG)
        flow.pack(fill=tk.X, pady=(0, 12))
        for i, (name, desc, color) in enumerate(PIPELINE_STEPS):
            box = tk.Frame(flow, bg=color, padx=2, pady=2)
            box.pack(side=tk.LEFT, padx=(0 if i == 0 else 4, 4))
            inner = tk.Frame(box, bg=CARD_BG, padx=12, pady=10)
            inner.pack()
            tk.Label(inner, text=name, font=("Microsoft YaHei UI", 10, "bold"), fg=color, bg=CARD_BG).pack()
            tk.Label(inner, text=desc, font=("Microsoft YaHei UI", 9), fg=TEXT_MUTED, bg=CARD_BG).pack()
            if i < len(PIPELINE_STEPS) - 1:
                tk.Label(flow, text="→", font=("Arial", 14), fg=TEXT_MUTED, bg=BG).pack(side=tk.LEFT)

        card = self._card(f, "使用说明")
        tips = (
            "1. 按 Task1 → Task5 顺序处理，各 Tab 可单独运行\n"
            "2. Task4 推荐 StereoBM，调节 blockSize（默认 15）\n"
            "3. Task5 点云：workers=CPU 核心数，stride=2 可大幅加速\n"
            "4. 日志在下方黑色区域实时显示，输出文件在 suite_outputs/"
        )
        ttk.Label(card, text=tips, style="Card.TLabel", justify=tk.LEFT).pack(anchor=tk.W)

        card2 = self._card(f, "快捷操作")
        self._primary_btn(card2, "  一键全流程 (Task1→5)  ", self._run_full_pipeline).pack(anchor=tk.W)

    def _tab_task1(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=16)
        nb.add(f, text="  Task1 正射  ")
        card = self._card(f, "RPC 正射纠正")
        ttk.Label(card, text="Q1–Q5 正射 + 参考对比 + 跨视角检核", style="Card.TLabel").pack(anchor=tk.W)
        self._primary_btn(card, "  运行 Task1  ", lambda: self._run(self._do_task1)).pack(anchor=tk.W, pady=(10, 0))

    def _tab_task2(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=16)
        nb.add(f, text="  Task2 RPC  ")
        card = self._card(f, "RPC 精化 / 像控点 / 粗差剔除")
        self.t2_vars = {}
        for key, label in [("q1", "Q1 RPC 精化"), ("q2", "Q2 SIFT 匹配"), ("q3", "Q3 DEM 精化"),
                           ("q4", "Q4 椭球高"), ("q5", "Q5 粗差剔除")]:
            v = tk.BooleanVar(value=True)
            self.t2_vars[key] = v
            ttk.Checkbutton(card, text=label, variable=v, style="Card.TLabel").pack(anchor=tk.W)
        bf = tk.Frame(card, bg=CARD_BG)
        bf.pack(anchor=tk.W, pady=(10, 0))
        self._primary_btn(bf, "  运行选中  ", lambda: self._run(self._do_task2)).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(
            bf, text="生成配图", font=FONT_BODY, bg="#E2E8F0", fg=TEXT,
            relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
            command=lambda: self._run(lambda: task2_adapter.run_task2_figures()),
        ).pack(side=tk.LEFT)

    def _tab_task3(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=16)
        nb.add(f, text="  Task3 核线  ")
        card = self._card(f, "核线纠正")
        self.t3_skip_img = tk.BooleanVar(value=False)
        ttk.Checkbutton(card, text="跳过影像重采样（调试用）", variable=self.t3_skip_img).pack(anchor=tk.W)
        self._primary_btn(card, "  运行 Task3  ", lambda: self._run(self._do_task3)).pack(anchor=tk.W, pady=(10, 0))

    def _tab_task4(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=16)
        nb.add(f, text="  Task4 匹配  ")
        card = self._card(f, "立体匹配（五种方法）")

        row0 = tk.Frame(card, bg=CARD_BG)
        row0.pack(fill=tk.X, pady=4)
        tk.Label(row0, text="方法", font=FONT_BODY, bg=CARD_BG).pack(side=tk.LEFT)
        self.t4_method = tk.StringVar(value=self.cfg.task4.method)
        for text, val in [("Census", "census"), ("Gray NCC", "gray_ncc"), ("StereoBM ★", "stereo_bm"),
                          ("StereoSGBM", "stereo_sgbm"), ("CREStereo", "cres")]:
            tk.Radiobutton(
                row0, text=text, variable=self.t4_method, value=val,
                bg=CARD_BG, font=FONT_BODY, activebackground=CARD_BG,
            ).pack(side=tk.LEFT, padx=6)

        bs = tk.Frame(card, bg="#EFF6FF", padx=12, pady=10)
        bs.pack(fill=tk.X, pady=8)
        tk.Label(bs, text="blockSize（StereoBM 精度关键参数）", font=FONT_SUB, bg="#EFF6FF", fg=ACCENT).pack(anchor=tk.W)
        row_bs = tk.Frame(bs, bg="#EFF6FF")
        row_bs.pack(anchor=tk.W, pady=4)
        self.t4_bm_bs = tk.IntVar(value=self.cfg.task4.bm_block_size)
        self.t4_sgbm_bs = tk.IntVar(value=self.cfg.task4.sgbm_block_size)
        tk.Label(row_bs, text="BM:", bg="#EFF6FF").grid(row=0, column=0)
        ttk.Spinbox(row_bs, from_=5, to=51, increment=2, textvariable=self.t4_bm_bs, width=5).grid(row=0, column=1, padx=6)
        tk.Label(row_bs, text="SGBM:", bg="#EFF6FF").grid(row=0, column=2, padx=(12, 0))
        ttk.Spinbox(row_bs, from_=3, to=21, increment=2, textvariable=self.t4_sgbm_bs, width=5).grid(row=0, column=3, padx=6)

        self._path_row(card, "左核线影像", "t4_left", self.cfg.task4.left_epi)
        self._path_row(card, "右核线影像", "t4_right", self.cfg.task4.right_epi)
        self._path_row(card, "真值视差", "t4_gt", self.cfg.task4.gt_disp)
        self._primary_btn(card, "  运行立体匹配  ", lambda: self._run(self._do_task4)).pack(anchor=tk.W, pady=(12, 0))

    def _tab_task5(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=16)
        nb.add(f, text="  Task5 点云  ")
        card = self._card(f, "视差 → 点云 → DSM")

        perf = tk.Frame(card, bg="#ECFDF5", padx=12, pady=10)
        perf.pack(fill=tk.X, pady=(0, 8))
        tk.Label(perf, text="性能参数（多进程并行，非 GPU）", font=FONT_SUB, bg="#ECFDF5", fg=SUCCESS).pack(anchor=tk.W)
        row = tk.Frame(perf, bg="#ECFDF5")
        row.pack(anchor=tk.W, pady=4)
        self.t5_stride = tk.IntVar(value=self.cfg.task5.stride)
        self.t5_workers = tk.IntVar(value=self.cfg.task5.workers)
        tk.Label(row, text="stride:", bg="#ECFDF5").grid(row=0, column=0)
        ttk.Spinbox(row, from_=1, to=8, textvariable=self.t5_stride, width=5).grid(row=0, column=1, padx=6)
        tk.Label(row, text="workers:", bg="#ECFDF5").grid(row=0, column=2, padx=(12, 0))
        ttk.Spinbox(row, from_=1, to=32, textvariable=self.t5_workers, width=5).grid(row=0, column=3, padx=6)
        tk.Label(row, text="建议 stride=2, workers=8", bg="#ECFDF5", fg=TEXT_MUTED).grid(row=0, column=4, padx=12)

        self._path_row(card, "视差图", "t5_disp", self.cfg.task5.disp_path)
        self._path_row(card, "左 RPC", "t5_rpc_l", self.cfg.task5.rpc_left)
        self._path_row(card, "右 RPC", "t5_rpc_r", self.cfg.task5.rpc_right)
        self._path_row(card, "左 RGB", "t5_rgb", self.cfg.task5.rgb_left)

        bf = tk.Frame(card, bg=CARD_BG)
        bf.pack(anchor=tk.W, pady=(12, 0))
        self._primary_btn(bf, "  生成点云  ", lambda: self._run(self._do_task5_cloud)).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(
            bf, text="生成 DSM", font=FONT_BODY, bg="#E2E8F0", fg=TEXT,
            relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
            command=lambda: self._run(lambda: task5_adapter.run_task5_dsm_idw(self._get_t5_cfg())),
        ).pack(side=tk.LEFT, padx=(0, 8))
        self._primary_btn(bf, "  点云+DSM  ", lambda: self._run(lambda: task5_adapter.run_task5_all(self._get_t5_cfg()))).pack(side=tk.LEFT)

    def _path_row(self, parent, label: str, attr: str, default: str) -> None:
        row = tk.Frame(parent, bg=CARD_BG)
        row.pack(fill=tk.X, pady=3)
        tk.Label(row, text=f"{label}:", width=10, anchor=tk.W, bg=CARD_BG, font=FONT_BODY).pack(side=tk.LEFT)
        var = tk.StringVar(value=default)
        setattr(self, attr, var)
        ttk.Entry(row, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        tk.Button(
            row, text="...", font=FONT_BODY, bg="#E2E8F0", relief=tk.FLAT, padx=6,
            command=lambda v=var: self._browse_file(v),
        ).pack(side=tk.RIGHT)

    # ---- actions ----
    def _browse_file(self, var: tk.StringVar) -> None:
        path = filedialog.askopenfilename()
        if path:
            var.set(path)

    def _open_output(self) -> None:
        ensure_output_dirs()
        os.startfile(str(OUTPUT_ROOT))

    def _save_config(self) -> None:
        self._sync_cfg_from_ui()
        self.cfg.save()
        messagebox.showinfo("保存", "配置已保存")

    def _sync_cfg_from_ui(self) -> None:
        if hasattr(self, "t4_method"):
            self.cfg.task4.method = self.t4_method.get()
            self.cfg.task4.bm_block_size = int(self.t4_bm_bs.get())
            self.cfg.task4.sgbm_block_size = int(self.t4_sgbm_bs.get())
            self.cfg.task4.left_epi = self.t4_left.get()
            self.cfg.task4.right_epi = self.t4_right.get()
            self.cfg.task4.gt_disp = self.t4_gt.get()
        if hasattr(self, "t5_stride"):
            self.cfg.task5.stride = int(self.t5_stride.get())
            self.cfg.task5.workers = int(self.t5_workers.get())
            self.cfg.task5.disp_path = self.t5_disp.get()
            self.cfg.task5.rpc_left = self.t5_rpc_l.get()
            self.cfg.task5.rpc_right = self.t5_rpc_r.get()
            self.cfg.task5.rgb_left = self.t5_rgb.get()

    def _get_t4_cfg(self) -> Task4StereoConfig:
        self._sync_cfg_from_ui()
        return self.cfg.task4

    def _get_t5_cfg(self) -> Task5CloudConfig:
        self._sync_cfg_from_ui()
        return self.cfg.task5

    def _do_task1(self) -> str:
        return task1_adapter.run_task1_all()

    def _do_task2(self) -> str:
        return task2_adapter.run_task2_pipeline([k for k, v in self.t2_vars.items() if v.get()])

    def _do_task3(self) -> str:
        return task3_adapter.run_task3_epipolar(skip_images=self.t3_skip_img.get())

    def _do_task4(self) -> str:
        return task4_adapter.run_task4_stereo(self._get_t4_cfg())

    def _do_task5_cloud(self) -> str:
        return task5_adapter.run_task5_point_cloud(self._get_t5_cfg())

    def _run_full_pipeline(self) -> None:
        if not messagebox.askyesno("确认", "全流程耗时很长，确定开始？"):
            return

        def _pipeline() -> str:
            return "\n".join([
                task1_adapter.run_task1_all(),
                task2_adapter.run_task2_pipeline(),
                task3_adapter.run_task3_epipolar(skip_images=False),
                task4_adapter.run_task4_stereo(self._get_t4_cfg()),
                task5_adapter.run_task5_all(self._get_t5_cfg()),
            ])

        self._run(_pipeline)

    def _run(self, func) -> None:
        if self.runner.is_running:
            messagebox.showwarning("提示", "当前有任务在运行")
            return
        self.status_var.set("运行中...")
        self.status_dot.config(fg=WARNING)
        self._append_log("\n" + "=" * 50 + "\n>>> 开始任务\n" + "=" * 50 + "\n")
        self.runner.run(func, on_done=self._on_task_done)

    def _on_task_done(self, result: TaskResult) -> None:
        if result.state == TaskState.SUCCESS:
            self.status_var.set("完成")
            self.status_dot.config(fg=SUCCESS)
            self._append_log(f"\n[OK] {result.message}\n")
        elif result.state == TaskState.FAILED:
            self.status_var.set("失败")
            self.status_dot.config(fg="#DC2626")
            self._append_log(f"\n[FAIL] {result.message}\n")
        else:
            self.status_var.set(result.state.value)
            self.status_dot.config(fg=TEXT_MUTED)

    def _append_log(self, text: str) -> None:
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.update_idletasks()

    def _clear_log(self) -> None:
        self.log_text.delete("1.0", tk.END)


def run_app() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    app = MainWindow()
    app.mainloop()
