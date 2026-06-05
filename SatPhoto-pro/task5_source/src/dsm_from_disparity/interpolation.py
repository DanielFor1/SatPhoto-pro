"""DSM interpolation methods: nearest neighbor, IDW, and Delaunay TIN."""

import numpy as np
from scipy.spatial import cKDTree, Delaunay


def _to_local_meters(lon: np.ndarray, lat: np.ndarray,
                     lon0: float, lat0: float) -> tuple[np.ndarray, np.ndarray]:
    """Convert lon/lat to local meters relative to a common reference origin (lon0, lat0)."""
    meter_per_deg_lat = 111320.0
    meter_per_deg_lon = 111320.0 * np.cos(np.radians(lat0))
    x = (lon - lon0) * meter_per_deg_lon
    y = (lat - lat0) * meter_per_deg_lat
    return x, y


def interpolate_nearest(point_lon: np.ndarray, point_lat: np.ndarray,
                        point_h: np.ndarray,
                        grid_lon: np.ndarray, grid_lat: np.ndarray,
                        nodata: float = -99999.0) -> np.ndarray:
    """Nearest-neighbor DSM interpolation.

    Args:
        point_lon, point_lat, point_h: Source point cloud (1-D arrays).
        grid_lon, grid_lat: Pixel-center arrays (H, W).
        nodata: Nodata value for output.
    Returns:
        DSM array (H, W).
    """
    lon0, lat0 = float(np.mean(point_lon)), float(np.mean(point_lat))

    px, py = _to_local_meters(point_lon, point_lat, lon0, lat0)
    tree = cKDTree(np.column_stack([px, py]))

    H, W = grid_lon.shape
    gx, gy = _to_local_meters(grid_lon.ravel(), grid_lat.ravel(), lon0, lat0)
    grid_xy = np.column_stack([gx, gy])

    dist, idx = tree.query(grid_xy, k=1)
    dsm = point_h[idx].reshape(H, W).astype(np.float32)
    return dsm


def interpolate_idw(point_lon: np.ndarray, point_lat: np.ndarray,
                    point_h: np.ndarray,
                    grid_lon: np.ndarray, grid_lat: np.ndarray,
                    k: int = 8, power: float = 2.0,
                    max_radius_m: float = 3.0,
                    nodata: float = -99999.0) -> np.ndarray:
    """IDW (Inverse Distance Weighted) DSM interpolation.

    Args:
        point_lon, point_lat, point_h: Source point cloud (1-D arrays).
        grid_lon, grid_lat: Pixel-center arrays (H, W).
        k: Number of nearest neighbors.
        power: Distance weighting power.
        max_radius_m: Maximum search radius in meters.
        nodata: Nodata value for pixels with no neighbor within radius.
    Returns:
        DSM array (H, W).
    """
    lon0, lat0 = float(np.mean(point_lon)), float(np.mean(point_lat))

    px, py = _to_local_meters(point_lon, point_lat, lon0, lat0)
    tree = cKDTree(np.column_stack([px, py]))

    H, W = grid_lon.shape
    gx, gy = _to_local_meters(grid_lon.ravel(), grid_lat.ravel(), lon0, lat0)
    grid_xy = np.column_stack([gx, gy])

    dist, idx = tree.query(grid_xy, k=k)

    dsm = np.full(H * W, nodata, dtype=np.float32)

    for i in range(H * W):
        di = dist[i]
        ii = idx[i]
        # k=1 case: dist/idx are 1-D
        if k == 1:
            di = np.array([di])
            ii = np.array([ii])

        in_radius = di <= max_radius_m
        if not np.any(in_radius):
            continue

        di_valid = di[in_radius]
        ii_valid = ii[in_radius]

        # Avoid division by zero for coincident points
        di_valid = np.maximum(di_valid, 1e-12)
        w = 1.0 / (di_valid ** power)
        dsm[i] = float(np.sum(w * point_h[ii_valid]) / np.sum(w))

    return dsm.reshape(H, W)


