"""Forward intersection of same-name points using RPC stereo images."""

import numpy as np
from scipy.optimize import least_squares

from .rpc_model import RPCModel


def _residuals(ground: np.ndarray, rpc_left: RPCModel, rpc_right: RPCModel,
               obs_left: np.ndarray, obs_right: np.ndarray) -> np.ndarray:
    """Residuals between projected and observed image coordinates.

    Args:
        ground: [lon, lat, h] guess.
        rpc_left, rpc_right: RPC models.
        obs_left: [line, sample] observed in left image.
        obs_right: [line, sample] observed in right image.
    Returns:
        4-element residual vector: [dline_L, dsample_L, dline_R, dsample_R].
    """
    lon, lat, h = ground
    line_l, samp_l = rpc_left.project(lon, lat, h)
    line_r, samp_r = rpc_right.project(lon, lat, h)
    return np.array([
        float(line_l - obs_left[0]),
        float(samp_l - obs_left[1]),
        float(line_r - obs_right[0]),
        float(samp_r - obs_right[1]),
    ])


def intersect_single(rpc_left: RPCModel, rpc_right: RPCModel,
                     obs_left: tuple[float, float],
                     obs_right: tuple[float, float],
                     initial: tuple[float, float, float] = None) -> tuple[float, float, float]:
    """Forward-intersect a single tie point.

    Args:
        rpc_left: Left image RPC model.
        rpc_right: Right image RPC model.
        obs_left: (line, sample) in left image.
        obs_right: (line, sample) in right image.
        initial: Optional (lon, lat, h) initial guess. If None, uses RPC offsets.
    Returns:
        (lon, lat, ellipsoid_height) in degrees/meters.
    """
    obs_l = np.array(obs_left, dtype=np.float64)
    obs_r = np.array(obs_right, dtype=np.float64)

    if initial is None:
        x0 = np.array([rpc_left.long_offset, rpc_left.lat_offset,
                       rpc_left.height_offset])
    else:
        x0 = np.array(initial, dtype=np.float64)

    result = least_squares(
        lambda x: _residuals(x, rpc_left, rpc_right, obs_l, obs_r),
        x0,
        method="lm",
        ftol=1e-12,
        xtol=1e-12,
        gtol=1e-12,
    )
    return float(result.x[0]), float(result.x[1]), float(result.x[2])


