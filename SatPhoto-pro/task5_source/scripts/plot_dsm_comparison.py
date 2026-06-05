"""Generate DSM comparison figure with percentile-based colormap scaling."""
import rasterio, numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

nodata = -99999.0

# Load DSMs
dsms = {}
with rasterio.open('outputs/task5/dsm/dsm_idw.tif') as src:
    dsms['IDW'] = src.read(1)
with rasterio.open('outputs/task5/dsm/dsm_tin_pure_masked.tif') as src:
    dsms['Pure TIN masked'] = src.read(1)
with rasterio.open('outputs/task5/dsm/dsm_tin_hybrid.tif') as src:
    dsms['TIN+IDW hybrid'] = src.read(1)
with rasterio.open('data/task5/参考答案/JAX_Tile_163_RGB_005_vs_JAX_Tile_163_RGB_001_DSM.tif') as src:
    ref = src.read(1)

# Global valid mask (all DSMs + ref)
names = list(dsms.keys())
mask = (ref != nodata)
for d in dsms.values():
    mask = mask & (d != nodata)

all_heights = np.concatenate([d[mask] for d in dsms.values()] + [ref[mask]])
vmin = float(np.percentile(all_heights, 2))
vmax = float(np.percentile(all_heights, 98))

# Error maps
errors = {}
for name, dsm in dsms.items():
    e = np.full_like(dsm, np.nan, dtype=np.float32)
    e[mask] = dsm[mask].astype(np.float32) - ref[mask].astype(np.float32)
    errors[name] = e

all_err = np.concatenate([e[mask] for e in errors.values()])
evmax = float(np.percentile(np.abs(all_err), 98))

print(f'Height clim: [{vmin:.1f}, {vmax:.1f}], Error clim: +/-{evmax:.1f}m')

fig = plt.figure(figsize=(20, 12))

# Row 1: DSMs + reference
dsm_list = list(dsms.items())  # IDW, Pure TIN masked, TIN+IDW hybrid
for i, (name, dsm) in enumerate(dsm_list):
    ax = fig.add_subplot(2, 4, i + 1)
    ax.axis('off')
    im = ax.imshow(dsm, cmap='terrain', vmin=vmin, vmax=vmax)
    rmse = np.sqrt(np.nanmean(errors[name][mask]**2))
    ax.set_title(f'{name}\nRMSE {rmse:.2f} m', fontsize=12, fontweight='bold')
    plt.colorbar(im, ax=ax, label='Height (m)', shrink=0.75, pad=0.02)

# Reference
ax = fig.add_subplot(2, 4, 4)
ax.axis('off')
im = ax.imshow(ref, cmap='terrain', vmin=vmin, vmax=vmax)
ax.set_title('Reference DSM', fontsize=12, fontweight='bold')
plt.colorbar(im, ax=ax, label='Height (m)', shrink=0.75, pad=0.02)

# Row 2: Error maps
for i, (name, dsm) in enumerate(dsm_list):
    ax = fig.add_subplot(2, 4, i + 5)
    ax.axis('off')
    im = ax.imshow(errors[name], cmap='RdBu_r', vmin=-evmax, vmax=evmax)
    rmse = np.sqrt(np.nanmean(errors[name][mask]**2))
    ax.set_title(f'{name} Error', fontsize=12, fontweight='bold')
    plt.colorbar(im, ax=ax, label='Error (m)', shrink=0.75, pad=0.02)

# Error histogram
ax = fig.add_subplot(2, 4, 8)
colors = ['steelblue', 'forestgreen', 'darkorange']
for i, (name, dsm) in enumerate(dsm_list):
    rmse = np.sqrt(np.nanmean(errors[name][mask]**2))
    ax.hist(errors[name][mask], bins=120, alpha=0.5, density=True,
            label=f'{name} ({rmse:.2f}m)', color=colors[i])
ax.axvline(0, color='k', linestyle='--', linewidth=0.8)
ax.set_xlim(-evmax, evmax)
ax.set_xlabel('Error (m)', fontsize=11)
ax.set_ylabel('Density', fontsize=11)
ax.set_title('Error Distribution', fontsize=12, fontweight='bold')
ax.legend(fontsize=8)

plt.tight_layout()
plt.savefig('reports/dsm_comparison.png', dpi=200, bbox_inches='tight')
print('Saved reports/dsm_comparison.png')
