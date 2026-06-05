# -*- coding: utf-8 -*-
"""从 q1 脚本复用 RPC 读写与精化函数。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_Q1_PATH = Path(__file__).resolve().parent.parent.parent / "q1" / "scripts" / "q1_rpc_refine.py"
_spec = importlib.util.spec_from_file_location("q1_rpc_refine", _Q1_PATH)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

load_rpb = _mod.load_rpb
load_gcps = _mod.load_gcps
write_rpb = _mod.write_rpb
rpc_project = _mod.rpc_project
refine_rpc_affine = _mod.refine_rpc_affine
rmse_vec = _mod.rmse_vec
