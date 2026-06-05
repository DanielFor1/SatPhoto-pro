# 任务一：基于 RPC 模型的卫星影像正射纠正

作者：________（姓名 + 学号，提交前补全）
数据：JAX（Jacksonville）卫星影像 `JAX_Tile_163_RGB_001`，含 RPC（.rpb）、DEM、参考答案。

本任务把"基于 RPC 模型的正射纠正"拆为 5 小题，从 RPC 正解逐步到完整 DOM 生产、
椭球高改正与平行投影加速。**全部 5 题已实现、跑通，并与老师参考答案定量对比通过。**

---

## 一、运行环境与方法

- Python 3.13；依赖：`numpy scipy opencv-python tifffile matplotlib`（无需 GDAL/rasterio）。
- 第 4、5 题需 EGM2008 大地水准面格网 `egm2008-5.pgm`（GeographicLib，5′，~18MB），
  放在 `../geoid_data/geoids/egm2008-5.pgm`。来源见第 4 题。
- 一键运行：`python run_all.py`；或单独运行 `python q1_project.py` … `python q5_parallel.py`，
  最后 `python compare.py` 与参考结果对比。
- 输出在 `../results/`（DOM 为 `tif + tfw + prj`，可直接拖入 ArcGIS 卷帘对比）。
- Windows 控制台看中文输出请加 `PYTHONIOENCODING=utf-8`。

## 二、核心约定（贯穿全部小题）

1. **像素中心坐标系**：行=line、列=sample，左上角第一个像素中心为原点 (0,0)。
2. **输出 DOM 像素中心地理坐标**（`正射影像范围.csv` 的 left/top 为边界）：
   `lon = left + (col+0.5)·res_x`，`lat = top − (row+0.5)·res_y`。
   输出 `.tfw` 的左上角坐标同样取像素中心（left/top 各 ±0.5 像元）。
3. **只用 RPC 正解（地面→像方）**，正射采用**间接法（反向映射）**：
   遍历输出像素→反算地面坐标→RPC 正解到原图→双线性重采样，无需 RPC 反解。
4. **高程基准**：RPC 的高程是 **WGS84 椭球高**。地面点高程为椭球高；USGS DEM 为
   **正常高（水准高）**；两者差为高程异常 N（EGM2008，本区 ≈ −29.6 m）。

## 三、各题原理与结果

### 第 1 题（30 分）RPC 正解 —— 教材 P75 公式 3.1
归一化 `P=(lat−latOff)/latScale, L=(lon−lonOff)/lonScale, H=(h−hOff)/hScale`，
用 RPC00B 20 项三次多项式：
```
line   = Num_L(P,L,H)/Den_L(P,L,H)·lineScale + lineOff
sample = Num_S(P,L,H)/Den_S(P,L,H)·sampScale + sampOff
```
- 文件：`rpc.py`、`q1_project.py`
- **结果：12 个地面点与 `standard_answer_pixels.csv` 逐点完全一致，RMSE = 0.00000 像素。**

### 第 2 题（10 分）正射到 0 高程面
间接法，每个 DOM 像素高程 Z=0（椭球高 0 面），整幅向量化构网格 + `cv2.remap`
双线性重采样。文件：`ortho.py`、`raster_io.py`、`q2_ortho_zero.py`，输出 `q2_dom_0m.tif`。

### 第 3 题（10 分）正射到 DEM（正常高）
每像素高程由 DEM 双线性内插获得（`dem.py`，由 .tfw 做经纬度↔像素换算）。
此处直接用正常高，几何相对椭球高略偏。文件：`q3_ortho_dem.py`，输出 `q3_dom_orthoH.tif`。

### 第 4 题（5 分）椭球高 DEM（EGM2008 改正）—— 正确结果 —— 教材 P112
`椭球高 h = 正常高 H(DEM) + 高程异常 N(EGM2008)`。`geoid_egm2008.py` 解析
GeographicLib `egm2008-5.pgm`（`N = Offset + Scale·像素值`，Offset=−108、Scale=0.003，
原点 90N/0E、5′格网），双线性内插得 N，用椭球高重做正射。
- 文件：`q4_ortho_ellip.py`，输出 `q4_dom_ellipH.tif`。
- **N 交叉校验（12 个地面点）**：EGM2008 N 均值 −29.580 m；用控制点椭球高减 DEM
  正常高得隐含 N 均值 −29.845 m；两者 RMSE 仅 0.38 m，证明 N 与椭球高改正正确。

### 第 5 题（5 分）平行投影模型加速 —— 教材 P63 公式 2.97、P86 格网点
用 RPC 在 DOM 经纬度范围 + 椭球高范围生成 21×21×5 虚拟控制格网，最小二乘拟合
8 参数仿射（平行投影）模型 `sample/line = c0+c1·L+c2·P+c3·H`，再用它替代 RPC 做正射。
- 文件：`parallel_model.py`、`q5_parallel.py`，输出 `q5_dom_parallel.tif`、`../results/q5_timing.txt`。
- **结果**：虚拟控制点拟合残差 RMSE line/sample = 0.036/0.142 像素；整幅像点坐标与 RPC
  差异 RMSE line/sample = 0.033/0.131 像素、最大点位 0.51 像素（亚像素，无显著差异）；
  DOM 灰度差 RMSE 1.3/255。**坐标解算耗时 RPC 3894 ms → 平行投影 184 ms，加速 ≈ 21 倍。**
  原因：仿射每像素仅几次乘加、无有理多项式与除法，而 RPC 需评估 4×20 项多项式 + 2 次除法。

## 四、与参考结果（ArcGIS DOM）定量对比 —— `compare.py`

参考 DOM 与我方 DOM **网格完全一致**（同 .tfw），但参考为 16bit 且经 ArcGIS 拉伸，
故比**几何对齐**：NCC（对线性拉伸不敏感）+ 相位相关求残余平移。参考文件名乱码不可逆，
用 NCC 矩阵自动配对（行最大即对应变体）：

| 我方 | 最佳匹配 | NCC | 残余平移 |
|------|----------|-----|----------|
| 第2题 0高程面 | 参考 0高程面 | 0.9902 | 0.007 像素 |
| 第3题 水准高   | 参考 水准高   | 0.9898 | 0.028 像素 |
| 第4题 椭球高   | 参考 椭球高   | 0.9890 | 0.157 像素 |

三变体均与对应参考亚像素重合（残余平移 < 0.16 像素）；NCC≈0.99 的微小差异来自
ArcGIS 颜色拉伸与重采样，几何上完全一致。可视化见 `../results/diff_q4_ellipH.png`
（棋盘格中道路/建筑跨格连续 → 配准良好）。亦可在 ArcGIS 中用"卷帘"目视核对。

## 五、文件清单

| 文件 | 作用 |
|------|------|
| `rpc.py` | RPC 解析与正解（含虚拟控制点生成） |
| `raster_io.py` | tif 读写、.tfw/.prj 地理参考 |
| `ortho.py` | 间接法正射核心（向量化 + cv2.remap） |
| `dem.py` | DEM 读取与双线性内插（正常高） |
| `geoid_egm2008.py` | EGM2008 高程异常 N 读取与内插 |
| `parallel_model.py` | 平行投影（仿射）模型拟合与正解 |
| `q1`…`q5_*.py` | 五道小题主程序 |
| `compare.py` | 与参考结果定量几何对比 |
| `run_all.py` | 一键依次运行全部小题 |
