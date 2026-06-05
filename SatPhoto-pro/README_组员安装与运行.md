# SatPhoto-Pro 组员安装与运行说明

本文说明如何把本仓库中的 **SatPhoto-Pro（卫星摄影测量集成系统）** 拷贝到其他组员电脑上运行，以及需要安装的环境与依赖。

---

## 一、发给组员什么？

建议发 **软件包 ZIP**（由 `pack_for_team.ps1` 生成），**不要**把整个 `suite_outputs`、全部 `实习数据` 原样打包（体积可达数 GB）。

| 包类型 | 内容 | 体积约 |
|--------|------|--------|
| **软件包（推荐）** | 源码 + 启动脚本 + 本说明 | 约 10–20 MB |
| 可选：测试数据包 | `全流程测试用例/` 文件夹 | 约 170 MB |
| 可选：实习数据包 | `实习数据/` 文件夹 | 约 1.1 GB |

组员至少需要：**软件包** + 自己准备或共享盘上的 **影像/真值数据**（见下文「数据准备」）。

---

## 二、系统与环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | **Windows 10/11 64 位**（当前脚本为 `.bat`，未适配 macOS/Linux） |
| Python | **3.9 ~ 3.11** 推荐（3.12 多数可用，需自行验证） |
| 安装方式 | **Anaconda / Miniconda** 或官方 Python 均可 |
| 磁盘 | 软件约 50 MB；单次全流程输出建议预留 **≥ 5 GB** |
| 内存 | 建议 **≥ 16 GB**（Task4/5 处理大 TIFF 时更稳） |
| 显卡 | **非必须**；Task5「GPU 模式」需 NVIDIA + CUDA + CuPy（可选） |

---

## 三、安装步骤（组员操作）

### 1. 解压软件包

解压到**纯英文或中文路径均可**，例如：

```
D:\SatPhoto-Pro\
```

避免路径过深、含特殊符号。解压后应能看到：

```
启动系统.bat
安装依赖.bat
README_组员安装与运行.md
photogrammetry_suite\
task1_code\
task2\
task4\
task5_source\
run_task3_all.py
...
```

### 2. 安装 Python（若尚未安装）

任选其一：

