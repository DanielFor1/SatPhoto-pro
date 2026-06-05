"""RPC (Rational Polynomial Camera) model for satellite image projection.

Parses .rpb files and implements ground-to-image projection:
    (lon, lat, height) -> (line, sample)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# RPC00B / GDAL term order for 20-coefficient cubic polynomials.
# Powers of (u, v, w) where u=lon_norm, v=lat_norm, w=h_norm.
RPC_TERMS = [
    (0, 0, 0),  # 1
    (1, 0, 0),  # U
    (0, 1, 0),  # V
    (0, 0, 1),  # W
    (1, 1, 0),  # U*V
    (1, 0, 1),  # U*W
    (0, 1, 1),  # V*W
    (2, 0, 0),  # U^2
    (0, 2, 0),  # V^2
    (0, 0, 2),  # W^2
    (1, 1, 1),  # U*V*W
    (3, 0, 0),  # U^3
    (1, 2, 0),  # U*V^2
    (1, 0, 2),  # U*W^2
    (2, 1, 0),  # U^2*V
    (0, 3, 0),  # V^3
    (0, 1, 2),  # V*W^2
    (2, 0, 1),  # U^2*W
    (0, 2, 1),  # V^2*W
    (0, 0, 3),  # W^3
]


@dataclass
class RPCModel:
    """A single RPC camera model loaded from a .rpb file."""

    line_offset: float = 0.0
    samp_offset: float = 0.0
    lat_offset: float = 0.0
    long_offset: float = 0.0
    height_offset: float = 0.0
    line_scale: float = 1.0
    samp_scale: float = 1.0
    lat_scale: float = 1.0
    long_scale: float = 1.0
    height_scale: float = 1.0
    line_num_coef: np.ndarray = field(default_factory=lambda: np.zeros(20))
    line_den_coef: np.ndarray = field(default_factory=lambda: np.zeros(20))
    samp_num_coef: np.ndarray = field(default_factory=lambda: np.zeros(20))
    samp_den_coef: np.ndarray = field(default_factory=lambda: np.zeros(20))

    @classmethod
    def from_rpb(cls, filepath: str) -> "RPCModel":
        """Parse an RPB file and return an RPCModel."""
        path = Path(filepath)
        suffix = path.suffix.lower()
        if suffix in {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp"}:
            raise ValueError(
                f"所选文件是影像 ({suffix})，不是 RPC。\n"
                f"请在「左 RPC / 右 RPC」中选择 .rpb 文件，例如：\n"
                f"  实习数据\\task5\\影像\\JAX_Tile_163_RGB_005_EPI.rpb"
            )
        if suffix and suffix != ".rpb":
            raise ValueError(f"RPC 文件应为 .rpb，当前为: {filepath}")

        raw = path.read_bytes()
        text = None
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError(f"无法读取 RPC 文本: {filepath}")

        def _extract(name: str) -> float:
            pattern = name + r"\s*=\s*([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)"
            m = re.search(pattern, text)
            if not m:
                raise ValueError(f"Could not find {name} in RPB file")
            return float(m.group(1))

        def _extract_array(name: str) -> np.ndarray:
            pattern = name + r"\s*=\s*\(\s*\n?(.*?)\);"
            m = re.search(pattern, text, re.DOTALL)
            if not m:
                raise ValueError(f"Could not find {name} in RPB file")
            values = []
            for line in m.group(1).strip().splitlines():
                line = line.strip().rstrip(",")
                if line:
                    values.append(float(line))
            return np.array(values, dtype=np.float64)

        return cls(
            line_offset=_extract("lineOffset"),
            samp_offset=_extract("sampOffset"),
            lat_offset=_extract("latOffset"),
            long_offset=_extract("longOffset"),
            height_offset=_extract("heightOffset"),
            line_scale=_extract("lineScale"),
            samp_scale=_extract("sampScale"),
            lat_scale=_extract("latScale"),
            long_scale=_extract("longScale"),
            height_scale=_extract("heightScale"),
            line_num_coef=_extract_array("lineNumCoef"),
            line_den_coef=_extract_array("lineDenCoef"),
            samp_num_coef=_extract_array("sampNumCoef"),
            samp_den_coef=_extract_array("sampDenCoef"),
        )

    def _eval_poly(self, u: np.ndarray, v: np.ndarray, w: np.ndarray,
                   coef: np.ndarray) -> np.ndarray:
        """Evaluate the cubic polynomial with given coefficients at (u,v,w)."""
        result = np.zeros_like(u, dtype=np.float64)
        for k, (pu, pv, pw) in enumerate(RPC_TERMS):
            term = (u ** pu) * (v ** pv) * (w ** pw) * coef[k]
            result += term
        return result

    def _normalize(self, lon: np.ndarray, lat: np.ndarray,
                   height: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Normalize geographic coordinates to [-1, 1] range."""
        u = (lon - self.long_offset) / self.long_scale
        v = (lat - self.lat_offset) / self.lat_scale
        w = (height - self.height_offset) / self.height_scale
        return u, v, w

    def project(self, lon: np.ndarray, lat: np.ndarray,
                height: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Project ground point (lon, lat, height) to image (line, sample).

        Args:
            lon: Longitude (degrees).
            lat: Latitude (degrees).
            height: Ellipsoid height (meters).
        Returns:
            (line, sample) pixel coordinates.
        """
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        height = np.asarray(height, dtype=np.float64)

        u, v, w = self._normalize(lon, lat, height)

        line_num = self._eval_poly(u, v, w, self.line_num_coef)
        line_den = self._eval_poly(u, v, w, self.line_den_coef)
        line_norm = line_num / line_den
        line = line_norm * self.line_scale + self.line_offset

        samp_num = self._eval_poly(u, v, w, self.samp_num_coef)
        samp_den = self._eval_poly(u, v, w, self.samp_den_coef)
        samp_norm = samp_num / samp_den
        samp = samp_norm * self.samp_scale + self.samp_offset

        return line, samp

    def project_with_jacobian(self, lon: np.ndarray, lat: np.ndarray,
                               height: np.ndarray,
                               ref_rpc: "RPCModel" = None
                               ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Project ground points to image coordinates with analytic Jacobian.

        Args:
            lon, lat, height: Ground coordinates, shape (N,).
            ref_rpc: Reference RPC for Jacobian normalization. If None,
                     uses self as reference.
        Returns:
            line, sample: shape (N,).
            J: Jacobian shape (N, 2, 3), columns = d/d(u_ref, v_ref, w_ref).
        """
        lon = np.asarray(lon, dtype=np.float64).ravel()
        lat = np.asarray(lat, dtype=np.float64).ravel()
        height = np.asarray(height, dtype=np.float64).ravel()
        N = len(lon)

        if ref_rpc is None:
            ref_rpc = self

        # Normalize by self's offsets/scales
        u, v, w = self._normalize(lon, lat, height)

        # Precompute powers for all terms
        # u_pow[i,k] = u[i] ** pu_k
        u_pow = np.zeros((N, 20), dtype=np.float64)
        v_pow = np.zeros((N, 20), dtype=np.float64)
        w_pow = np.zeros((N, 20), dtype=np.float64)
        for k, (pu, pv, pw) in enumerate(RPC_TERMS):
            if pu > 0:
                u_pow[:, k] = u ** pu
            else:
                u_pow[:, k] = 1.0
            if pv > 0:
                v_pow[:, k] = v ** pv
            else:
                v_pow[:, k] = 1.0
            if pw > 0:
                w_pow[:, k] = w ** pw
            else:
                w_pow[:, k] = 1.0

        term_vals = u_pow * v_pow * w_pow  # (N, 20)

        # Evaluate line
        line_num = term_vals @ self.line_num_coef
        line_den = term_vals @ self.line_den_coef
        line_norm = line_num / line_den
        line = line_norm * self.line_scale + self.line_offset

        # Evaluate samp
        samp_num = term_vals @ self.samp_num_coef
        samp_den = term_vals @ self.samp_den_coef
        samp_norm = samp_num / samp_den
        samp = samp_norm * self.samp_scale + self.samp_offset

        # Derivatives
        du_pow = np.zeros((N, 20), dtype=np.float64)
        dv_pow = np.zeros((N, 20), dtype=np.float64)
        dw_pow = np.zeros((N, 20), dtype=np.float64)
        for k, (pu, pv, pw) in enumerate(RPC_TERMS):
            if pu > 0:
                du_pow[:, k] = pu * (u ** (pu - 1)) * v_pow[:, k] * w_pow[:, k]
            if pv > 0:
                dv_pow[:, k] = pv * (v ** (pv - 1)) * u_pow[:, k] * w_pow[:, k]
            if pw > 0:
                dw_pow[:, k] = pw * (w ** (pw - 1)) * u_pow[:, k] * v_pow[:, k]

        # d(line_norm)/d(u,v,w)
        dln_u = (du_pow @ self.line_num_coef * line_den -
                 line_num * (du_pow @ self.line_den_coef)) / (line_den ** 2)
        dln_v = (dv_pow @ self.line_num_coef * line_den -
                 line_num * (dv_pow @ self.line_den_coef)) / (line_den ** 2)
        dln_w = (dw_pow @ self.line_num_coef * line_den -
                 line_num * (dw_pow @ self.line_den_coef)) / (line_den ** 2)

        # d(samp_norm)/d(u,v,w)
        dsn_u = (du_pow @ self.samp_num_coef * samp_den -
                 samp_num * (du_pow @ self.samp_den_coef)) / (samp_den ** 2)
        dsn_v = (dv_pow @ self.samp_num_coef * samp_den -
                 samp_num * (dv_pow @ self.samp_den_coef)) / (samp_den ** 2)
        dsn_w = (dw_pow @ self.samp_num_coef * samp_den -
                 samp_num * (dw_pow @ self.samp_den_coef)) / (samp_den ** 2)

        # Scale to pixel units: d(line)/d(u) = d(line_norm)/d(u) * line_scale
        J_self = np.zeros((N, 2, 3), dtype=np.float64)
        J_self[:, 0, 0] = dln_u * self.line_scale
        J_self[:, 0, 1] = dln_v * self.line_scale
        J_self[:, 0, 2] = dln_w * self.line_scale
        J_self[:, 1, 0] = dsn_u * self.samp_scale
        J_self[:, 1, 1] = dsn_v * self.samp_scale
        J_self[:, 1, 2] = dsn_w * self.samp_scale

        # Chain rule: d/d(u_ref) = d/d(u_self) * d(u_self)/d(u_ref)
        # d(u_self)/d(u_ref) = ref_rpc.long_scale / self.long_scale
        if ref_rpc is not self:
            scale_u = ref_rpc.long_scale / self.long_scale
            scale_v = ref_rpc.lat_scale / self.lat_scale
            scale_w = ref_rpc.height_scale / self.height_scale
            J_self[:, :, 0] *= scale_u
            J_self[:, :, 1] *= scale_v
            J_self[:, :, 2] *= scale_w

        return line, samp, J_self
