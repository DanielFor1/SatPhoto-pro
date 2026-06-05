# Task 5 — DSM from Disparity

## What this package contains

Source code only. No data, no outputs.

## What you need to provide

Place the following files under `data/task5/` (relative to the directory where you run the commands):

```
data/task5/
├── 同名点.csv
├── dsm_grid_spec.csv
├── 影像/
│   ├── JAX_Tile_163_RGB_005_EPI.rpb
│   ├── JAX_Tile_163_RGB_001_EPI.rpb
│   ├── JAX_Tile_163_RGB_005_vs_JAX_Tile_163_RGB_001_DSP.tif
│   └── JAX_Tile_163_RGB_005_EPI.tif
└── 参考答案/
    └── JAX_Tile_163_RGB_005_vs_JAX_Tile_163_RGB_001_DSM.tif
```

## Install

```bash
pip install -r requirements.txt
```

## Run

All commands are run from the **project root** (the directory that contains `src/`).

GPU is **optional**. If you have a CUDA GPU and `cupy` installed, add `--gpu`. Otherwise the default CPU batch path works on any machine.

```bash
# CPU (universal fallback)
python -m src.dsm_from_disparity.cli run-all --stride 1 --workers 16

# GPU (requires cupy + CUDA)
python -m src.dsm_from_disparity.cli run-all --stride 1 --gpu
```

Key options:

| Flag | Default | Notes |
|---|---|---|
| `--stride` | 1 | Row/column stride (1 = all pixels) |
| `--workers` | 16 | Only used by scipy mode; batch mode ignores this |
| `--intersection-method` | batch | `batch` (CPU), `scipy` (slow, debug), `gpu` (experimental) |
| `--gpu` | — | Shortcut for `--intersection-method gpu` |
| `--max-edge` | 10.0 | TIN max edge threshold (meters) |
| `--support-radius` | 3.0 | Support mask radius (meters) |

## Outputs

```
outputs/task5/
├── tie_points/intersected_points.csv
├── point_cloud/point_cloud.csv
├── point_cloud/point_cloud.ply
├── point_cloud/point_cloud_visual_local_m.ply
├── dsm/dsm_idw.tif
├── dsm/dsm_idw_error.tif
├── dsm/dsm_tin_pure_masked.tif
├── dsm/dsm_tin_pure_masked_error.tif
├── dsm/dsm_tin_hybrid.tif
├── dsm/dsm_tin_hybrid_error.tif
└── metrics/*.csv
```

## Visualization (optional)

```bash
# Single DSM as histogram-stretched PNG
python scripts/render_dsm_vis.py outputs/task5/dsm/dsm_idw.tif -o dsm_idw.png

# 4×2 comparison figure (requires reference DSM)
python scripts/plot_dsm_comparison.py                      \
  --dsm-idw outputs/task5/dsm/dsm_idw.tif                   \
  --dsm-tin-pure outputs/task5/dsm/dsm_tin_pure_masked.tif   \
  --dsm-tin-hybrid outputs/task5/dsm/dsm_tin_hybrid.tif      \
  --reference data/task5/参考答案/JAX_Tile_163_RGB_005_vs_JAX_Tile_163_RGB_001_DSM.tif \
  -o dsm_comparison.png

# Point cloud to color-mapped PLY (local meters, CloudCompare-friendly)
python scripts/csv_to_visual_ply.py outputs/task5/point_cloud/point_cloud.csv -o cloud_viz.ply
```