def build_point_support_mask(point_lon: np.ndarray, point_lat: np.ndarray,
                              grid_lon: np.ndarray, grid_lat: np.ndarray,
                              spec: dict,
                              support_radius_m: float = 3.0) -> np.ndarray:
    """Build a boolean mask of DSM grid pixels within support_radius_m of any point.

    Maps each point to its nearest grid pixel, then dilates by the radius
    converted to pixels.  Pixels outside this mask have no point support and
    should not receive TIN-interpolated values.
    """
    lat_mid = float(np.mean(point_lat))
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * np.cos(np.radians(lat_mid))

    # Map each point to its nearest grid pixel
    col_idx = ((point_lon - spec["left"]) / spec["res_x"] - 0.5).astype(int)
    row_idx = ((spec["top"] - point_lat) / spec["res_y"] - 0.5).astype(int)

    H, W = grid_lon.shape
    valid = (row_idx >= 0) & (row_idx < H) & (col_idx >= 0) & (col_idx < W)

    occupancy = np.zeros((H, W), dtype=bool)
    occupancy[row_idx[valid], col_idx[valid]] = True

    # Dilate: pixels within radius of any occupied pixel
    radius_px = max(1, int(np.ceil(support_radius_m / (spec["res_x"] * m_per_deg_lon))))
    if radius_px > 1:
        from scipy.ndimage import distance_transform_edt
        dist = distance_transform_edt(~occupancy)
        occupancy = dist <= radius_px

    return occupancy


def interpolate_tin(point_lon: np.ndarray, point_lat: np.ndarray,
                    point_h: np.ndarray,
                    grid_lon: np.ndarray, grid_lat: np.ndarray,
                    nodata: float = -99999.0,
                    support_mask: np.ndarray = None,
                    max_edge_m: float = None) -> np.ndarray:
    """Delaunay TIN-based linear (barycentric) interpolation DSM.

    Args:
        point_lon, point_lat, point_h: Source point cloud.
        grid_lon, grid_lat: Pixel-center arrays (H, W).
        nodata: Nodata for pixels outside the convex hull.
        support_mask: Optional (H,W) boolean mask. Pixels outside the mask
                      are forced to nodata even if inside the convex hull.
        max_edge_m: Optional max triangle edge length in meters. Pixels in
                    triangles with longer edges are forced to nodata.
    Returns:
        DSM array (H, W).
    """
    lon0, lat0 = float(np.mean(point_lon)), float(np.mean(point_lat))

    px, py = _to_local_meters(point_lon, point_lat, lon0, lat0)
    xy = np.column_stack([px, py])
    _, unique_idx = np.unique(np.round(xy, decimals=4), axis=0, return_index=True)
    xy_unique = xy[unique_idx]
    h_unique = point_h[unique_idx]

    tri = Delaunay(xy_unique)

    # Precompute triangle max edge lengths if needed
    tri_max_edge = None
    if max_edge_m is not None:
        tri_verts = xy_unique[tri.simplices]
        edges = np.sqrt(((tri_verts[:, [0, 1, 2], :] -
                          tri_verts[:, [1, 2, 0], :]) ** 2).sum(axis=2))
        tri_max_edge = edges.max(axis=1)

    H, W = grid_lon.shape
    gx, gy = _to_local_meters(grid_lon.ravel(), grid_lat.ravel(), lon0, lat0)
    grid_xy = np.column_stack([gx, gy])

    dsm = np.full(H * W, nodata, dtype=np.float32)

    simplex_idx = tri.find_simplex(grid_xy)
    valid = simplex_idx >= 0

    # Apply support mask filter
    if support_mask is not None:
        valid = valid & support_mask.ravel()

    # Apply max edge filter
    if tri_max_edge is not None:
        valid = valid & (tri_max_edge[simplex_idx] <= max_edge_m)

    if np.any(valid):
        simplices = tri.simplices[simplex_idx[valid]]
        tris = tri.transform[simplex_idx[valid], :2]
        origins = tri.transform[simplex_idx[valid], 2]

        dx = grid_xy[valid, 0] - origins[:, 0]
        dy = grid_xy[valid, 1] - origins[:, 1]

        b1 = tris[:, 0, 0] * dx + tris[:, 0, 1] * dy
        b2 = tris[:, 1, 0] * dx + tris[:, 1, 1] * dy

        lam0 = 1.0 - b1 - b2
        lam1 = b1
        lam2 = b2

        h0 = h_unique[simplices[:, 0]]
        h1 = h_unique[simplices[:, 1]]
        h2 = h_unique[simplices[:, 2]]

        dsm[valid] = (lam0 * h0 + lam1 * h1 + lam2 * h2).astype(np.float32)

        mask_bad = (lam0 < -1e-6) | (lam1 < -1e-6) | (lam2 < -1e-6)
        dsm_flat = dsm
        valid_flat = np.where(valid)[0]
        dsm_flat[valid_flat[mask_bad]] = nodata

    return dsm.reshape(H, W)


