"""LumiSteer deterministic physics engine.

All displayed numbers in the app come from these functions. Vectorized with
NumPy; a moderate sweep (e.g. 40x40 receiver grid) completes in milliseconds.

Model summary (documented in detail on the Methodology page):
  H_los(m) = (m+1) A_pd / (2 pi d^2) * cos^m(phi) * Ts * g(psi) * cos(psi), psi <= FOV else 0
  IRS element: Lambertian LED gain at element * reflectivity * element area
               * cos(incidence at element) * exp(-delta^2 / (2 sigma^2))
               * A_pd/d2^2 * cos(psi_rx), with blockage per segment.
  P_r = P_tx * (H_los + H_irs)
  sigma_noise^2 = 2 q R (P_r + P_amb) B  (shot) + 4 k T B / R_L  (thermal)
  SNR = (R P_r)^2 / sigma_noise^2 ; OOK BER = Q(sqrt(SNR)) = 0.5 erfc(sqrt(SNR/2))

This module is intentionally a swappable unit: a researcher can replace any
gain function with their own model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.special import erfc

from .schemas import SimConfig, SimResult, LinkStatus, Modulation

Q_ELECTRON = 1.602176634e-19
BOLTZMANN = 1.380649e-23


# ---------------------------------------------------------------- geometry ---

def lambert_m(half_angle_deg: float) -> float:
    """Lambertian order m = -ln 2 / ln cos(phi_half)."""
    c = math.cos(math.radians(half_angle_deg))
    if c <= 0 or c >= 1:
        raise ValueError("half_angle_deg must be in (0, 90)")
    return -math.log(2.0) / math.log(c)


def _unit(vec: np.ndarray) -> np.ndarray:
    vec = np.asarray(vec, dtype=float)
    n = np.linalg.norm(vec, axis=-1, keepdims=True)
    n = np.where(n < 1e-12, 1.0, n)
    return vec / n


def wall_normal(wall: str) -> np.ndarray:
    """Unit normal of a wall pointing into the room."""
    return {
        "north": np.array([0.0, 1.0, 0.0]),
        "south": np.array([0.0, -1.0, 0.0]),
        "east": np.array([-1.0, 0.0, 0.0]),
        "west": np.array([1.0, 0.0, 0.0]),
    }[wall]


def wall_axes(wall: str) -> tuple[np.ndarray, np.ndarray]:
    """Horizontal in-wall axis u and vertical in-wall axis v."""
    nrm = wall_normal(wall)
    v = np.array([0.0, 0.0, 1.0])
    u = np.cross(v, nrm)
    return u, v


def rotate(vec: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    """Rodrigues rotation of (unit) vector `vec` around `axis` by `angle` radians."""
    axis = _unit(np.asarray(axis, dtype=float))
    if abs(angle) < 1e-12:
        return np.asarray(vec, dtype=float).copy()
    c, s = math.cos(angle), math.sin(angle)
    dot = float(np.dot(axis, vec))
    return vec * c + np.cross(axis, vec) * s + axis * dot * (1.0 - c)


def element_geometry(cfg: SimConfig, azimuth_deg: np.ndarray, elevation_deg: np.ndarray):
    """Positions and normals of every IRS element, given per-element tilts.

    Azimuth rotates around the wall's vertical axis, elevation around the wall's
    horizontal axis; both relative to the wall normal pointing into the room.
    """
    nrm = wall_normal(cfg.irs.wall)
    u, v = wall_axes(cfg.irs.wall)
    az = np.deg2rad(np.asarray(azimuth_deg, dtype=float).ravel())
    el = np.deg2rad(np.asarray(elevation_deg, dtype=float).ravel())
    K = az.shape[0]

    def many(vec: np.ndarray) -> np.ndarray:
        return np.tile(vec, (K, 1))

    # n = R_v(az) R_u(el) n_base   (applied in that order)
    n = (many(nrm) * np.cos(el)[:, None]
         + np.cross(many(u), many(nrm)) * np.sin(el)[:, None]
         + many(u) * (np.einsum("ij,ij->i", many(u), many(nrm)) * (1 - np.cos(el)))[:, None])
    # note: u · nrm == 0 for perpendicular axes, kept for clarity
    n = (n * np.cos(az)[:, None]
         + np.cross(many(v), n) * np.sin(az)[:, None]
         + many(v) * (np.einsum("ij,ij->i", many(v), n) * (1 - np.cos(az)))[:, None])
    n = _unit(n)

    cx, cy, cz = cfg.irs.center.x, cfg.irs.center.y, cfg.irs.center.z
    if cfg.irs.wall in ("north",):
        cy = 0.05
    elif cfg.irs.wall in ("south",):
        cy = cfg.room.depth - 0.05
    elif cfg.irs.wall == "east":
        cx = cfg.room.width - 0.05
    else:
        cx = 0.05

    pitch = math.sqrt(cfg.irs.element_area_m2)  # square elements, square pitch
    rows, cols = cfg.irs.rows, cfg.irs.cols
    # grid extents centered on panel center: rows along u, cols along v
    u_off = (np.arange(int(rows)) - (rows - 1) / 2.0) * pitch
    v_off = (np.arange(int(cols)) - (cols - 1) / 2.0) * pitch
    uu, vv = np.meshgrid(u_off, v_off, indexing="ij")
    u_off = uu.ravel()[:K]
    v_off = vv.ravel()[:K]

    positions = (np.array([cx, cy, cz])[None, :]
                 + u_off[:, None] * u[None, :]
                 + v_off[:, None] * v[None, :])
    positions[:, 0] = np.clip(positions[:, 0], 0.01, cfg.room.width - 0.01)
    positions[:, 1] = np.clip(positions[:, 1], 0.01, cfg.room.depth - 0.01)
    positions[:, 2] = np.clip(positions[:, 2], 0.05, cfg.room.height - 0.05)
    return positions, n


# ---------------------------------------------------------------- blockage ---

def block_factors(cfg: SimConfig, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Per-segment power transmission through the obstacle.

    starts/ends: (M, 3) matching point pairs. Circle obstacle: the 3D closest
    approach point of each segment to the obstacle's XY center line must fall
    inside the XY radius and inside the obstacle's vertical extent.
    """
    att = cfg.obstacle.attenuation
    if not cfg.obstacle.enabled or att >= 1.0 - 1e-12:
        return np.ones(starts.shape[0])
    starts = np.atleast_2d(np.asarray(starts, dtype=float))
    ends = np.atleast_2d(np.asarray(ends, dtype=float))
    d = ends - starts
    den = d[:, 0] ** 2 + d[:, 1] ** 2
    c = cfg.obstacle.center
    rel = np.array([c.x, c.y]) - starts[:, :2]
    t = np.where(den[:, None] > 1e-12, (rel * d[:, :2]).sum(axis=1, keepdims=True) / den[:, None], 0.0)
    t = np.clip(t, 0.0, 1.0)
    xy_close = starts[:, :2] + t * d[:, :2]
    dz = np.array([c.x, c.y]) - xy_close
    dist2 = (dz ** 2).sum(axis=1)
    z_close = starts[:, 2] + t[:, 0] * d[:, 2]

    blocked = np.zeros(starts.shape[0], dtype=bool)
    z_lo, z_hi = cfg.obstacle.center.z, cfg.obstacle.center.z + cfg.obstacle.height_m
    r_eff = cfg.obstacle.radius_m
    if cfg.obstacle.shape == "circle":
        blocked = (dist2 <= r_eff ** 2) & (z_close >= z_lo) & (z_close <= z_hi)
    else:
        in_x = np.abs(dz[:, 0]) <= cfg.obstacle.box_semi_x
        in_y = np.abs(dz[:, 1]) <= cfg.obstacle.box_semi_y
        blocked = (in_x & in_y & (z_close >= z_lo) & (z_close <= z_hi))
    return np.where(blocked, att, 1.0)


