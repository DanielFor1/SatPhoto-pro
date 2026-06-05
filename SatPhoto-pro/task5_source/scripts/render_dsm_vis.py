"""Render DSM GeoTIFFs as PNG previews with percentile-based colormap."""
import rasterio, numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

# ---- config ----
DSM_DIR = Path('outputs/task5/dsm')
REF_PATH = Path('data/task5/参考答案/JAX_Tile_163_RGB_005_vs_JAX_Tile_163_RGB_001_DSM.tif')
OUT_DIR = Path('outputs/task5/dsm_vis')
OUT_DIR.mkdir(parents=True, exist_ok=True)

nodata = -99999.0

# ---- load all ----
files = {
    'idw': DSM_DIR / 'dsm_idw.tif',
    'tin_hybrid': DSM_DIR / 'dsm_tin_hybrid.tif',
    'tin_pure': DSM_DIR / 'dsm_tin.tif',
    'reference': REF_PATH,
}

dsms = {}
for name, path in files.items():
    with rasterio.open(path) as src:
        dsms[name] = src.read(1)

ref = dsms.pop('reference')

# ---- global height percentile clim (for consistent comparison) ----
all_valid = np.concatenate([
    d[(d != nodata) & np.isfinite(d)] for d in dsms.values()
] + [ref[(ref != nodata) & np.isfinite(ref)]])
vmin = float(np.percentile(all_valid, 2))
vmax = float(np.percentile(all_valid, 98))

# ---- error percentile clim ----
all_err = []
for name, dsm in dsms.items():
    mask = (dsm != nodata) & (ref != nodata)
    all_err.append((dsm[mask].astype(np.float64) - ref[mask].astype(np.float64)))
all_err = np.concatenate(all_err)
evmax = float(np.percentile(np.abs(all_err), 98))

print(f'Height: [{vmin:.1f}, {vmax:.1f}] m   Error: ±{evmax:.1f} m')

# ---- render each DSM ----
for name, dsm in dsms.items():
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.axis('off')
    masked = np.where((dsm != nodata) & np.isfinite(dsm), dsm, np.nan)
    im = ax.imshow(masked, cmap='terrain', vmin=vmin, vmax=vmax)
    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label='Height (m)')
    ax.set_title(f'{name} DSM', fontsize=14, fontweight='bold')
    plt.tight_layout()
    out = OUT_DIR / f'{name}.png'
    plt.savefig(out, dpi=200, bbox_inches='tight')
    plt.close()
    print(f'  {out}')

# ---- render reference ----
fig, ax = plt.subplots(figsize=(10, 8))
ax.axis('off')
masked_ref = np.where((ref != nodata) & np.isfinite(ref), ref, np.nan)
im = ax.imshow(masked_ref, cmap='terrain', vmin=vmin, vmax=vmax)
plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label='Height (m)')
ax.set_title('Reference DSM', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig(OUT_DIR / 'reference.png', dpi=200, bbox_inches='tight')
plt.close()
print(f'  reference.png')

# ---- render error maps ----
for name, dsm in dsms.items():
    mask = (dsm != nodata) & (ref != nodata) & np.isfinite(dsm) & np.isfinite(ref)
    err = np.full_like(dsm, np.nan, dtype=np.float32)
    err[mask] = dsm[mask].astype(np.float32) - ref[mask].astype(np.float32)

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.axis('off')
    im = ax.imshow(err, cmap='RdBu_r', vmin=-evmax, vmax=evmax)
    r = np.sqrt(np.nanmean(err[mask]**2))
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label='Error (m)')
    ax.set_title(f'{name} Error Map (RMSE {r:.2f} m)', fontsize=14, fontweight='bold')
    plt.tight_layout()
    out = OUT_DIR / f'{name}_error.png'
    plt.savefig(out, dpi=200, bbox_inches='tight')
    plt.close()
    print(f'  {out}')

print(f'\nDone. Outputs in {OUT_DIR.resolve()}')