- [Anaconda](https://www.anaconda.org/download)（推荐，便于装 GDAL）
- [Python 官网](https://www.python.org/downloads/) 安装时勾选 **Add Python to PATH**

### 3. 安装依赖

**方式 A（推荐）：双击 `安装依赖.bat`**

会自动用当前环境的 `python` 安装 `photogrammetry_suite\requirements.txt`，并尝试用 conda 安装 **GDAL**（Task2 必需）。

**方式 B：手动命令行**

```bat
cd /d D:\SatPhoto-Pro
python -m pip install -r photogrammetry_suite\requirements.txt
```

**GDAL（Task2 必装，否则 Q2–Q5 会报错）：**

```bat
conda install -c conda-forge gdal -y
```

若无 conda，可尝试（不一定成功）：

```bat
pip install gdal
```

### 4. 配置 Python 路径（仅当双击无法启动时）

用记事本打开 **`启动系统.bat`**，修改前两行为本机 Python 路径，例如：

```bat
set "PYW=C:\Users\你的用户名\anaconda3\pythonw.exe"
set "PY=C:\Users\你的用户名\anaconda3\python.exe"
```

保存后再双击 `启动系统.bat`。

### 5. 启动软件

- **推荐：双击 `启动系统.bat`**（无黑窗口，打开 Qt 图形界面）
- 若启动失败：双击 **`launch.bat`**（会显示错误信息）
- 或命令行：

```bat
python photogrammetry_suite\qt_app\main.py
```

启动失败时查看项目根目录下的 **`suite_startup.log`**。

---

## 四、Python 依赖清单

`photogrammetry_suite\requirements.txt` 中主要包含：

| 包名 | 用途 |
|------|------|
| PyQt5 | 图形界面 |
| numpy, scipy | 数值计算 |
| opencv-python | Task4 立体匹配、Task2 部分脚本 |
| matplotlib | 绘图与预览 |
| pandas | CSV/表格 |
| rasterio | 栅格读写（Task5、部分 Task1） |
| tifffile | TIFF 读取 |
| pygeodesy | Task1/Task2 椭球高相关（可选但建议装） |
| python-docx | 部分报告导出（若用到） |

**额外（非 pip 或需 conda）：**

| 组件 | 用途 |
|------|------|
| **GDAL** (`osgeo`) | Task2 影像地理参考、DOM 匹配 |
| **EGM2008 大地水准面 `.pgm`** | Task1 Q4/Q5、Task2 Q4 椭球高改正 |

大地水准面文件请放在项目根目录之一（任选）：

- `geoid_data/geoids/egm2008-5.pgm`
- 或 `EGM2008 - 1'.pgm`

没有该文件时，涉及椭球高正射/精化的题目可能无法运行或结果异常。

**Task5 GPU（可选）：**

```bat
pip install cupy-cuda12x
```

需与本机 CUDA 版本匹配；界面中选「GPU」模式才会用到。

---

## 五、数据准备（重要）

软件**不会**自动附带完整实习影像。组员需自行准备：

1. **全流程测试用例**（011/007 等）：从课程网盘/共享文件夹复制 `全流程测试用例` 到项目根目录。  
2. **实习数据**（Task1/2 等）：复制 `实习数据` 文件夹（若跑 005/001 链）。  
3. 在软件界面中通过 **「浏览」** 逐项选择影像、RPC、DEM、真值等，**不要依赖写死路径**。  
4. **输出目录** 在界面中设置（默认 `suite_outputs`），解算结果写入该目录。

首次使用建议将 `photogrammetry_suite\user_config.json` **删除或清空**，避免沿用他人电脑上的绝对路径。

---

## 六、各 Task 运行顺序与说明

```
Task1 正射 → Task2 RPC精化 → Task3 核线 → Task4 匹配 → Task5 点云/DSM
```

- 数据须**同一像对、同一输出链**串联（例如 011 左 + 007 右 → Task3 核线 → Task4 视差 → Task5）。  
- Task5 若用 011/007，**不要**用 005/001 的「同名点.csv」做检校。  
- Task5 DSM 格网与参考 DSM 尺寸不一致时，软件会自动改用参考 DSM 格网（需指定参考 DSM）。

---

## 七、常见问题

| 现象 | 处理 |
|------|------|
| 双击无反应 | 改 `启动系统.bat` 中 Python 路径，或用 `launch.bat` 看报错 |
| `No module named 'PyQt5'` | 运行 `安装依赖.bat` |
| `No module named 'osgeo'` | `conda install -c conda-forge gdal` |
| Task1 Q4 报错找不到 geoid | 放入 EGM2008 `.pgm`（见第四节） |
| 浏览文件框字看不清 | 使用最新版 `启动系统.bat` 对应源码；重启软件 |
| Task5 广播 shape 错误 | 检查视差/RPC/参考 DSM 是否为同一 011/007 链 |
| 中文路径乱码 | 设置环境变量 `PYTHONIOENCODING=utf-8`（启动脚本已设） |

日志文件：

- `suite_startup.log` — 启动失败  
- `suite_runtime.log` — 运行中未捕获异常（项目根目录）

---

## 八、打包人如何生成 ZIP（组长/维护者）

在项目根目录 **PowerShell** 执行：

```powershell
.\pack_for_team.ps1
```

生成 `dist\SatPhoto-Pro_组员版_日期.zip`。可将 `全流程测试用例` 单独再打一个 zip 发给组员。

---

## 九、版本信息

- 软件名：**SatPhoto-Pro** 本地卫星摄影测量解算系统  
- 集成：Task1–Task5 组员源码 + PyQt5 统一界面  
- 配置：`photogrammetry_suite\user_config.json`（界面保存后生成）

如有问题，请联系本组负责集成的同学，并附上 `suite_startup.log` / 界面报错截图。
