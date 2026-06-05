# SatPhoto-Pro — 暗黑工业风 Qt 界面

## 启动

双击项目根目录 **`启动系统.bat`**

或命令行：

```bat
C:\Users\27238\anaconda3\pythonw.exe photogrammetry_suite\qt_app\main.py
```

## 界面结构

| 区域 | 说明 |
|------|------|
| 顶栏 Header | LOGO + 系统名 + Task1~5 模块 Tab 卡片 |
| 左侧 Sidebar | 文件输入、参数设置、「开始自动化解算」 |
| 右侧 Canvas | 双屏 GIS 网格画布（输入 / 成果） |
| 底栏 Status | 状态文字 + 进度条 |
| 侧栏底部 | 运行日志控制台 |

## 技术栈

- **PyQt5** + **QSS** 全局暗黑工业风样式（`qt_app/styles.qss`）
- **QThread** 异步解算（`qt_app/workers.py`），防止 OpenCV/GDAL 阻塞 UI
- 后端复用 `photogrammetry_suite/adapters/` 已有 Task1~5 逻辑

## 文件

```
photogrammetry_suite/qt_app/
  main.py          # 入口
  main_window.py   # 主窗口三栏布局
  canvas.py        # 双屏 GIS 网格预览
  workers.py       # QThread Worker
  styles.qss       # 全局 QSS
```

## 依赖

```bat
pip install PyQt5
```

（Anaconda 环境通常已自带 PyQt5）
