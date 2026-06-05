# SatPhoto-Pro · 卫星摄影测量课程设计（团队集成）

> 武汉大学《卫星摄影测量》课程设计 · 基于 RPC 模型的"从不准确 RPC 影像到准确 DOM/DSM 产品"全流程集成软件。
> 本仓库供组员共享：含**集成软件源码**、**全流程一键编排**、**两条数据赛道的实验与评定报告**。

---

## 1. 这个软件做什么

把课程 Task1–Task5 五位同学的成果，**按正确的摄影测量生产顺序**集成为一条龙，并提供**带界面的一键全流程**：

```
不准确 RPC 立体像对 + 控制点
      │
   Task2  控制点匹配 / RPC 校正  →  准确 RPC（沿链传播）
      ├──────────────► Task1  正射纠正 ─────► 准确 DOM
      └──► Task3 核线 ──► Task4 密集匹配 ──► Task5 点云/DSM ─► 准确 DSM
```

> ⚠️ 关键认识：正确顺序**不是编号 1→2→3→4→5**。"准确"来自 **Task2 的 RPC 校正**，它必须**先行**；随后分成 DOM 分支（Task1）与 DSM 分支（Task3→4→5）。软件通过把 Task2 校正后的 RPC 以"同名 `.rpb` 暂存"**传播给下游**，真正打通"不准确 → 准确"。

![全流程数据流向](报告/figs/fig_pipeline_flow.png)

---

## 2. 两条独立数据赛道

| 赛道 | 数据 | 是否有真值/底图 | 报告 |
|---|---|---|---|
| **测试用例** | `全流程测试用例/`（011/007 + 老师真值 DOM/DSM/视差 + 底图 016） | 有真值、有底图 | [测试用例赛道_评定报告](报告/测试用例赛道_评定报告.md) |
| **补充数据** | `卫星摄影测量-补充数据/`（FWD/BWD 前后视 + SRTM，**无底图无真值**） | 无 | [补充数据赛道_报告](报告/补充数据赛道_报告.md) |

> 两条赛道相互独立、互不混用。补充数据按老师提示"用 SRTM 把 BWD 正射出来当底图"。

---

## 3. 关键结果速览

**测试用例（011/007，端到端一次跑通，各阶段全部 OK）**

| 环节 | 指标 |
|---|---|
| Task2 RPC 校正（独立检查点） | 011：9.77 px → **0.0013 px**；007：10.03 px → **0.0024 px** |
| Task1 DOM 对真值残余配准 | 011：9.09 → **0.81 px**；007：9.24 → **0.71 px**（NCC≈0.98） |
| Task3 核线竖直视差 | **0.026 px** |
| Task4 StereoBM（vs 真值视差） | RMSE **4.62 px**（五种算法均产出） |
| Task5 DSM（vs 真值 DSM） | Pure-TIN **4.84 m** / IDW 5.60 m / hybrid 5.48 m |

**补充数据（FWD/BWD + SRTM）**：RPC 文本→`.rpb`；用 SRTM 正射出 BWD 自制底图与 FWD-DOM；二者 SIFT 经 RANSAC 得 **544 内点**、残余配准约 **3.6 px（≈8 m）**，证明"BWD 正射当底图"可支撑控制点匹配。

---

## 4. 安装

推荐 Anaconda，使用专用环境 `satphoto`（已含 numpy/scipy/opencv/tifffile/pandas/rasterio/GDAL/PyQt5/onnxruntime 等）：

```powershell
conda env create -f SatPhoto-pro\environment_satphoto.yml
# 或在已有环境中：pip install -r SatPhoto-pro\photogrammetry_suite\requirements.txt
```

> 直接用 conda 环境的 `python.exe` 运行时，需保证 `<env>\Library\bin` 在 PATH 中（MKL/LAPACK 与 GDAL/PROJ 的 DLL 在此）。本仓库的 `.bat` 启动器已自动处理。

## 5. 数据放置

把课程数据放到**本仓库根目录**（与 `run_pipeline.bat` 同级）：

```
全流程测试用例/        # 测试用例赛道
卫星摄影测量-补充数据/  # 补充数据赛道
实习数据/              # 个人 Task1-5 原始数据（可选）
geoid_data/           # EGM2008（Task1 Q4 / Task2 Q4 用）
```

## 6. 运行

**图形界面（推荐演示）**：

```powershell
SatPhoto-pro\启动系统.bat      # 打开后选择"★ 全流程"标签页，一键完成全部流程
```

**命令行（报告复现）**：

```powershell
run_pipeline.bat                 # 测试用例 011/007 全流程（默认）
run_pipeline.bat --stages rpc dom    # 只跑指定阶段
run_supplementary.bat            # 补充数据：SRTM 正射 BWD 当底图 + 配准评估
make_report_figures.bat          # 重新生成报告图件
```

产物在 `SatPhoto-pro/suite_outputs/`：`pipeline/`（全流程）、`task3/4/5/`（各环节）、`supplementary/`（补充数据）。

---

## 7. 目录结构

```
SatPhoto-Pro-share/
├─ README.md                     本文件
├─ run_pipeline.py / .bat        测试用例全流程一键编排（命令行）
├─ run_supplementary.py / .bat   补充数据赛道实验
├─ make_report_figures.py / .bat 报告图件生成
├─ 报告/
│  ├─ 测试用例赛道_评定报告.md/.docx/.pdf
│  ├─ 补充数据赛道_报告.md/.docx/.pdf
│  └─ figs/                      报告图件
├─ docs/环境与运行说明.md
└─ SatPhoto-pro/                 集成软件与各组员源码
   ├─ photogrammetry_suite/      Qt 界面 + 统一 adapter + 全流程编排(pipeline/)
   ├─ task1_code/                Task1 正射纠正（Q1–Q5）
   ├─ task2/                     Task2 控制点匹配与 RPC 校正（Q1–Q5）
   ├─ run_task3_all.py           Task3 核线纠正（Q1–Q4）
   ├─ task4/                     Task4 密集匹配（Census/NCC/BM/SGBM/CREStereo）
   └─ task5_source/              Task5 视差→点云→DSM（Q1–Q4）
```

> CREStereo 的 ONNX 权重较大、未随仓库提供；如需 Task4 挑战题，请按 `SatPhoto-pro/` 内说明单独放置模型。

---

## 8. 评分对齐

- **个人部分（60）**：Task1–Task5 共 22 个小题均有实现与证据（详见两份报告的逐题评定表）。
- **团队部分（40）**：软件已满足 100% 评分点——"把成果集成到带界面软件并完成全部流程"，逻辑方向与"从不准确 RPC 到准确 DOM/DSM 产品"一致。
