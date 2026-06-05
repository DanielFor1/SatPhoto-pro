# -*- coding: utf-8 -*-
"""SatPhoto-Pro 组员分发打包。在项目根目录执行: python pack_for_team.py"""

from __future__ import annotations

import shutil
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
STAMP = datetime.now().strftime("%Y%m%d")
ZIP_PATH = DIST / f"SatPhoto-Pro_组员版_{STAMP}.zip"

INCLUDE = [
    "photogrammetry_suite",
    "task1_code",
    "task2",
    "task4",
    "task5_source",
    "run_task3_all.py",
    "启动系统.bat",
    "launch.bat",
    "安装依赖.bat",
    "README_组员安装与运行.md",
    "pack_for_team.py",
    "pack_for_team.ps1",
]

SKIP_DIR_NAMES = {"__pycache__", ".git", ".cursor", "suite_outputs", "dist", "results"}
SKIP_FILE_NAMES = {"user_config.json"}


def should_skip(path: Path) -> bool:
    for part in path.parts:
        if part in SKIP_DIR_NAMES:
            return True
    if path.name in SKIP_FILE_NAMES:
        return True
    if path.suffix == ".pyc":
        return True
    return False


def main() -> None:
    DIST.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.is_file():
        ZIP_PATH.unlink()

    added = 0
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in INCLUDE:
            src = ROOT / name
            if not src.exists():
                print(f"  [skip] missing: {name}")
                continue
            if src.is_file():
                arc = name.replace("\\", "/")
                zf.write(src, arc)
                added += 1
                print(f"  + {name}")
                continue
            for f in src.rglob("*"):
                if not f.is_file() or should_skip(f.relative_to(ROOT)):
                    continue
                rel = f.relative_to(ROOT).as_posix()
                zf.write(f, rel)
                added += 1
            print(f"  + {name}/")

        readme = (
            "本目录用于存放解算结果。首次运行请在 SatPhoto-Pro 界面设置输出路径。\n"
        )
        zf.writestr("suite_outputs/README.txt", readme.encode("utf-8"))

    mb = ZIP_PATH.stat().st_size / (1024 * 1024)
    print()
    print(f"完成: {ZIP_PATH}")
    print(f"大小: {mb:.2f} MB  (共 {added} 个文件)")
    print("请将 zip 与 README_组员安装与运行.md 发给组员。")
    print("测试数据请单独共享「全流程测试用例」或「实习数据」。")


if __name__ == "__main__":
    main()
