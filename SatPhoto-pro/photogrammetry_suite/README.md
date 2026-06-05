# 卫星摄影测量后端处理系统 v0.1

集成小组 Task1–Task5 实习代码的 Windows 图形界面调度平台。

## 快速启动（推荐）

**双击 `启动系统.bat`** — 无黑窗口，直接打开图形界面。

备用：
- `launch.vbs` — 同上，无控制台
- `launch.bat` — 若启动失败会显示错误信息

若 Python 不在默认路径，编辑 bat 中这一行：
```
set "PYW=C:\Users\27238\anaconda3\pythonw.exe"
```

## 目录结构

```
photogrammetry_suite/     ← 集成系统（本目录）
  main.py                 ← 启动入口
  config.py               ← 统一路径与参数
  app/main_window.py      ← GUI 主界面
  adapters/               ← 各 Task 适配器
task1_code/               ← 同学 A：RPC 正射
task2/                    ← 同学 B：RPC 精化
run_task3_all.py          ← 同学 C：核线纠正
task4/                    ← 同学 D：立体匹配
task5_source/             ← 同学 E：点云/DSM
suite_outputs/            ← 统一输出目录
```

## 处理流程

Task1 → Task2 → Task3 → Task4 → Task5

| 模块 | 功能 | 关键参数 |
|------|------|----------|
| Task4 | 立体匹配 | **StereoBM blockSize**（默认 15） |
| Task5 | 点云生成 | **workers** 并行进程数、**stride** 步长 |

## 性能说明

- **Task5 点云慢**：瓶颈在 RPC 前向交会（逐点 scipy 优化），不是 GPU 问题
- **加速方法**：增大 `workers`（多进程）、增大 `stride`（降采样）
- **Task4**：五种方法中 StereoBM 对本数据集效果最好

## 配置

GUI 内可设置路径与参数，点击「保存配置」写入 `user_config.json`。

## 后续调试计划

- [ ] Task4 Census/NCC/CRES 脚本路径自动注入
- [ ] Task3 核线影像路径与 Task4 输出联动
- [ ] 全流程进度条与步骤取消
- [ ] 打包为 exe（PyInstaller）
