# -*- coding: utf-8 -*-
"""补充数据 RPC 工具：把标准 RPC00B 文本(LINE_OFF / LINE_NUM_COEFF_i ...) 转为 .rpb。

补充数据 FWD/BWD 的 RPC 为 *_rpc.txt（GDAL/RPC00B 文本格式），字段名与课程 .rpb
（lineOffset / lineNumCoef=(...)）不同，但 20 项系数顺序一致（RPC00B：1,L,P,H,...,H^3）。
转换为 .rpb 后即可被 task1/task3/task5 的 RPCModel 直接读取，复用全部既有流程。
"""

from __future__ import annotations

import re
from pathlib import Path


_SCALAR_MAP = {
    "LINE_OFF": "lineOffset", "SAMP_OFF": "sampOffset",
    "LAT_OFF": "latOffset", "LONG_OFF": "longOffset", "HEIGHT_OFF": "heightOffset",
    "LINE_SCALE": "lineScale", "SAMP_SCALE": "sampScale",
    "LAT_SCALE": "latScale", "LONG_SCALE": "longScale", "HEIGHT_SCALE": "heightScale",
}
_COEF_MAP = {
    "LINE_NUM_COEFF": "lineNumCoef", "LINE_DEN_COEFF": "lineDenCoef",
    "SAMP_NUM_COEFF": "sampNumCoef", "SAMP_DEN_COEFF": "sampDenCoef",
}


def parse_rpc_txt(path: str | Path) -> dict:
    """解析 RPC00B 文本，返回 {rpb字段名: 值 / 20项列表}。"""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    out: dict = {}
    for key, rpb_key in _SCALAR_MAP.items():
        m = re.search(rf"^{key}\s*:\s*([-+0-9.eE]+)", text, re.M)
        if not m:
            raise ValueError(f"{path} 缺少 {key}")
        out[rpb_key] = float(m.group(1))
    for key, rpb_key in _COEF_MAP.items():
        vals = []
        for i in range(1, 21):
            m = re.search(rf"^{key}_{i}\s*:\s*([-+0-9.eE]+)", text, re.M)
            if not m:
                raise ValueError(f"{path} 缺少 {key}_{i}")
            vals.append(float(m.group(1)))
        out[rpb_key] = vals
    return out


def write_rpb(params: dict, out_path: str | Path) -> Path:
    """把解析结果写成课程 .rpb 文本（与测试用例同款格式）。"""
    def block(name: str, vals: list) -> str:
        lines = [f"\t{name} = ("]
        for i, v in enumerate(vals):
            sep = "," if i < len(vals) - 1 else ""
            lines.append(f"\t\t\t{v:+.15e}{sep}")
        lines.append("\t\t);")
        return "\n".join(lines)

    body = [
        'satId = "SUPP";', 'bandId = "P";', 'SpecId = "RPC00B";',
        "BEGIN_GROUP = IMAGE",
        "\terrBias =   1.0;", "\terrRand =   0.0;",
        f"\tlineOffset = {params['lineOffset']:.12f};",
        f"\tsampOffset = {params['sampOffset']:.12f};",
        f"\tlatOffset = {params['latOffset']:.12f};",
        f"\tlongOffset = {params['longOffset']:.12f};",
        f"\theightOffset = {params['heightOffset']:.12f};",
        f"\tlineScale = {params['lineScale']:.12f};",
        f"\tsampScale = {params['sampScale']:.12f};",
        f"\tlatScale = {params['latScale']:.12f};",
        f"\tlongScale = {params['longScale']:.12f};",
        f"\theightScale = {params['heightScale']:.12f};",
        block("lineNumCoef", params["lineNumCoef"]),
        block("lineDenCoef", params["lineDenCoef"]),
        block("sampNumCoef", params["sampNumCoef"]),
        block("sampDenCoef", params["sampDenCoef"]),
        "END_GROUP = IMAGE", "END;", "",
    ]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(body), encoding="utf-8")
    return out_path


def txt_to_rpb(txt_path: str | Path, out_path: str | Path) -> Path:
    return write_rpb(parse_rpc_txt(txt_path), out_path)
