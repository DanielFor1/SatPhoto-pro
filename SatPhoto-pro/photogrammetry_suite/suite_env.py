# -*- coding: utf-8 -*-
"""SatPhoto-Pro 运行前注入环境变量，供各 Task 脚本读取。"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def image_stem(path: str | Path) -> str:
    return Path(path).stem


def sibling_rpb(tif_path: str | Path) -> Path:
    p = Path(tif_path)
    rpb = p.with_suffix(".rpb")
    if rpb.is_file():
        return rpb
    raise FileNotFoundError(f"未找到与影像同名的 RPC: {rpb}")


def _set(key: str, value: str | Path | None) -> None:
    if value is None:
        os.environ.pop(key, None)
        return
    text = str(value).strip()
    if text:
        os.environ[key] = text
    else:
        os.environ.pop(key, None)


def apply_task1_env(
    *,
    image: str = "",
    dom: str = "",
    dem: str = "",
    dom_spec: str = "",
    ground_points: str = "",
    ref_dom: str = "",
    output_dir: str = "",
) -> None:
    _set("SUITE_T1_IMAGE", image)
    _set("SUITE_T1_DOM", dom or ref_dom)
    _set("SUITE_T1_REF_DOM", ref_dom or dom)
    _set("SUITE_T1_DEM", dem)
    _set("SUITE_T1_DOM_SPEC", dom_spec)
    _set("SUITE_T1_GROUND_POINTS", ground_points)
    _set("SUITE_T1_OUT", output_dir)
    if image:
        _set("SUITE_T1_IMAGES", image_stem(image))
        try:
            _set("SUITE_T1_RPC", sibling_rpb(image))
        except FileNotFoundError:
            os.environ.pop("SUITE_T1_RPC", None)


def apply_task2_env(
    *,
    image: str = "",
    dom: str = "",
    dem: str = "",
    gcp_ellipsoid: str = "",
    gcp_check: str = "",
    init_rpc: str = "",
    ref_rpc: str = "",
    corners: str = "",
) -> None:
    _set("SUITE_T2_IMAGE", image)
    _set("SUITE_T2_DOM", dom)
    _set("SUITE_T2_DEM", dem)
    _set("SUITE_T2_GCP_ELLIPSOID", gcp_ellipsoid)
    _set("SUITE_T2_GCP_CHECK", gcp_check)
    _set("SUITE_T2_CORNERS", corners)
    if init_rpc:
        _set("SUITE_T2_INIT_RPC", init_rpc)
    elif image:
        try:
            _set("SUITE_T2_INIT_RPC", sibling_rpb(image))
        except FileNotFoundError:
            os.environ.pop("SUITE_T2_INIT_RPC", None)
    else:
        os.environ.pop("SUITE_T2_INIT_RPC", None)
    _set("SUITE_T2_REF_RPC", ref_rpc)
    if image:
        _set("SUITE_T2_STEM", image_stem(image))


def apply_task3_env(
    *,
    left: str = "",
    right: str = "",
    ground_csv: str = "",
    ref_dir: str = "",
    output_dir: str = "",
) -> None:
    _set("SUITE_T3_LEFT", left)
    _set("SUITE_T3_RIGHT", right)
    if left:
        _set("SUITE_T3_LEFT_NAME", image_stem(left))
    else:
        os.environ.pop("SUITE_T3_LEFT_NAME", None)
    if right:
        _set("SUITE_T3_RIGHT_NAME", image_stem(right))
    else:
        os.environ.pop("SUITE_T3_RIGHT_NAME", None)
    if left and right:
        lp, rp = Path(left).resolve().parent, Path(right).resolve().parent
        _set("SUITE_T3_DATA", lp if lp == rp else lp)
    _set("SUITE_T3_GROUND_CSV", ground_csv)
    _set("SUITE_T3_REF", ref_dir)
    _set("SUITE_T3_OUT", output_dir)


@contextmanager
def task_env(**apply_kwargs) -> Iterator[None]:
    """临时注入环境变量，运行结束后恢复。"""
    backup = os.environ.copy()
    try:
        for fn, kwargs in apply_kwargs.items():
            if fn == "task1":
                apply_task1_env(**kwargs)
            elif fn == "task2":
                apply_task2_env(**kwargs)
            elif fn == "task3":
                apply_task3_env(**kwargs)
        yield
    finally:
        os.environ.clear()
        os.environ.update(backup)
