from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import tifffile
from scipy.optimize import least_squares


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
GROUND_CSV = DATA / "rpc_consistency_ground_points.csv"
OUT = ROOT / "output" / "task3_epipolar_rectification"
OUT34 = OUT / "epipolar_images_and_rpc"
REF = ROOT / "\u53c2\u8003\u7b54\u6848" / "task3-AI\u7a0b\u5e8f\u7b54\u6848-\u7b2c\u4e09\u9898\u7b2c\u56db\u9898\u53c2\u8003\u7ed3\u679c-new"

LEFT_NAME = "JAX_Tile_163_RGB_005"   # task 3/4: left/base image
RIGHT_NAME = "JAX_Tile_163_RGB_001"  # task 3/4: right/search image
IMAGE_SIZE = 2048
EPI_WIDTH = 2579
EPI_HEIGHT = 2626
N_SEGMENTS = 8
STRIP_BOUNDS = [0, 328, 656, 984, 1313, 1641, 1969, 2297, 2626]
NODE_STEP = 64
NODATA = -99999
TASK2_SAMPLE_COUNT = 401


def terms(p: np.ndarray, l: np.ndarray, h: np.ndarray) -> np.ndarray:
    return np.stack(
        [
            np.ones_like(p),
            l,
            p,
            h,
            l * p,
            l * h,
            p * h,
            l * l,
            p * p,
            h * h,
            p * l * h,
            l**3,
            l * p * p,
            l * h * h,
            l * l * p,
            p**3,
            p * h * h,
            l * l * h,
            p * p * h,
            h**3,
        ],
        axis=-1,
    )


