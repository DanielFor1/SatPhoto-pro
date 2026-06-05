"""Convert point cloud CSV (lon,lat,height) to CloudCompare-friendly PLY in local meters."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

csv_path = sys.argv[1] if len(sys.argv) > 1 else "outputs/task5/point_cloud/point_cloud.csv"
out_path = Path(csv_path).parent / (Path(csv_path).stem + "_visual_local_m.ply")

df = pd.read_csv(csv_path)
print(f"Loaded {len(df)} points")

# lon/lat -> local meters
lat_mid = df["lat"].mean()
lon_mid = df["lon"].mean()
m_per_deg_lat = 111320.0
m_per_deg_lon = 111320.0 * np.cos(np.radians(lat_mid))

x = (df["lon"].values - lon_mid) * m_per_deg_lon
y = (df["lat"].values - lat_mid) * m_per_deg_lat
z = df["ellipsoid_height"].values

has_rgb = "r" in df.columns or all(c in df.columns for c in ["r", "g", "b"])

with open(out_path, "w") as f:
    f.write("ply\nformat ascii 1.0\n")
    f.write(f"element vertex {len(df)}\n")
    f.write("property float x\nproperty float y\nproperty float z\n")
    if has_rgb:
        f.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
    f.write("end_header\n")
    for i in range(len(df)):
        if has_rgb:
            f.write(f"{x[i]:.6f} {y[i]:.6f} {z[i]:.6f} "
                    f"{int(df.iloc[i]['r'])} {int(df.iloc[i]['g'])} {int(df.iloc[i]['b'])}\n")
        else:
            f.write(f"{x[i]:.6f} {y[i]:.6f} {z[i]:.6f}\n")

print(f"Wrote {out_path}  ({len(df)} points, local meters)")