# ------------------------------------------------------------------- gains ---

def los_gain(cfg: SimConfig, rx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Direct LOS channel gain to receiver(s). Returns (gain, block_factor)."""
    rx = np.atleast_2d(np.asarray(rx, dtype=float))
    led = np.array([cfg.led.position.x, cfg.led.position.y, cfg.led.position.z])
    d_vec = rx - led[None, :]
    d = np.linalg.norm(d_vec, axis=1)
    d = np.where(d < 1e-9, 1e-9, d)
    vhat = d_vec / d[:, None]
    led_normal = np.array([0.0, 0.0, -1.0])
    rx_normal = np.array([0.0, 0.0, 1.0])
    cos_phi = np.clip((vhat * led_normal[None, :]).sum(axis=1), 0.0, 1.0)  # vs downward LED normal
    cos_psi = np.clip(-((vhat) * rx_normal[None, :]).sum(axis=1), 0.0, 1.0)
    psi = np.rad2deg(np.arccos(np.clip(cos_psi, -1.0, 1.0)))
    fov_ok = psi <= cfg.receiver.photodiode.fov_deg

    m = lambert_m(cfg.led.half_angle_deg)
    A = cfg.receiver.photodiode.area_m2
    gain = (m + 1.0) * A / (2.0 * math.pi * d ** 2) * cos_phi ** m
    gain *= cfg.receiver.photodiode.filter_gain
    gain *= cos_psi  # cos(psi) term
    gain *= fov_ok
    gain = np.where(np.isnan(gain), 0.0, gain)
    block = block_factors(cfg, np.tile(led, (rx.shape[0], 1)), rx)
    return gain * block, block


def irradiance_at_element(cfg: SimConfig) -> dict:
    """Per-element LED-side Lambertian geometry (independent of RX)."""
    return {}


def irs_gain(cfg: SimConfig, azimuth_deg: np.ndarray, elevation_deg: np.ndarray,
             rx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sum of per-element reflected gains for receiver(s). Returns (gain, mean Transmission)."""
    if not cfg.irs.enabled:
        rx = np.atleast_2d(np.asarray(rx, dtype=float))
        return np.zeros(rx.shape[0]), np.ones(rx.shape[0])

    positions, normals = element_geometry(cfg, azimuth_deg, elevation_deg)
    led = np.array([cfg.led.position.x, cfg.led.position.y, cfg.led.position.z])
    K = positions.shape[0]

    d1_vec = positions - led[None, :]            # (K,3)
    d1 = np.linalg.norm(d1_vec, axis=1)
    d1 = np.where(d1 < 1e-9, 1e-9, d1)
    v1hat = d1_vec / d1[:, None]

    led_normal = np.array([0.0, 0.0, -1.0])
    cos_phi1 = np.clip((v1hat * led_normal[None, :]).sum(axis=1), 0.0, 1.0)  # vs downward LED normal
    cos_a1 = np.clip(-np.einsum("ij,ij->i", v1hat, normals), 0.0, 1.0)  # incidence on element

    m = lambert_m(cfg.led.half_angle_deg)
    A_el = cfg.irs.element_area_m2
    led_side = ((m + 1.0) / (2.0 * math.pi * d1 ** 2) * cos_phi1 ** m
                * cos_a1 * A_el * cfg.irs.reflectivity)  # (K,)

    # spec reflect direction
    dn = np.einsum("ij,ij->i", v1hat, normals)
    reflect_dir = v1hat - 2.0 * dn[:, None] * normals
    reflect_dir = _unit(reflect_dir)

    b1 = block_factors(cfg, np.tile(led, (K, 1)), positions)  # (K,)

    rx = np.atleast_2d(np.asarray(rx, dtype=float))
    N = rx.shape[0]
    seg2_end = rx[None, :, :]
    seg2_start = positions[:, None, :]  # (K,1,3) broadcast -> (K,N,3)
    b2 = block_factors(cfg, np.repeat(seg2_start, N, axis=1).reshape(-1, 3),
                       np.repeat(seg2_end, K, axis=0).reshape(-1, 3)).reshape(K, N)

    v2 = rx[None, :, :] - positions[:, None, :]      # (K,N,3)
    d2 = np.linalg.norm(v2, axis=2)
    d2 = np.where(d2 < 1e-9, 1e-9, d2)
    v2hat = v2 / d2[:, :, None]
    rx_normal = np.array([0.0, 0.0, 1.0])
    cos_psi2 = np.clip(-np.einsum("knj,j->kn", v2hat, rx_normal), 0.0, 1.0)
    psi2 = np.rad2deg(np.arccos(np.clip(cos_psi2, -1.0, 1.0)))
    fov_ok2 = psi2 <= cfg.receiver.photodiode.fov_deg

    cos_delta = np.clip(np.einsum("kij,kj->ki", v2hat, reflect_dir), -1.0, 1.0)  # (K,N)
    delta = np.arccos(cos_delta)
    sigma = np.deg2rad(cfg.irs.sigma_deg)
    align = np.exp(-(delta ** 2) / (2.0 * sigma ** 2))

    A_pd = cfg.receiver.photodiode.area_m2
    H = (led_side[:, None] * A_pd / d2 ** 2
         * cos_psi2 * fov_ok2 * align * cfg.receiver.photodiode.filter_gain)
    H = H * b1[:, None] * b2
    gain = H.sum(axis=0)  # (N,)
    mean_trans = None
    return gain, b2.mean(axis=0)


# ----------------------------------------------------------------- metrics ---

def noise_variance(cfg: SimConfig, p_rx: np.ndarray) -> np.ndarray:
    p_rx = np.asarray(p_rx, dtype=float)
    R = cfg.receiver.photodiode.responsivity
    B = cfg.noise.bandwidth_hz
    # p_ambient_w is specified as background optical power arriving at the
    # photodiode (W) - documented in the Methodology page.
    p_amb_eff = cfg.noise.ambient_power()
    shot = 2.0 * Q_ELECTRON * R * (p_rx + p_amb_eff) * B
    thermal = 4.0 * BOLTZMANN * cfg.noise.temperature_k * B / cfg.noise.load_resistance_ohm
    return shot + thermal


def ook_ber(snr: np.ndarray) -> np.ndarray:
    """OOK BER = Q(sqrt(SNR)) = 0.5 * erfc(sqrt(SNR / 2)) (exact formula used in the app).
    Values underflowing to 0 come back as 0 (the UI renders them as '< 1e-18')."""
    snr = np.asarray(snr, dtype=float)
    snr_safe = np.where(snr > 0, snr, 1e-300)
    return 0.5 * erfc(np.sqrt(snr_safe / 2.0))


BER_MIN_LOG = -18.0


def log10_ber(ber, floor: float = 10 ** BER_MIN_LOG) -> float:
    """Numerically safe log10(BER) for objective functions. ber can be None/0."""
    if ber is None:
        return BER_MIN_LOG
    b = float(ber)
    if b <= 0 or not math.isfinite(b):
        return BER_MIN_LOG
    return max(math.log10(b), BER_MIN_LOG)


def link_status(cfg: SimConfig, ber: float | None) -> str:
    if ber is None or ber <= cfg.modulation.ber_threshold:
        return LinkStatus.STABLE
    if ber > 0.1 or math.isclose(ber, 0.5, abs_tol=0.02):
        return LinkStatus.OUTAGE
    return LinkStatus.DEGRADED


def illuminance_lux(cfg: SimConfig, point_xy: tuple[float, float] | None = None,
                    height: float | None = None) -> float:
    """Illuminance (lux) at the work plane from the direct LED beam only.

    point_xy: XY position to evaluate; defaults to the receiver XY.
    height: work-plane height; defaults to the receiver Z.
    """
    if point_xy is None:
        point_xy = (cfg.receiver.position.x, cfg.receiver.position.y)
    if height is None:
        height = cfg.receiver.position.z
    led = np.array([cfg.led.position.x, cfg.led.position.y, cfg.led.position.z])
    p = np.array([point_xy[0], point_xy[1], height])
    d2 = float(((p - led) ** 2).sum())
    if d2 < 1e-9:
        return 0.0
    vhat = (p - led) / math.sqrt(d2)
    cos_theta = max(0.0, -float(vhat[2]))  # LED emits down: cosine vs its normal
    # incidence on the horizontal work plane (normal up): |(vhat)_z|
    cos_work = min(1.0, abs(float(vhat[2])))
    if cos_theta <= 0 or cos_work <= 1e-9:
        return 0.0
    m = lambert_m(cfg.led.half_angle_deg)
    lum = cfg.led.power_w * cfg.illumination.luminous_efficacy
    return float(lum * (m + 1.0) / (2.0 * math.pi * d2) * (cos_theta ** m) * cos_work)


# ---------------------------------------------------------------- simulate ---

def evaluate(cfg: SimConfig, azimuth_deg, elevation_deg, rx_pos) -> dict:
    """Core single-point evaluation used by /api/simulate and optimizers.

    Returns raw float metrics (not a Pydantic model) for speed.
    """
    rx = np.atleast_2d(np.asarray(rx_pos, dtype=float))
    g_los, b_los = los_gain(cfg, rx)
    if cfg.irs.enabled:
        g_irs_arr, _ = irs_gain(cfg, np.asarray(azimuth_deg).ravel(),
                                np.asarray(elevation_deg).ravel(), rx)
    else:
        g_irs_arr = np.zeros(rx.shape[0])
    total = g_los + g_irs_arr
    p_r = cfg.led.power_w * total
    var = noise_variance(cfg, p_r)
    R_pd = cfg.receiver.photodiode.responsivity
    var = np.where(var <= 0, 1e-300, var)
    sig2 = var[0]
    snr = (R_pd * p_r[0]) ** 2 / sig2
    ber = 0.5 * math.erfc(math.sqrt(snr / 2.0))
    E = float(p_r[0] / cfg.receiver.photodiode.area_m2)
    lux_led = illuminance_lux(cfg)
    # Comfort illuminance includes the ambient background lighting of the room
    # (ambient background irradiance at the photodiode plane scaled by the same
    # luminous efficacy). With only a single 1 W VLC LED the direct contribution
    # alone cannot reach typical 300 lux room-lighting levels.
    ambient_lux = (cfg.noise.ambient_power() / cfg.receiver.photodiode.area_m2
                   * cfg.illumination.luminous_efficacy)
    lux = lux_led + ambient_lux
    return {
        "received_power_w": float(p_r[0]),
        "irradiance_w_m2": E,
        "illuminance_lux": lux,
        "illuminance_led_lux": lux_led,
        "illuminance_ok": lux >= cfg.illumination.min_lux * 0.999,
        "snr": float(snr),
        "snr_db": float(10 * math.log10(max(snr, 1e-30))),
        "ber": None if ber <= 0 else float(ber),
        "g_los": float(g_los[0]),
        "g_irs": float(g_irs_arr[0]),
        "total_gain": float(total[0]),
        "p_led_w": float(cfg.led.power_w),
        "los_block_factor": float(b_los[0]),
        "irs_block_factor": 1.0,
        "noise_std": float(math.sqrt(max(sig2, 1e-300))),
        "link_status": link_status(cfg, None if ber <= 0 else float(ber)),
    }


def sweep(cfg: SimConfig, azimuth_deg, elevation_deg, resolution: int = 40) -> dict:
    """BER / power / irradiance over an XY grid of receiver positions at the
    receiver's current height. Fully vectorized."""
    res = max(2, min(int(resolution), 120))
    xs = np.linspace(0.05, cfg.room.width - 0.05, res)
    ys = np.linspace(0.05, cfg.room.depth - 0.05, res)
    gx, gy = np.meshgrid(xs, ys, indexing="xy")  # gy varies fastest
    z = cfg.receiver.position.z
    rx = np.stack([gx.ravel(), gy.ravel(), np.full(gx.size, z)], axis=1)

    g_los, _ = los_gain(cfg, rx)
    if cfg.irs.enabled:
        g_irs, _ = irs_gain(cfg, np.asarray(azimuth_deg).ravel(),
                            np.asarray(elevation_deg).ravel(), rx)
    else:
        g_irs = np.zeros(rx.shape[0])
    total = g_los + g_irs
    p_r = cfg.led.power_w * total
    var = noise_variance(cfg, p_r)
    R_pd = cfg.receiver.photodiode.responsivity
    snr = (R_pd * p_r) ** 2 / np.maximum(var, 1e-300)
    ber = 0.5 * erfc(np.sqrt(np.maximum(snr, 1e-300) / 2.0))

    ber_grid = ber.reshape(res, res)
    pow_grid = p_r.reshape(res, res)
    E_grid = (p_r / cfg.receiver.photodiode.area_m2).reshape(res, res)
    outage = (ber_grid > cfg.modulation.ber_threshold)
    n_out = int(outage.sum())
    finite = ber_grid[ber_grid > 0]
    return {
        "resolution": res,
        "x": xs.tolist(),
        "y": ys.tolist(),
        "ber": [[None if v <= 0 else float(v) for v in row] for row in ber_grid],
        "received_power_w": pow_grid.tolist(),
        "irradiance_w_m2": E_grid.tolist(),
        "outage_probability": n_out / ber_grid.size,
        "mean_ber": float(finite.mean()) if finite.size else None,
        "worst_ber": float(max(ber_grid.max(), 0.0)) or None,
        "mean_power_w": float(p_r.mean()),
        "mean_irradiance_w_m2": float(E_grid.mean()),
        "outage_positions": n_out,
    }


def simulate_model(cfg: SimConfig, angles, rx_pos) -> SimResult:
    """Pydantic-shaped version of evaluate() for the API layer."""
    n = cfg.irs.n_elements if cfg.irs.enabled else 0
    if angles is None:
        angles = {"azimuth_deg": [0.0] * n, "elevation_deg": [0.0] * n}
    res = evaluate(cfg, angles.get("azimuth_deg", [0.0] * n) if isinstance(angles, dict) else angles.azimuth_deg,
                   angles.get("elevation_deg", [0.0] * n) if isinstance(angles, dict) else angles.elevation_deg,
                   rx_pos)
    return SimResult(**res)