@dataclass
class RPC:
    line_offset: float
    samp_offset: float
    lat_offset: float
    lon_offset: float
    height_offset: float
    line_scale: float
    samp_scale: float
    lat_scale: float
    lon_scale: float
    height_scale: float
    line_num: np.ndarray
    line_den: np.ndarray
    samp_num: np.ndarray
    samp_den: np.ndarray

    @staticmethod
    def from_rpb(path: Path) -> "RPC":
        text = path.read_text(encoding="utf-8", errors="ignore")

        def scalar(name: str) -> float:
            m = re.search(rf"{name}\s*=\s*([-+0-9.eE]+)", text)
            if not m:
                raise ValueError(f"Missing {name} in {path}")
            return float(m.group(1))

        def coef(name: str) -> np.ndarray:
            m = re.search(rf"{name}\s*=\s*\((.*?)\);", text, re.S)
            if not m:
                raise ValueError(f"Missing {name} in {path}")
            vals = [float(x) for x in re.findall(r"[-+]\d+\.\d+e[-+]\d+", m.group(1), re.I)]
            if len(vals) != 20:
                raise ValueError(f"{name} has {len(vals)} coefficients, expected 20")
            return np.asarray(vals, dtype=np.float64)

        return RPC(
            scalar("lineOffset"),
            scalar("sampOffset"),
            scalar("latOffset"),
            scalar("longOffset"),
            scalar("heightOffset"),
            scalar("lineScale"),
            scalar("sampScale"),
            scalar("latScale"),
            scalar("longScale"),
            scalar("heightScale"),
            coef("lineNumCoef"),
            coef("lineDenCoef"),
            coef("sampNumCoef"),
            coef("sampDenCoef"),
        )

    def ground_to_image(self, lon: np.ndarray, lat: np.ndarray, height: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        height = np.asarray(height, dtype=np.float64)
        p = (lat - self.lat_offset) / self.lat_scale
        l = (lon - self.lon_offset) / self.lon_scale
        h = (height - self.height_offset) / self.height_scale
        t = terms(p, l, h)
        line_n = (t @ self.line_num) / (t @ self.line_den)
        samp_n = (t @ self.samp_num) / (t @ self.samp_den)
        return line_n * self.line_scale + self.line_offset, samp_n * self.samp_scale + self.samp_offset

    def image_to_ground(
        self,
        line: float,
        sample: float,
        height: float,
        initial_lon: float | None = None,
        initial_lat: float | None = None,
    ) -> tuple[float, float]:
        # Unknowns are lon/lat; height is fixed. Initial value from RPC offsets is
        # reliable for this small WorldView tile.
        def residual(x: np.ndarray) -> np.ndarray:
            pred_line, pred_samp = self.ground_to_image(x[0], x[1], height)
            return np.array([(pred_line - line) / self.line_scale, (pred_samp - sample) / self.samp_scale])

        res = least_squares(
            residual,
            np.array(
                [
                    self.lon_offset if initial_lon is None else initial_lon,
                    self.lat_offset if initial_lat is None else initial_lat,
                ],
                dtype=np.float64,
            ),
            xtol=1e-13,
            ftol=1e-13,
            gtol=1e-13,
            max_nfev=100,
        )
        return float(res.x[0]), float(res.x[1])


def fit_homography(src_rc: np.ndarray, dst_rc: np.ndarray) -> np.ndarray:
    # Matrix maps source [sample, line, 1] to destination [sample, line, 1].
    src = np.column_stack([src_rc[:, 1], src_rc[:, 0]])
    dst = np.column_stack([dst_rc[:, 1], dst_rc[:, 0]])
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, _, vh = np.linalg.svd(np.asarray(rows, dtype=np.float64))
    h = vh[-1].reshape(3, 3)
    return h / h[2, 2]


def apply_h(h: np.ndarray, line: np.ndarray, sample: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    den = h[2, 0] * sample + h[2, 1] * line + h[2, 2]
    out_samp = (h[0, 0] * sample + h[0, 1] * line + h[0, 2]) / den
    out_line = (h[1, 0] * sample + h[1, 1] * line + h[1, 2]) / den
    return out_line, out_samp


def estimate_left_epipolar_axes(left: RPC, right: RPC) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    right_center_line = (IMAGE_SIZE - 1.0) / 2.0
    right_center_sample = (IMAGE_SIZE - 1.0) / 2.0
    h0 = right.height_offset
    h1 = h0 + max(abs(right.height_scale) * 0.02, 20.0)

    lon0, lat0 = right.image_to_ground(right_center_line, right_center_sample, h0)
    lon1, lat1 = right.image_to_ground(right_center_line, right_center_sample, h1, lon0, lat0)
    left_line0, left_sample0 = left.ground_to_image(lon0, lat0, h0)
    left_line1, left_sample1 = left.ground_to_image(lon1, lat1, h1)

    sample_axis = np.asarray([left_line1 - left_line0, left_sample1 - left_sample0], dtype=np.float64)
    norm = float(np.linalg.norm(sample_axis))
    if norm < 1e-9:
        raise RuntimeError("Cannot estimate left-image epipolar direction")
    sample_axis /= norm
    line_axis = np.asarray([sample_axis[1], -sample_axis[0]], dtype=np.float64)
    angle_deg = float(np.degrees(np.arctan2(sample_axis[0], sample_axis[1])))
    info = {
        "h0": float(h0),
        "h1": float(h1),
        "left_line0": float(left_line0),
        "left_sample0": float(left_sample0),
        "left_line1": float(left_line1),
        "left_sample1": float(left_sample1),
        "left_epipolar_angle_deg_from_sample_axis": angle_deg,
    }
    return sample_axis, line_axis, info


def strip_index(epi_line: float) -> int:
    idx = int(np.searchsorted(STRIP_BOUNDS, epi_line, side="right") - 1)
    return max(0, min(N_SEGMENTS - 1, idx))


def bilinear_row(image: np.ndarray, src_samp: np.ndarray, src_line: np.ndarray) -> np.ndarray:
    h, w, c = image.shape
    out = np.full((src_samp.size, c), NODATA, dtype=np.float64)
    ok = (src_samp >= 0) & (src_samp < w - 1) & (src_line >= 0) & (src_line < h - 1)
    if not np.any(ok):
        return out
    x0 = np.floor(src_samp[ok]).astype(np.int64)
    y0 = np.floor(src_line[ok]).astype(np.int64)
    dx = src_samp[ok] - x0
    dy = src_line[ok] - y0
    top = image[y0, x0] * (1 - dx)[:, None] + image[y0, x0 + 1] * dx[:, None]
    bot = image[y0 + 1, x0] * (1 - dx)[:, None] + image[y0 + 1, x0 + 1] * dx[:, None]
    out[ok] = top * (1 - dy)[:, None] + bot * dy[:, None]
    return out


def rectify_image(src_path: Path, map_info: dict, out_path: Path) -> None:
    img = tifffile.imread(src_path).astype(np.float64)
    result = np.zeros((EPI_HEIGHT, EPI_WIDTH, 3), dtype=np.uint8)
    epi_samples = np.arange(EPI_WIDTH, dtype=np.float64)
    for seg in map_info["segments"]:
        inv_h = np.linalg.inv(np.asarray(seg["matrix"], dtype=np.float64))
        for epi_line in range(int(seg["row_start"]), int(seg["row_end"])):
            line_arr = np.full(EPI_WIDTH, float(epi_line), dtype=np.float64)
            src_line, src_samp = apply_h(inv_h, line_arr, epi_samples)
            row = bilinear_row(img, src_samp, src_line)
            valid = np.all(row != NODATA, axis=1)
            result[epi_line, valid] = np.clip(np.rint(row[valid]), 0, 255).astype(np.uint8)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(out_path, result, photometric="rgb")


def build_epipolar_grid(left: RPC, right: RPC) -> tuple[dict, list[list[float]]]:
    sample_axis, line_axis, direction_info = estimate_left_epipolar_axes(left, right)
    left_center = np.asarray([(IMAGE_SIZE - 1.0) / 2.0, (IMAGE_SIZE - 1.0) / 2.0], dtype=np.float64)
    canvas_center = np.asarray([(EPI_HEIGHT - 1.0) / 2.0, (EPI_WIDTH - 1.0) / 2.0], dtype=np.float64)

    def target_to_left(epi_line: float, epi_samp: float) -> tuple[float, float]:
        offset = (epi_line - canvas_center[0]) * line_axis + (epi_samp - canvas_center[1]) * sample_axis
        left_line, left_samp = left_center + offset
        return float(left_line), float(left_samp)

    left_segments = []
    right_segments = []
    nodes = []
    h_ref = left.height_offset

    if len(STRIP_BOUNDS) != N_SEGMENTS + 1:
        raise ValueError("STRIP_BOUNDS must contain N_SEGMENTS + 1 entries")

    for seg_idx, (row_start, row_end) in enumerate(zip(STRIP_BOUNDS[:-1], STRIP_BOUNDS[1:])):
        band_height = row_end - row_start
        left_src_pts = []
        right_src_pts = []
        epi_pts = []
        grid_rows = []
        prev_lon = left.lon_offset
        prev_lat = left.lat_offset
        epi_lines = np.linspace(row_start + 0.10 * band_height, row_end - 0.10 * band_height, 9)
        epi_samps = np.linspace(0.05 * EPI_WIDTH, 0.95 * EPI_WIDTH, 9)
        for epi_line in epi_lines:
            for epi_samp in epi_samps:
                left_line, left_samp = target_to_left(float(epi_line), float(epi_samp))
                if not (0 <= left_line < IMAGE_SIZE and 0 <= left_samp < IMAGE_SIZE):
                    continue
                lon, lat = left.image_to_ground(left_line, left_samp, h_ref, prev_lon, prev_lat)
                prev_lon, prev_lat = lon, lat
                right_line, right_samp = right.ground_to_image(lon, lat, h_ref)
                if not (0 <= right_line < IMAGE_SIZE and 0 <= right_samp < IMAGE_SIZE):
                    continue
                left_src_pts.append([left_line, left_samp])
                right_src_pts.append([right_line, right_samp])
                epi_pts.append([epi_line, epi_samp])
                grid_rows.append([epi_line, epi_samp, left_line, left_samp, right_line, right_samp])
        if len(epi_pts) < 4:
            raise ValueError(f"Strip {seg_idx} has too few valid control points")
        left_h = fit_homography(np.asarray(left_src_pts), np.asarray(epi_pts))
        right_h = fit_homography(np.asarray(right_src_pts), np.asarray(epi_pts))
        left_segments.append({"row_start": row_start, "row_end": row_end, "matrix": left_h.tolist()})
        right_segments.append({"row_start": row_start, "row_end": row_end, "matrix": right_h.tolist()})
        nodes.extend(grid_rows)

    grid = {
        "description": "Epipolar local pixel grid generated from original RPC models. CRS is None; transform is identity.",
        "width": EPI_WIDTH,
        "height": EPI_HEIGHT,
        "transform": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        "left_map": {"type": "piecewise_homography", "out_width": EPI_WIDTH, "out_height": EPI_HEIGHT, "segments": left_segments},
        "right_map": {"type": "piecewise_homography", "out_width": EPI_WIDTH, "out_height": EPI_HEIGHT, "segments": right_segments},
        "direction": direction_info,
        "node_csv": "epipolar_grid_nodes.csv",
        "control_grid": {"strips": N_SEGMENTS, "rows_per_strip": 9, "cols_per_strip": 9},
    }
    return grid, nodes


def image_background(name: str) -> np.ndarray:
    image = tifffile.imread(DATA / f"{name}.tif")
    if image.ndim == 3:
        return image
    return np.dstack([image, image, image])


def show_image_axis(name: str) -> None:
    plt.imshow(image_background(name), extent=[0, IMAGE_SIZE, IMAGE_SIZE, 0], origin="upper")
    plt.xlim(0, IMAGE_SIZE)
    plt.ylim(IMAGE_SIZE, 0)
    plt.gca().set_aspect("equal", adjustable="box")


def show_zoom_axis(name: str, x_center: float, y_center: float, half_size: float = 120.0) -> None:
    x0 = max(0.0, x_center - half_size)
    x1 = min(float(IMAGE_SIZE), x_center + half_size)
    y0 = max(0.0, y_center - half_size)
    y1 = min(float(IMAGE_SIZE), y_center + half_size)
    plt.imshow(image_background(name), extent=[0, IMAGE_SIZE, IMAGE_SIZE, 0], origin="upper")
    plt.xlim(x0, x1)
    plt.ylim(y1, y0)
    plt.gca().set_aspect("equal", adjustable="box")


def line_segment_in_image(c: float, r: float, dc: float, dr: float) -> tuple[np.ndarray, np.ndarray]:
    candidates = []
    if abs(dc) > 1e-12:
        for x in (0.0, float(IMAGE_SIZE - 1)):
            t = (x - c) / dc
            y = r + t * dr
            if 0.0 <= y <= IMAGE_SIZE - 1:
                candidates.append((x, y))
    if abs(dr) > 1e-12:
        for y in (0.0, float(IMAGE_SIZE - 1)):
            t = (y - r) / dr
            x = c + t * dc
            if 0.0 <= x <= IMAGE_SIZE - 1:
                candidates.append((x, y))

    unique = []
    for pt in candidates:
        if not any(abs(pt[0] - old[0]) < 1e-7 and abs(pt[1] - old[1]) < 1e-7 for old in unique):
            unique.append(pt)
    if len(unique) < 2:
        return np.array([c]), np.array([r])
    unique.sort(key=lambda pt: (pt[0] - c) ** 2 + (pt[1] - r) ** 2)
    p0, p1 = unique[0], unique[-1]
    return np.array([p0[0], p1[0]]), np.array([p0[1], p1[1]])


def generate_task1(left: RPC, right: RPC) -> None:
    # The first two sub-tasks fix the center of the left image and observe its
    # corresponding epipolar trajectory on the right image. 1023.5 is the center
    # in the pixel-center coordinate convention emphasized in the task document.
    center = (IMAGE_SIZE - 1) / 2
    h0 = left.height_offset
    h1 = left.height_offset + 20.0
    lon0, lat0 = left.image_to_ground(center, center, h0)
    lon1, lat1 = left.image_to_ground(center, center, h1)
    r0, c0 = right.ground_to_image(lon0, lat0, h0)
    r1, c1 = right.ground_to_image(lon1, lat1, h1)
    dr = float(r1 - r0)
    dc = float(c1 - c0)
    theta = math.degrees(math.atan2(dr, dc))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "task1_epipolar_direction.txt").write_text(
        f"Right-image epipolar direction vector:\n"
        f"delta_r = {dr:.10f}\n"
        f"delta_c = {dc:.10f}\n"
        f"Right-image epipolar direction angle:\n"
        f"theta_deg = {theta:.10f}\n",
        encoding="utf-8",
    )

    zs = np.linspace(h0, h1, 80)
    pts = []
    for z in zs:
        lon, lat = left.image_to_ground(center, center, float(z))
        rr, cc = right.ground_to_image(lon, lat, z)
        pts.append([cc, rr])
    pts = np.asarray(pts)
    line_x, line_y = line_segment_in_image(c0, r0, dc, dr)
    fig, axes = plt.subplots(1, 2, figsize=(18, 9), dpi=220)
    plt.sca(axes[0])
    show_image_axis(RIGHT_NAME)
    plt.plot(line_x, line_y, "r-", linewidth=2.2, label="estimated epipolar line")
    plt.plot(pts[:, 0], pts[:, 1], color="yellow", linewidth=1.0, alpha=0.9, label="projection trajectory")
    plt.scatter([c0, c1], [r0, r1], c=["cyan", "white"], edgecolors="black", linewidths=0.4, s=28)
    plt.title("Task 1 Epipolar Direction on Right Image")
    plt.xlabel("Sample / column")
    plt.ylabel("Line / row")
    plt.legend(loc="upper right")
    plt.grid(True, alpha=0.3)
    plt.sca(axes[1])
    show_zoom_axis(RIGHT_NAME, float(np.mean(pts[:, 0])), float(np.mean(pts[:, 1])), half_size=90)
    plt.plot(line_x, line_y, "r-", linewidth=2.0)
    plt.plot(pts[:, 0], pts[:, 1], color="yellow", linewidth=1.5, alpha=0.95)
    plt.scatter([c0, c1], [r0, r1], c=["cyan", "white"], edgecolors="black", linewidths=0.4, s=32)
    plt.title("Task 1 Local Zoom")
    plt.xlabel("Sample / column")
    plt.ylabel("Line / row")
    plt.legend(["estimated epipolar line", "projection trajectory"], loc="upper right")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT / "task1_epipolar_direction.png")
    plt.close()


