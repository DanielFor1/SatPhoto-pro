# -*- coding: utf-8 -*-
"""SatPhoto-Pro 全流程编排包：把 Task1-Task5 组员成果按

    Task2(校正不准确 RPC) -> Task1(DOM) / Task3(核线) -> Task4(视差) -> Task5(DSM)

的生产顺序串接，核心是将 Task2 产出的校正后 RPC 向下游传递，
实现"从不准确 RPC 影像到准确 DOM/DSM 产品"的完整链路。
"""

from .full_pipeline import PipelineConfig, run_full_pipeline  # noqa: F401