def interpolate_tin_hybrid(point_lon: np.ndarray, point_lat: np.ndarray,
                           point_h: np.ndarray,
                           grid_lon: np.ndarray, grid_lat: np.ndarray,
                           max_edge_m: float = 10.0,
                           idw_k: int = 8, idw_power: float = 2.0,
                           idw_max_radius_m: float = 3.0,
                           support_mask: np.ndarray = None,
                           nodata: float = -99999.0) -> np.ndarray:
    """Delaunay TIN + IDW hybrid interpolation.

    Pixels inside triangles with max edge <= max_edge_m use barycentric
    TIN interpolation. Pixels outside the convex hull or in large triangles
    fall back to IDW.

    This combines TIN's accuracy in dense areas with IDW's robustness in
    sparse areas.
    """
    lon0, lat0 = float(np.mean(point_lon)), float(np.mean(point_lat))

    px, py = _to_local_meters(point_lon, point_lat, lon0, lat0)
    xy = np.column_stack([px, py])
    _, unique_idx = np.unique(np.round(xy, decimals=4), axis=0, return_index=True)
    xy_unique = xy[unique_idx]
    h_unique = point_h[unique_idx]

    tri = Delaunay(xy_unique)

    # Precompute max edge length for each triangle
    tri_verts = xy_unique[tri.simplices]
    edges = np.sqrt(((tri_verts[:, [0, 1, 2], :] -
                      tri_verts[:, [1, 2, 0], :]) ** 2).sum(axis=2))
    tri_max_edge = edges.max(axis=1)

    H, W = grid_lon.shape
    gx, gy = _to_local_meters(grid_lon.ravel(), grid_lat.ravel(), lon0, lat0)
    grid_xy = np.column_stack([gx, gy])

    simplex_idx = tri.find_simplex(grid_xy)

    # TIN for pixels in small triangles
    use_tin = (simplex_idx >= 0) & (tri_max_edge[simplex_idx] <= max_edge_m)
    if support_mask is not None:
        use_tin = use_tin & support_mask.ravel()

    dsm = np.full(H * W, nodata, dtype=np.float32)

    if np.any(use_tin):
        simplices = tri.simplices[simplex_idx[use_tin]]
        tris = tri.transform[simplex_idx[use_tin], :2]
        origins = tri.transform[simplex_idx[use_tin], 2]
        dx = grid_xy[use_tin, 0] - origins[:, 0]
        dy = grid_xy[use_tin, 1] - origins[:, 1]
        b1 = tris[:, 0, 0] * dx + tris[:, 0, 1] * dy
        b2 = tris[:, 1, 0] * dx + tris[:, 1, 1] * dy
        lam0 = 1.0 - b1 - b2
        lam1 = b1
        lam2 = b2

        h0 = h_unique[simplices[:, 0]]
        h1 = h_unique[simplices[:, 1]]
        h2 = h_unique[simplices[:, 2]]
        dsm[use_tin] = (lam0 * h0 + lam1 * h1 + lam2 * h2).astype(np.float32)

        bad = (lam0 < -1e-6) | (lam1 < -1e-6) | (lam2 < -1e-6)
        uf = np.where(use_tin)[0]
        dsm[uf[bad]] = nodata

    # IDW fallback for remaining pixels
    use_idw = dsm == nodata
    if np.any(use_idw):
        idw = interpolate_idw(point_lon, point_lat, point_h,
                              grid_lon, grid_lat,
                              k=idw_k, power=idw_power,
                              max_radius_m=idw_max_radius_m,
                              nodata=nodata)
        dsm[use_idw] = idw.ravel()[use_idw]

    return dsm.reshape(H, W)