def generate_task2(left: RPC, right: RPC) -> None:
    center = (IMAGE_SIZE - 1) / 2
    zs = np.linspace(left.height_offset - left.height_scale, left.height_offset + left.height_scale, TASK2_SAMPLE_COUNT)
    pts = []
    for z in zs:
        lon, lat = left.image_to_ground(center, center, float(z))
        rr, cc = right.ground_to_image(lon, lat, z)
        pts.append([cc, rr])
    pts = np.asarray(pts)
    x = pts[:, 0]
    y = pts[:, 1]
    k, b = np.polyfit(x, y, 1)
    pred_y = k * x + b
    rmse_r = float(np.sqrt(np.mean((y - pred_y) ** 2)))
    rmse_orth = float(np.sqrt(np.mean(((k * x - y + b) / math.sqrt(k * k + 1)) ** 2)))
    (OUT / "task2_epipolar_curve_fit.txt").write_text(
        f"k = {k:.10f}\n"
        f"b = {b:.10f}\n"
        f"RMSE_r = {rmse_r:.10f} px\n"
        f"RMSE_orth = {rmse_orth:.10f} px\n",
        encoding="utf-8",
    )
    fig, axes = plt.subplots(1, 2, figsize=(18, 9), dpi=220)
    plt.sca(axes[0])
    show_image_axis(RIGHT_NAME)
    plt.plot(x, y, "o", markersize=2, color="cyan", label="RPC projected trajectory")
    xx = np.linspace(0, IMAGE_SIZE - 1, 400)
    plt.plot(xx, k * xx + b, "r-", linewidth=2, label="least-squares line")
    plt.title("Task 2 Epipolar Curve and Fitted Line")
    plt.xlabel("Sample / column")
    plt.ylabel("Line / row")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.sca(axes[1])
    show_zoom_axis(RIGHT_NAME, float(np.mean(x)), float(np.mean(y)), half_size=110)
    plt.plot(x, y, "o", markersize=2.4, color="cyan")
    plt.plot(xx, k * xx + b, "r-", linewidth=2)
    plt.title("Task 2 Local Zoom")
    plt.xlabel("Sample / column")
    plt.ylabel("Line / row")
    plt.legend(["RPC projected trajectory", "least-squares line"], loc="upper right")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT / "task2_epipolar_curve_fit.png")
    plt.close()