def intersect_many(rpc_left: RPCModel, rpc_right: RPCModel,
                   line_left: np.ndarray, samp_left: np.ndarray,
                   line_right: np.ndarray, samp_right: np.ndarray,
                   initial: tuple[float, float, float] = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Forward-intersect many points.

    Args:
        rpc_left, rpc_right: RPC models.
        line_left, samp_left: Left image observations (1-D arrays).
        line_right, samp_right: Right image observations (1-D arrays).
        initial: Optional initial guess for all points.
    Returns:
        (lon, lat, height) arrays.
    """
    n = len(line_left)
    lons = np.empty(n, dtype=np.float64)
    lats = np.empty(n, dtype=np.float64)
    heights = np.empty(n, dtype=np.float64)
    for i in range(n):
        lon, lat, h = intersect_single(
            rpc_left, rpc_right,
            (float(line_left[i]), float(samp_left[i])),
            (float(line_right[i]), float(samp_right[i])),
            initial,
        )
        lons[i] = lon
        lats[i] = lat
        heights[i] = h
    return lons, lats, heights


def _project_with_jacobian_cupy(rpc, lon, lat, h_geo, cp, ref_rpc=None):
    """CuPy GPU projection + analytic Jacobian.

    Args:
        rpc: RPCModel.
        lon, lat, h_geo: CuPy arrays, geographic coordinates.
        cp: cupy module reference.
        ref_rpc: reference RPC for Jacobian chain rule.
    Returns:
        line, samp: CuPy arrays (N,).
        J: CuPy array (N, 2, 3), columns = d/d(u_ref, v_ref, w_ref).
    """
    from .rpc_model import RPC_TERMS

    # Normalize by self's offsets/scales (same as CPU project_with_jacobian)
    u = (lon - rpc.long_offset) / rpc.long_scale
    v = (lat - rpc.lat_offset) / rpc.lat_scale
    w = (h_geo - rpc.height_offset) / rpc.height_scale

    N = len(u)
    u_pow = cp.ones((N, 20), dtype=cp.float64)
    v_pow = cp.ones((N, 20), dtype=cp.float64)
    w_pow = cp.ones((N, 20), dtype=cp.float64)
    for k, (pu, pv, pw) in enumerate(RPC_TERMS):
        if pu > 0: u_pow[:, k] = u ** pu
        if pv > 0: v_pow[:, k] = v ** pv
        if pw > 0: w_pow[:, k] = w ** pw
    term = u_pow * v_pow * w_pow

    ln_c = cp.asarray(rpc.line_num_coef, dtype=cp.float64)
    ld_c = cp.asarray(rpc.line_den_coef, dtype=cp.float64)
    sn_c = cp.asarray(rpc.samp_num_coef, dtype=cp.float64)
    sd_c = cp.asarray(rpc.samp_den_coef, dtype=cp.float64)

    l_num = term @ ln_c; l_den = term @ ld_c
    s_num = term @ sn_c; s_den = term @ sd_c
    line = l_num / l_den * rpc.line_scale + rpc.line_offset
    samp = s_num / s_den * rpc.samp_scale + rpc.samp_offset

    du_p = cp.zeros((N, 20), dtype=cp.float64)
    dv_p = cp.zeros((N, 20), dtype=cp.float64)
    dw_p = cp.zeros((N, 20), dtype=cp.float64)
    for k, (pu, pv, pw) in enumerate(RPC_TERMS):
        if pu > 0: du_p[:, k] = pu * (u ** (pu-1)) * v_pow[:, k] * w_pow[:, k]
        if pv > 0: dv_p[:, k] = pv * (v ** (pv-1)) * u_pow[:, k] * w_pow[:, k]
        if pw > 0: dw_p[:, k] = pw * (w ** (pw-1)) * u_pow[:, k] * v_pow[:, k]

    dln_u = (du_p @ ln_c * l_den - l_num * (du_p @ ld_c)) / (l_den ** 2)
    dln_v = (dv_p @ ln_c * l_den - l_num * (dv_p @ ld_c)) / (l_den ** 2)
    dln_w = (dw_p @ ln_c * l_den - l_num * (dw_p @ ld_c)) / (l_den ** 2)
    dsn_u = (du_p @ sn_c * s_den - s_num * (du_p @ sd_c)) / (s_den ** 2)
    dsn_v = (dv_p @ sn_c * s_den - s_num * (dv_p @ sd_c)) / (s_den ** 2)
    dsn_w = (dw_p @ sn_c * s_den - s_num * (dw_p @ sd_c)) / (s_den ** 2)

    J = cp.zeros((N, 2, 3), dtype=cp.float64)
    J[:, 0, 0] = dln_u * rpc.line_scale
    J[:, 0, 1] = dln_v * rpc.line_scale
    J[:, 0, 2] = dln_w * rpc.line_scale
    J[:, 1, 0] = dsn_u * rpc.samp_scale
    J[:, 1, 1] = dsn_v * rpc.samp_scale
    J[:, 1, 2] = dsn_w * rpc.samp_scale

    if ref_rpc is not None and ref_rpc is not rpc:
        J[:, :, 0] *= ref_rpc.long_scale / rpc.long_scale
        J[:, :, 1] *= ref_rpc.lat_scale / rpc.lat_scale
        J[:, :, 2] *= ref_rpc.height_scale / rpc.height_scale

    return line, samp, J


def intersect_many_gpu(rpc_left: RPCModel, rpc_right: RPCModel,
                        line_left: np.ndarray, samp_left: np.ndarray,
                        line_right: np.ndarray, samp_right: np.ndarray,
                        initial: tuple[float, float, float] = None,
                        max_iter: int = 10, damping: float = 1e-3,
                        ftol: float = 1e-10) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """GPU-accelerated Gauss-Newton forward intersection using CuPy.

    Full Gauss-Newton iteration on GPU: residuals, Jacobian, normal equations,
    and linear solve all stay on GPU. Only final lon/lat/height are transferred
    back to CPU.

    Requires CuPy installed with a CUDA-matched package (e.g. cupy-cuda12x).
    """
    try:
        import cupy as cp
    except ImportError:
        raise RuntimeError(
            "GPU intersection requires CuPy. "
            "Install a CUDA-matched cupy package, e.g.: pip install cupy-cuda12x"
        )

    N = len(line_left)
    r_l = cp.asarray(line_left, dtype=cp.float64).ravel()
    s_l = cp.asarray(samp_left, dtype=cp.float64).ravel()
    r_r = cp.asarray(line_right, dtype=cp.float64).ravel()
    s_r = cp.asarray(samp_right, dtype=cp.float64).ravel()

    # State: left-RPC normalized (u_ref, v_ref, w_ref) on GPU
    if initial is None:
        u = cp.zeros(N, dtype=cp.float64)
        v = cp.zeros(N, dtype=cp.float64)
        w = cp.full(N, (rpc_left.height_offset - rpc_left.height_offset) / rpc_left.height_scale, dtype=cp.float64)
        # u_ref = (lon_offset - lon_offset) / scale = 0, same for v
        u[:] = 0.0
        v[:] = 0.0
        w[:] = 0.0
    else:
        u = cp.full(N, (initial[0] - rpc_left.long_offset) / rpc_left.long_scale, dtype=cp.float64)
        v = cp.full(N, (initial[1] - rpc_left.lat_offset) / rpc_left.lat_scale, dtype=cp.float64)
        w = cp.full(N, (initial[2] - rpc_left.height_offset) / rpc_left.height_scale, dtype=cp.float64)

    active = cp.ones(N, dtype=cp.bool_)
    converged_mask = cp.zeros(N, dtype=cp.bool_)
    eye3 = cp.eye(3, dtype=cp.float64)

    for it in range(max_iter):
        n_active = int(cp.sum(active))
        if n_active == 0:
            break

        # Convert state to lon/lat/h
        lon = u * rpc_left.long_scale + rpc_left.long_offset
        lat = v * rpc_left.lat_scale + rpc_left.lat_offset
        h_geo = w * rpc_left.height_scale + rpc_left.height_offset

        # GPU projection + Jacobian (normalized by ref_rpc=rpc_left)
        line_l, samp_l, J_l = _project_with_jacobian_cupy(rpc_left, lon, lat, h_geo, cp)
        line_r, samp_r, J_r = _project_with_jacobian_cupy(rpc_right, lon, lat, h_geo, cp, ref_rpc=rpc_left)

        # Residuals on GPU (full N, set inactive to 0)
        res = cp.zeros((N, 4), dtype=cp.float64)
        mask_a = cp.nonzero(active)[0]
        res[mask_a, 0] = line_l[mask_a] - r_l[mask_a]
        res[mask_a, 1] = samp_l[mask_a] - s_l[mask_a]
        res[mask_a, 2] = line_r[mask_a] - r_r[mask_a]
        res[mask_a, 3] = samp_r[mask_a] - s_r[mask_a]
        r_active = res[mask_a]  # (n_active, 4)

        # Jacobian (n_active, 4, 3)
        J = cp.concatenate([J_l[mask_a], J_r[mask_a]], axis=1)

        # Normal equations on GPU
        JTJ = cp.einsum('nij,nik->njk', J, J)
        JTr = cp.einsum('nij,ni->nj', J, r_active)
        JTJ += eye3 * damping

        # Solve on GPU (JTr needs shape (N, 3, 1) for batched solve)
        try:
            dx = cp.linalg.solve(JTJ, JTr[:, :, cp.newaxis]).squeeze(axis=-1)
        except Exception as e:
            raise RuntimeError(
                f"GPU solve failed on chunk of size {n_active}: {e}"
            ) from e

        # Update active points
        u[mask_a] -= dx[:, 0]
        v[mask_a] -= dx[:, 1]
        w[mask_a] -= dx[:, 2]

        # Debug: first-iteration stats
        if it == 0:
            r_norm0 = float(cp.sqrt(cp.mean(r_active ** 2)))

        # Convergence check on GPU
        max_dx = cp.max(cp.abs(dx), axis=1)
        converged = max_dx < ftol
        bad = ~cp.isfinite(max_dx) | (max_dx > 1e3)

        bad_idx = mask_a[bad]
        if bad_idx.size > 0:
            u[bad_idx] = cp.nan; v[bad_idx] = cp.nan; w[bad_idx] = cp.nan
            active[bad_idx] = False

        conv_idx = mask_a[converged & ~bad]
        if conv_idx.size > 0:
            converged_mask[conv_idx] = True
            active[conv_idx] = False

        if not cp.any(active):
            break

    # Debug stats
    n_conv = int(cp.sum(converged_mask))
    n_bad = int(cp.sum(cp.isnan(u)))
    n_active_end = int(cp.sum(active))
    r_norm_final = float(cp.sqrt(cp.mean(r_active ** 2))) if n_active_end > 0 else 0.0
    if n_active_end > 0:
        r_norm_final = float(cp.sqrt(cp.mean(cp.asarray([
            cp.mean((line_l[active] - r_l[active])**2),
            cp.mean((samp_l[active] - s_l[active])**2),
            cp.mean((line_r[active] - r_r[active])**2),
            cp.mean((samp_r[active] - s_r[active])**2),
        ]))))

    print(f"  GPU: N={N}, converged={n_conv}, bad={n_bad}, "
          f"still_active={n_active_end}, "
          f"r_norm: {r_norm0:.2f} -> {r_norm_final:.2f}", flush=True)

    # Final: convert converged state to lon/lat/h
    lon_out = cp.full(N, cp.nan, dtype=cp.float64)
    lat_out = cp.full(N, cp.nan, dtype=cp.float64)
    h_out = cp.full(N, cp.nan, dtype=cp.float64)
    lon_out[converged_mask] = u[converged_mask] * rpc_left.long_scale + rpc_left.long_offset
    lat_out[converged_mask] = v[converged_mask] * rpc_left.lat_scale + rpc_left.lat_offset
    h_out[converged_mask] = w[converged_mask] * rpc_left.height_scale + rpc_left.height_offset

    return cp.asnumpy(lon_out), cp.asnumpy(lat_out), cp.asnumpy(h_out)


def intersect_many_batch(rpc_left: RPCModel, rpc_right: RPCModel,
                          line_left: np.ndarray, samp_left: np.ndarray,
                          line_right: np.ndarray, samp_right: np.ndarray,
                          initial: tuple[float, float, float] = None,
                          max_iter: int = 10, damping: float = 1e-3,
                          ftol: float = 1e-10) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Batch Gauss-Newton forward intersection for many points.

    Solves N independent 3×3 linear systems per iteration using analytic
    Jacobians from RPCModel.project_with_jacobian(). Much faster than
    calling scipy.optimize.least_squares per point.

    Args:
        rpc_left, rpc_right: RPC models.
        line_left, samp_left: Left image observations, shape (N,).
        line_right, samp_right: Right image observations, shape (N,).
        initial: Optional (lon, lat, h) initial guess for all points.
        max_iter: Max Gauss-Newton iterations.
        damping: Levenberg-Marquardt damping factor added to diagonal.
        ftol: Convergence threshold on max |dx| in normalized space.
    Returns:
        (lon, lat, height) arrays, shape (N,). Failed points are NaN.
    """
    r_l = np.asarray(line_left, dtype=np.float64).ravel()
    s_l = np.asarray(samp_left, dtype=np.float64).ravel()
    r_r = np.asarray(line_right, dtype=np.float64).ravel()
    s_r = np.asarray(samp_right, dtype=np.float64).ravel()
    N = len(r_l)

    # Initial guess in left-RPC normalized space
    if initial is None:
        lon0 = np.full(N, rpc_left.long_offset, dtype=np.float64)
        lat0 = np.full(N, rpc_left.lat_offset, dtype=np.float64)
        h0 = np.full(N, rpc_left.height_offset, dtype=np.float64)
    else:
        lon0 = np.full(N, initial[0], dtype=np.float64)
        lat0 = np.full(N, initial[1], dtype=np.float64)
        h0 = np.full(N, initial[2], dtype=np.float64)

    u = (lon0 - rpc_left.long_offset) / rpc_left.long_scale
    v = (lat0 - rpc_left.lat_offset) / rpc_left.lat_scale
    w = (h0 - rpc_left.height_offset) / rpc_left.height_scale

    active = np.ones(N, dtype=bool)
    converged_mask = np.zeros(N, dtype=bool)

    for it in range(max_iter):
        if not np.any(active):
            break

        # Convert normalized state to lon/lat/h (only for active points)
        lon = np.full(N, np.nan, dtype=np.float64)
        lat = np.full(N, np.nan, dtype=np.float64)
        h_geo = np.full(N, np.nan, dtype=np.float64)
        lon[active] = u[active] * rpc_left.long_scale + rpc_left.long_offset
        lat[active] = v[active] * rpc_left.lat_scale + rpc_left.lat_offset
        h_geo[active] = w[active] * rpc_left.height_scale + rpc_left.height_offset

        # Project with Jacobians (normalized by rpc_left)
        line_l, samp_l, J_l = rpc_left.project_with_jacobian(
            lon[active], lat[active], h_geo[active])
        line_r, samp_r, J_r = rpc_right.project_with_jacobian(
            lon[active], lat[active], h_geo[active], ref_rpc=rpc_left)

        # Residuals
        res_lr = np.zeros((N, 4), dtype=np.float64)
        res_lr[active, 0] = line_l - r_l[active]
        res_lr[active, 1] = samp_l - s_l[active]
        res_lr[active, 2] = line_r - r_r[active]
        res_lr[active, 3] = samp_r - s_r[active]
        r = res_lr[active]  # (n_active, 4)

        # Full Jacobian (n_active, 4, 3)
        J = np.concatenate([J_l, J_r], axis=1)

        # Normal equations: (J^T J + damping*I) * dx = J^T r
        JTJ = np.einsum('nij,nik->njk', J, J)  # (n_active, 3, 3)
        JTr = np.einsum('nij,ni->nj', J, r)     # (n_active, 3)

        # Add damping
        eye = np.eye(3, dtype=np.float64)
        JTJ[:, range(3), range(3)] += damping

        # Solve: batch (N, 3, 3) \ (N, 3, 1)
        JTr_expanded = JTr[:, :, np.newaxis]  # (n_active, 3, 1)
        try:
            dx = np.linalg.solve(JTJ, JTr_expanded).squeeze(axis=-1)
        except np.linalg.LinAlgError:
            dx = np.zeros((active.sum(), 3), dtype=np.float64)
            for j in range(active.sum()):
                try:
                    dx[j] = np.linalg.solve(JTJ[j], JTr[j])
                except np.linalg.LinAlgError:
                    dx[j] = np.nan

        # Update
        idx_active = np.where(active)[0]
        u[idx_active] -= dx[:, 0]
        v[idx_active] -= dx[:, 1]
        w[idx_active] -= dx[:, 2]

        # Check convergence and invalid points
        max_dx = np.max(np.abs(dx), axis=1)
        converged = max_dx < ftol
        bad_update = ~np.isfinite(max_dx) | (max_dx > 1e3)

        # Mark bad points as NaN and remove from active set
        bad_idx = idx_active[bad_update]
        if len(bad_idx) > 0:
            u[bad_idx] = np.nan
            v[bad_idx] = np.nan
            w[bad_idx] = np.nan
            active[bad_idx] = False

        # Remove converged points from active set, mark in converged_mask
        converged_idx = idx_active[converged & ~bad_update]
        if len(converged_idx) > 0:
            converged_mask[converged_idx] = True
            active[converged_idx] = False

        if not np.any(active):
            break

    # Convert to lon/lat/h — only converged points get finite output
    lon_out = np.full(N, np.nan, dtype=np.float64)
    lat_out = np.full(N, np.nan, dtype=np.float64)
    h_out = np.full(N, np.nan, dtype=np.float64)

    lon_out[converged_mask] = u[converged_mask] * rpc_left.long_scale + rpc_left.long_offset
    lat_out[converged_mask] = v[converged_mask] * rpc_left.lat_scale + rpc_left.lat_offset
    h_out[converged_mask] = w[converged_mask] * rpc_left.height_scale + rpc_left.height_offset

    return lon_out, lat_out, h_out
