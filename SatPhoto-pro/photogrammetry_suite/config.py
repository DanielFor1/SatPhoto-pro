# -*- coding: utf-8 -*-
"""卫星摄影测量集成系统 — 统一路径与默认参数配置。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


# 项目根目录（《卫星摄影测量课程设计》）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUITE_ROOT = Path(__file__).resolve().parent

# 各组员源码目录
TASK1_CODE = PROJECT_ROOT / "task1_code"
TASK2_ROOT = PROJECT_ROOT / "task2"
TASK3_SCRIPT = PROJECT_ROOT / "run_task3_all.py"
TASK4_ROOT = PROJECT_ROOT / "task4"
TASK5_ROOT = PROJECT_ROOT / "task5_source"

# 实习数据
DATA_ROOT = PROJECT_ROOT / "实习数据"
DATA_TASK1 = DATA_ROOT / "task1"
DATA_TASK2 = DATA_ROOT / "task2"
DATA_TASK3 = DATA_ROOT / "task3"
DATA_TASK4 = DATA_ROOT / "task4"
DATA_TASK5 = DATA_ROOT / "task5"

# 集成系统统一输出
OUTPUT_ROOT = PROJECT_ROOT / "suite_outputs"
OUTPUT_TASK1 = OUTPUT_ROOT / "task1"
OUTPUT_TASK2 = OUTPUT_ROOT / "task2"
OUTPUT_TASK3 = OUTPUT_ROOT / "task3"
OUTPUT_TASK4 = OUTPUT_ROOT / "task4"
OUTPUT_TASK5 = OUTPUT_ROOT / "task5"

# EGM2008 大地水准面（task1 / task2 q4）
GEOID_SEARCH = [
    PROJECT_ROOT / "geoid_data" / "geoids" / "egm2008-5.pgm",
    PROJECT_ROOT / "EGM2008 - 1'.pgm",
    PROJECT_ROOT,
]

CONFIG_FILE = SUITE_ROOT / "user_config.json"


def get_output_root() -> Path:
    """读取用户配置的输出根目录，未配置时使用默认 suite_outputs。"""
    if CONFIG_FILE.is_file():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            root = raw.get("output_root", "")
            if root:
                return Path(root)
        except (json.JSONDecodeError, OSError):
            pass
    return OUTPUT_ROOT


def task_output_dir(name: str, root: Path | str | None = None) -> Path:
    """各 Task 子输出目录，如 task1 / task4。"""
    base = Path(root) if root else get_output_root()
    return base / name


@dataclass
class Task4StereoConfig:
    """Task4 立体匹配参数（默认 StereoBM，blockSize 可调）。"""

    method: str = "stereo_bm"  # census | gray_ncc | stereo_bm | stereo_sgbm | cres
    bm_block_size: int = 15
    sgbm_block_size: int = 5
    search_margin: int = 10
    left_epi: str = ""
    right_epi: str = ""
    gt_disp: str = ""
    output_dir: str = ""


@dataclass
class Task5CloudConfig:
    """Task5 点云/DSM 参数 — 支持 CPU batch/scipy 与 GPU(CuPy)。"""

    stride: int = 2
    workers: int = 8
    intersection_method: str = "batch"  # batch | scipy | gpu
    use_gpu: bool = False
    chunk_size: int = 100000
    max_edge: float = 10.0
    support_radius: float = 3.0
    disp_path: str = ""
    rpc_left: str = ""
    rpc_right: str = ""
    rgb_left: str = ""
    tie_csv: str = ""
    grid_spec: str = ""
    ref_dsm: str = ""
    ref_tie_csv: str = ""
    output_dir: str = ""

    def resolved_intersection_method(self) -> str:
        if self.use_gpu:
            return "gpu"
        return self.intersection_method or "batch"


@dataclass
class SuiteConfig:
    project_root: str = str(PROJECT_ROOT)
    python_exe: str = ""  # 空则自动检测
    output_root: str = str(OUTPUT_ROOT)
    last_browse_dir: str = ""  # 上次文件/目录浏览位置，跨会话记忆
    task4: Task4StereoConfig = field(default_factory=Task4StereoConfig)
    task5: Task5CloudConfig = field(default_factory=Task5CloudConfig)

    def resolve_paths(self) -> None:
        """仅同步输出子目录，不自动填充输入数据路径。"""
        out_root = Path(self.output_root)
        if not self.task4.output_dir:
            self.task4.output_dir = str(out_root / "task4")
        if not self.task5.output_dir:
            self.task5.output_dir = str(out_root / "task5")

    def set_output_root(self, path: str | Path) -> None:
        """设置统一输出根目录，并同步 Task4/5 子目录。"""
        root = Path(path).expanduser().resolve()
        self.output_root = str(root)
        self.task4.output_dir = str(root / "task4")
        self.task5.output_dir = str(root / "task5")

    @classmethod
    def load(cls) -> SuiteConfig:
        if CONFIG_FILE.is_file():
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            t4 = Task4StereoConfig(**raw.pop("task4", {}))
            t5 = Task5CloudConfig(**raw.pop("task5", {}))
            cfg = cls(task4=t4, task5=t5, **raw)
        else:
            cfg = cls()
        cfg.resolve_paths()
        return cfg

    def save(self) -> None:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def ensure_output_dirs(output_root: str | Path | None = None) -> Path:
    """创建输出根目录及 task1–task5 子目录。"""
    root = Path(output_root) if output_root else get_output_root()
    for name in ("task1", "task2", "task3", "task4", "task5"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def find_python() -> str:
    cfg = SuiteConfig.load()
    if cfg.python_exe and Path(cfg.python_exe).is_file():
        return cfg.python_exe
    # 常见 Windows Python 路径
    candidates = [
        os.environ.get("PYTHON_EXE", ""),
        r"C:\Users\27238\anaconda3\python.exe",
        "python",
    ]
    for c in candidates:
        if c and (Path(c).is_file() or c == "python"):
            return c
    return "python"


def find_geoid_pgm() -> Path | None:
    for p in GEOID_SEARCH:
        if p.is_file() and p.suffix.lower() == ".pgm":
            return p
        if p.is_dir():
            for f in p.glob("*EGM*.pgm"):
                return f
    return None