def rpc_fit(
    lat: np.ndarray,
    lon: np.ndarray,
    height: np.ndarray,
    line: np.ndarray,
    samp: np.ndarray,
    source_rpc: RPC,
) -> RPC:
    # Keep the ground-coordinate normalization consistent with the source RPC.
    # Fitting only on the supplied consistency points is much better conditioned
    # this way than using the small terrain-point bounding box as the scale.
    lat_off = source_rpc.lat_offset
    lon_off = source_rpc.lon_offset
    h_off = source_rpc.height_offset
    line_off = (EPI_HEIGHT - 1) / 2
    samp_off = (EPI_WIDTH - 1) / 2
    lat_scale = source_rpc.lat_scale
    lon_scale = source_rpc.lon_scale
    h_scale = source_rpc.height_scale
    line_scale = (EPI_HEIGHT - 1) / 2
    samp_scale = (EPI_WIDTH - 1) / 2
    p = (lat - lat_off) / lat_scale
    l = (lon - lon_off) / lon_scale
    h = (height - h_off) / h_scale
    t = terms(p, l, h)

    def solve(target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        y = target
        a = np.column_stack([t, -(y[:, None] * t[:, 1:])])
        sol, *_ = np.linalg.lstsq(a, y, rcond=None)
        num = sol[:20]
        den = np.r_[1.0, sol[20:]]
        return num, den

    line_n = (line - line_off) / line_scale
    samp_n = (samp - samp_off) / samp_scale
    line_num, line_den = solve(line_n)
    samp_num, samp_den = solve(samp_n)
    return RPC(line_off, samp_off, lat_off, lon_off, h_off, line_scale, samp_scale, lat_scale, lon_scale, h_scale, line_num, line_den, samp_num, samp_den)


def write_rpb(path: Path, rpc: RPC) -> None:
    def coef_block(name: str, vals: np.ndarray) -> str:
        lines = [f"\t{name} = ("]
        for i, v in enumerate(vals):
            sep = "," if i < len(vals) - 1 else ""
            lines.append(f"\t\t\t{v:+.15e}{sep}")
        lines.append("\t\t);")
        return "\n".join(lines)

    text = "\n".join(
        [
            'satId = "XXX";',
            'bandId = "XXX";',
            'SpecId = "XXX";',
            "BEGIN_GROUP = IMAGE",
            "\terrBias =   1.0;",
            "\terrRand =   0.0;",
            f"\tlineOffset = {rpc.line_offset:.18f};",
            f"\tsampOffset = {rpc.samp_offset:.18f};",
            f"\tlatOffset = {rpc.lat_offset:.18f};",
            f"\tlongOffset = {rpc.lon_offset:.18f};",
            f"\theightOffset = {rpc.height_offset:.18f};",
            f"\tlineScale = {rpc.line_scale:.18f};",
            f"\tsampScale = {rpc.samp_scale:.18f};",
            f"\tlatScale = {rpc.lat_scale:.18f};",
            f"\tlongScale = {rpc.lon_scale:.18f};",
            f"\theightScale = {rpc.height_scale:.18f};",
            coef_block("lineNumCoef", rpc.line_num),
            coef_block("lineDenCoef", rpc.line_den),
            coef_block("sampNumCoef", rpc.samp_num),
            coef_block("sampDenCoef", rpc.samp_den),
            "END_GROUP = IMAGE",
            "END;",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def generate_task4(left: RPC, right: RPC, grid: dict) -> None:
    def to_epi(src_rpc: RPC, map_info: dict, lon: np.ndarray, lat: np.ndarray, h: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        line, samp = src_rpc.ground_to_image(lon, lat, h)
        out_line = np.full_like(line, np.nan)
        out_samp = np.full_like(samp, np.nan)
        valid = np.zeros_like(line, dtype=bool)
        for seg in map_info["segments"]:
            hs = np.asarray(seg["matrix"], dtype=np.float64)
            tmp_line, tmp_samp = apply_h(hs, line, samp)
            mask = (
                (tmp_line >= seg["row_start"])
                & (tmp_line < seg["row_end"])
                & (tmp_samp >= 0)
                & (tmp_samp < EPI_WIDTH)
            )
            out_line[mask] = tmp_line[mask]
            out_samp[mask] = tmp_samp[mask]
            valid[mask] = True
        return out_line, out_samp, valid

    def virtual_control_points(src_rpc: RPC, map_info: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        img_lines = np.linspace(96, IMAGE_SIZE - 97, 21)
        img_samps = np.linspace(96, IMAGE_SIZE - 97, 21)
        heights = np.linspace(
            src_rpc.height_offset - src_rpc.height_scale,
            src_rpc.height_offset + src_rpc.height_scale,
            7,
        )
        lon_list = []
        lat_list = []
        h_list = []
        line_list = []
        samp_list = []
        for height in heights:
            for line in img_lines:
                for samp in img_samps:
                    lon0, lat0 = src_rpc.image_to_ground(float(line), float(samp), float(height))
                    epi_line, epi_samp, ok = to_epi(
                        src_rpc,
                        map_info,
                        np.array([lon0]),
                        np.array([lat0]),
                        np.array([height]),
                    )
                    if ok[0]:
                        lon_list.append(lon0)
                        lat_list.append(lat0)
                        h_list.append(height)
                        line_list.append(epi_line[0])
                        samp_list.append(epi_samp[0])
        return (
            np.asarray(lat_list, dtype=np.float64),
            np.asarray(lon_list, dtype=np.float64),
            np.asarray(h_list, dtype=np.float64),
            np.asarray(line_list, dtype=np.float64),
            np.asarray(samp_list, dtype=np.float64),
        )

    left_lat, left_lon, left_h, left_line, left_samp = virtual_control_points(left, grid["left_map"])
    right_lat, right_lon, right_h, right_line, right_samp = virtual_control_points(right, grid["right_map"])
    left_rpc = rpc_fit(left_lat, left_lon, left_h, left_line, left_samp, left)
    right_rpc = rpc_fit(right_lat, right_lon, right_h, right_line, right_samp, right)
    write_rpb(OUT34 / f"{LEFT_NAME}_epipolar.rpb", left_rpc)
    write_rpb(OUT34 / f"{RIGHT_NAME}_epipolar.rpb", right_rpc)

    rows = list(csv.DictReader(open(GROUND_CSV, "r", encoding="utf-8-sig")))
    lon = np.array([float(r["lon"]) for r in rows])
    lat = np.array([float(r["lat"]) for r in rows])
    h = np.array([float(r["height"]) for r in rows])
    left_line, left_samp, left_valid = to_epi(left, grid["left_map"], lon, lat, h)
    right_line, right_samp, right_valid = to_epi(right, grid["right_map"], lon, lat, h)

    ll2, ls2 = left_rpc.ground_to_image(lon[left_valid], lat[left_valid], h[left_valid])
    rl2, rs2 = right_rpc.ground_to_image(lon[right_valid], lat[right_valid], h[right_valid])
    left_rmse = float(np.sqrt(np.mean((ll2 - left_line[left_valid]) ** 2 + (ls2 - left_samp[left_valid]) ** 2)))
    right_rmse = float(np.sqrt(np.mean((rl2 - right_line[right_valid]) ** 2 + (rs2 - right_samp[right_valid]) ** 2)))
    (OUT34 / "rpc_consistency_report.txt").write_text(
        "epipolar_grid.json stores the piecewise homography maps computed from the original RPC models.\n"
        "epipolar_grid_nodes.csv stores sampled nodes of the epipolar mapping.\n"
        "Program result\n"
        f"Check points: {len(rows)}\n"
        f"Left virtual control points: {len(left_lat)}\n"
        f"Right virtual control points: {len(right_lat)}\n"
        f"Left epipolar RPC: valid points {int(left_valid.sum())}, total RMSE = {left_rmse:.6f} px\n"
        f"Right epipolar RPC: valid points {int(right_valid.sum())}, total RMSE = {right_rmse:.6f} px\n",
        encoding="utf-8",
    )


def save_grid(grid: dict, nodes: list[list[float]]) -> None:
    OUT34.mkdir(parents=True, exist_ok=True)
    (OUT34 / "epipolar_grid.json").write_text(json.dumps(grid, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT34 / "epipolar_grid_nodes.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["epi_line", "epi_sample", "left_line", "left_sample", "right_line", "right_sample"])
        w.writerows(nodes)


def image_point_to_epi(line: float, samp: float, map_info: dict) -> tuple[float, float, bool]:
    best_line = np.nan
    best_samp = np.nan
    best_dist = float("inf")
    for seg in map_info["segments"]:
        h = np.asarray(seg["matrix"], dtype=np.float64)
        epi_line, epi_samp = apply_h(h, np.array([line]), np.array([samp]))
        line0 = float(epi_line[0])
        samp0 = float(epi_samp[0])
        if seg["row_start"] <= line0 < seg["row_end"]:
            return line0, samp0, 0 <= samp0 < EPI_WIDTH
        dist = min(abs(line0 - seg["row_start"]), abs(line0 - seg["row_end"]))
        if dist < best_dist:
            best_dist = dist
            best_line = line0
            best_samp = samp0
    return best_line, best_samp, bool(0 <= best_samp < EPI_WIDTH and 0 <= best_line < EPI_HEIGHT)


def check_vertical_parallax(left: RPC, right: RPC, grid: dict) -> None:
    samples = np.linspace(0.15 * IMAGE_SIZE, 0.85 * IMAGE_SIZE, 7)
    lines = np.linspace(0.15 * IMAGE_SIZE, 0.85 * IMAGE_SIZE, 7)
    h_span = max(abs(left.height_scale) * 0.25, 100.0)
    heights = np.linspace(left.height_offset - h_span, left.height_offset + h_span, 5)
    v_list = []
    rows = []
    for left_line in lines:
        for left_samp in samples:
            epi_ll, epi_ls, ok_l = image_point_to_epi(float(left_line), float(left_samp), grid["left_map"])
            if not ok_l:
                continue
            prev_lon = left.lon_offset
            prev_lat = left.lat_offset
            for h_ref in heights:
                lon, lat = left.image_to_ground(float(left_line), float(left_samp), float(h_ref), prev_lon, prev_lat)
                prev_lon, prev_lat = lon, lat
                right_line, right_samp = right.ground_to_image(lon, lat, h_ref)
                if not (0 <= right_line < IMAGE_SIZE and 0 <= right_samp < IMAGE_SIZE):
                    continue
                epi_rl, epi_rs, ok_r = image_point_to_epi(float(right_line), float(right_samp), grid["right_map"])
                if ok_r:
                    v = epi_rl - epi_ll
                    v_list.append(v)
                    rows.append([left_line, left_samp, h_ref, right_line, right_samp, epi_ll, epi_ls, epi_rl, epi_rs, v])

    v_arr = np.asarray(v_list, dtype=np.float64)
    rmse = float(np.sqrt(np.mean(v_arr**2))) if v_arr.size else float("nan")
    mean_abs = float(np.mean(np.abs(v_arr))) if v_arr.size else float("nan")
    max_abs = float(np.max(np.abs(v_arr))) if v_arr.size else float("nan")

    with (OUT34 / "vertical_parallax_check.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "left_line",
                "left_sample",
                "height",
                "right_line",
                "right_sample",
                "left_epi_line",
                "left_epi_sample",
                "right_epi_line",
                "right_epi_sample",
                "vertical_parallax",
            ]
        )
        w.writerows(rows)

    (OUT34 / "vertical_parallax_report.txt").write_text(
        "Vertical parallax check on virtual ground control points\n"
        f"Height range: {float(heights[0]):.6f} to {float(heights[-1]):.6f}\n"
        f"Check points: {len(v_arr)}\n"
        f"RMSE_v: {rmse:.6f} px\n"
        f"Mean_abs_v: {mean_abs:.6f} px\n"
        f"Max_abs_v: {max_abs:.6f} px\n"
        "Acceptance: RMSE_v should be within 0.4 px, and DPGScope visual inspection should show no obvious vertical parallax.\n",
        encoding="utf-8",
    )


def compare_with_reference() -> None:
    lines = []
    lines.append("task1_epipolar_direction.txt: generated from RPC; reference text exists in the reference folder.")
    lines.append("task2_epipolar_curve_fit.txt: generated from RPC; reference text exists in the reference folder.")
    for stem in [RIGHT_NAME, LEFT_NAME]:
        out_path = OUT34 / f"{stem}_epipolar.tif"
        ref_path = REF / f"{stem}_EPI_student.tif"
        if out_path.exists() and ref_path.exists():
            out_img = tifffile.imread(out_path)
            ref_img = tifffile.imread(ref_path)
            valid = np.all(out_img != NODATA, axis=2) if out_img.ndim == 3 else out_img != NODATA
            d = out_img[valid].astype(np.int64) - ref_img[valid].astype(np.int64)
            if d.size:
                lines.append(
                    f"{stem}_epipolar.tif: shape={out_img.shape}, dtype={out_img.dtype}, "
                    f"valid_pixels={int(valid.sum())}, mean_abs_diff={np.mean(np.abs(d)):.4f}, "
                    f"max_abs_diff={np.max(np.abs(d))}"
                )
            else:
                lines.append(f"{stem}_epipolar.tif: no valid pixels to compare")
    (OUT / "reference_comparison.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Complete task 3: satellite-image epipolar rectification.")
    parser.add_argument("--skip-images", action="store_true", help="Skip TIFF resampling to speed up debugging.")
    args = parser.parse_args()

    OUT34.mkdir(parents=True, exist_ok=True)
    left = RPC.from_rpb(DATA / f"{LEFT_NAME}.rpb")
    right = RPC.from_rpb(DATA / f"{RIGHT_NAME}.rpb")

    generate_task1(left, right)
    generate_task2(left, right)
    grid, nodes = build_epipolar_grid(left, right)
    save_grid(grid, nodes)
    check_vertical_parallax(left, right, grid)
    if not args.skip_images:
        rectify_image(DATA / f"{LEFT_NAME}.tif", grid["left_map"], OUT34 / f"{LEFT_NAME}_epipolar.tif")
        rectify_image(DATA / f"{RIGHT_NAME}.tif", grid["right_map"], OUT34 / f"{RIGHT_NAME}_epipolar.tif")
    generate_task4(left, right, grid)
    compare_with_reference()
    print(f"All outputs written to {OUT}")


if __name__ == "__main__":
    main()
