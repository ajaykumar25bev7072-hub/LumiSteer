"""Optimization tools (classical, deterministic - never the LLM).

- optimize_irs: point-optimized IRS tilts at a receiver position.
- robust_optimize: average + worst-case optimization over sampled receiver
  positions within a radius and small TX tilt jitter.
- baseline_configs: no-IRS, random-IRS, fixed-point-optimized baselines.
"""
from __future__ import annotations

import math
import numpy as np
from scipy.optimize import minimize

from . import physics
from .schemas import SimConfig, SimResult, IRSAngles
from scipy.special import erfc as _erfc

POWER_REF_W = 1e-5      # 10 microwatts - typical unblocked P_r scales
IRRA_REF_W_M2 = 0.1     # = POWER_REF / 1 cm^2


# --------------------------------------------------------------- internals ---

def metric_score(ber: float | None, power: float, irradiance: float,
                 weights: dict) -> float:
    """Scalar quality score of one configuration sample (higher is better).

    weights keys: power, irradiance, ber (all >= 0, sum may be anything).
    Uses log10(BER) so improvements at low BER still count.
    """
    w_p = weights.get("power", 1.0)
    w_i = weights.get("irradiance", 0.5)
    w_b = weights.get("ber", 2.0)
    norm_power = power / POWER_REF_W
    norm_irr = irradiance / IRRA_REF_W_M2
    return float(w_p * norm_power + w_i * norm_irr
                 - w_b * (physics.log10_ber(ber) - physics.BER_MIN_LOG))


def _sample_positions(center, radius: float, n: int, rng: np.random.Generator) -> np.ndarray:
    r = radius * np.sqrt(rng.random(n))
    theta = 2.0 * math.pi * rng.random(n)
    pts = np.asarray(center, dtype=float)[None, :].repeat(n, axis=0)
    pts[:, 0] += r * np.cos(theta)
    pts[:, 1] += r * np.sin(theta)
    return pts


def _evaluate_samples(cfg: SimConfig, az_rad: np.ndarray, el_rad: np.ndarray,
                      rx: np.ndarray) -> dict:
    """Vectorized batch evaluation of several receiver positions at fixed IRS."""
    g_los, _ = physics.los_gain(cfg, rx)
    g_irs, _ = physics.irs_gain(cfg, np.rad2deg(az_rad), np.rad2deg(el_rad), rx)
    total = g_los + g_irs
    p_r = cfg.led.power_w * total
    var = physics.noise_variance(cfg, p_r)
    R_pd = cfg.receiver.photodiode.responsivity
    snr = (R_pd * p_r) ** 2 / np.maximum(var, 1e-300)
    snr_safe = np.maximum(snr, 1e-300)
    ber = 0.5 * _erfc(np.sqrt(snr_safe / 2.0))
    irr = p_r / cfg.receiver.photodiode.area_m2
    return {"p_r": p_r, "irr": irr, "snr": snr, "ber": ber,
            "g_los": g_los, "g_irs": g_irs}


def _aggregate_score(cfg: SimConfig, samples: dict, weights: dict,
                     worst_weight: float = 0.3) -> float:
    """Robust objective: (1-beta) mean over samples + beta * worst-case sample."""
    per = metric_score_vec(cfg, samples, weights)
    wers = per.min()
    return float((1.0 - worst_weight) * per.mean() + worst_weight * wers)


def metric_score_vec(cfg: SimConfig, samples: dict, weights: dict) -> np.ndarray:
    ber = samples["ber"].copy()
    with np.errstate(divide="ignore", invalid="ignore"):
        log_ber = np.where(ber > 0, np.log10(np.where(ber > 0, ber, 1.0)), physics.BER_MIN_LOG)
    log_ber = np.clip(log_ber, physics.BER_MIN_LOG, 0.0)
    w_p = weights.get("power", 1.0)
    w_i = weights.get("irradiance", 0.5)
    w_b = weights.get("ber", 2.0)
    return (w_p * samples["p_r"] / POWER_REF_W
            + w_i * samples["irr"] / IRRA_REF_W_M2
            - w_b * (log_ber - physics.BER_MIN_LOG))


# -------------------------------------------------------------- optimize ---

def _unpack(vec: np.ndarray, n: int, cfg: SimConfig):
    az = vec[:n]
    el = vec[n:2 * n]
    return az, el


def _build_objective(cfg: SimConfig, positions: np.ndarray, weights: dict,
                     worst_weight: float):
    n = cfg.irs.n_elements
    az_lo, az_hi = cfg.irs.azimuth_range_deg
    el_lo, el_hi = cfg.irs.elevation_range_deg

    def obj(vec: np.ndarray) -> float:
        az = np.deg2rad(vec[:n])
        el = np.deg2rad(vec[n:2 * n])
        samples = _evaluate_samples(cfg, az, el, positions)
        s = -_aggregate_score(cfg, samples, weights, worst_weight)
        # illuminance comfort constraint: strong penalty when violated
        lux = physics.illuminance_lux(cfg)
        if lux < cfg.illumination.min_lux:
            s += 50.0 * (cfg.illumination.min_lux - lux) / cfg.illumination.min_lux + 10.0
        if lux > cfg.illumination.max_lux:
            s += 20.0
        return float(s)

    return obj


def optimize_irs(cfg: SimConfig, rx_position=None, objective_weights: dict | None = None,
                 include_power: bool = True, n_restarts: int = 3, seed: int = 17) -> dict:
    """Point optimization of IRS tilts (and optionally LED power) at one position.

    Uses scipy.optimize L-BFGS-B with deterministic seeded multi-start.
    Returns angles (deg) and resulting metrics. Note: illuminance depends on
    LED power, so when include_power is on, the optimizer raises power until it
    hits either max power or the max-illuminance comfort cap.
    """
    weights = objective_weights or {"power": 1.0, "irradiance": 0.5, "ber": 2.0}
    pos = np.asarray(rx_position[0:3] if rx_position else
                     [cfg.receiver.position.x, cfg.receiver.position.y, cfg.receiver.position.z],
                     dtype=float).reshape(1, 3)
    rng = np.random.default_rng(seed)
    obj = _build_objective(cfg, pos, weights, worst_weight=0.30)

    best_vec, best_val = None, math.inf
    n = cfg.irs.n_elements
    az_lo, az_hi = cfg.irs.azimuth_range_deg
    el_lo, el_hi = cfg.irs.elevation_range_deg
    bounds = [(az_lo, az_hi)] * n + [(el_lo, el_hi)] * n

    starts = [np.concatenate([np.zeros(n), np.zeros(n)])]
    for i in range(1, max(1, n_restarts)):
        starts.append(np.concatenate([rng.uniform(az_lo, az_hi, n), rng.uniform(el_lo, el_hi, n)]))

    power_candidates = _power_candidates(cfg) if include_power else [cfg.led.power_w]
    for pow_w in power_candidates:
        cfg_pow = cfg.model_copy(deep=True)
        cfg_pow.led.power_w = pow_w
        obj_p = _build_objective(cfg_pow, pos, weights, worst_weight=0.30)
        for s0 in starts:
            r = minimize(obj_p, s0, method="L-BFGS-B", bounds=bounds,
                         options={"maxiter": 250})
            if r.fun < best_val:
                best_val, best_vec = float(r.fun), r.x.copy()
        if len(power_candidates) > 1:
            # keep only the best power given symmetrical structure: choose by metric
            pass

    az = np.deg2rad(best_vec[:n])
    el = np.deg2rad(best_vec[n:2 * n])

    # if power optimization is on, pick the power whose result is best within constraints
    if include_power:
        best_pow = _pick_power(cfg, az, el, pos)
        cfg_new = cfg.model_copy(deep=True)
        cfg_new.led.power_w = best_pow
        cfg, led_changed = cfg_new, True
    else:
        led_changed = False

    samples = _evaluate_samples(cfg, az, el, pos)
    metrics = _point_result(cfg, az_rad=az, el_rad=el, rx=pos[0],
                            samples={k: v[0:1] for k, v in samples.items()})
    metrics["optimized_power_w"] = cfg.led.power_w
    metrics["power_optimized"] = led_changed
    angles = _angles_from(cfg, az, el)
    return {"angles": angles, "metrics": metrics,
            "objective": {"weights": weights}}


def _angles_from(cfg: SimConfig, az_rad, el_rad) -> IRSAngles:
    return IRSAngles(azimuth_deg=np.rad2deg(az_rad).tolist(),
                     elevation_deg=np.rad2deg(el_rad).tolist())


def _power_candidates(cfg: SimConfig) -> list[float]:
    max_w = cfg.led.max_power_w
    min_w = max(cfg.led.dim_min_fraction * max_w, 1e-3)
    return sorted({min_w, 0.3 * max_w, 0.6 * max_w, max_w})


def _pick_power(cfg: SimConfig, az, el, pos) -> float:
    """Choose LED power maximizing quality while honoring illuminance constraints.

    The optimizer may raise power up to the cap implied by max_lux, never below
    the dim floor.
    """
    max_w = cfg.led.max_power_w
    min_w = max(cfg.led.dim_min_fraction * max_w, 1e-3)
    # lux is linear in power: cap power so lux stays <= max_lux
    probe = cfg.model_copy(deep=True)
    probe.led.power_w = min_w
    ref_lux = physics.illuminance_lux(probe)
    cap = 1.0
    if ref_lux > 0 and cfg.illumination.max_lux > 0:
        cap = cfg.illumination.max_lux / ref_lux
    p_hi = min(max_w, min_w * cap)
    if p_hi <= min_w:
        return min_w
    weights = {"power": 1.0, "irradiance": 0.5, "ber": 2.0}
    best_p, best_score = None, -math.inf
    for p in np.linspace(min_w, p_hi, 7):
        c = cfg.model_copy(deep=True)
        c.led.power_w = float(p)
        s = _evaluate_samples(c, az, el, pos)
        score = _aggregate_score(c, s, weights, worst_weight=0.3)
        if score > best_score:
            best_score, best_p = score, float(p)
    return best_p


def _point_result(cfg: SimConfig, az_rad, el_rad, rx, samples: dict) -> dict:
    p_r, irr = float(samples["p_r"][0]), float(samples["irr"][0])
    snr = float(samples["snr"][0])
    ber = float(samples["ber"][0])
    lux_led = physics.illuminance_lux(cfg)
    ambient_lux = (cfg.noise.ambient_power() / cfg.receiver.photodiode.area_m2
                   * cfg.illumination.luminous_efficacy)
    return {
        "received_power_w": p_r,
        "irradiance_w_m2": irr,
        "illuminance_lux": lux_led + ambient_lux,
        "illuminance_led_lux": lux_led,
        "illuminance_ok": (lux_led + ambient_lux) >= cfg.illumination.min_lux * 0.999,
        "snr": snr,
        "snr_db": 10 * math.log10(max(snr, 1e-30)),
        "ber": None if ber <= 0 else ber,
        "g_los": float(samples["g_los"][0]),
        "g_irs": float(samples["g_irs"][0]),
        "total_gain": float(samples["g_los"][0] + samples["g_irs"][0]),
        "p_led_w": float(cfg.led.power_w),
        "los_block_factor": 1.0,
        "irs_block_factor": 1.0,
        "noise_std": math.sqrt(max(float(physics.noise_variance(cfg, np.array([samples["p_r"][0]]))[0]), 1e-300)),
        "link_status": physics.link_status(cfg, None if ber <= 0 else ber),
    }


# --------------------------------------------------------------- robust ----

def robust_optimize(cfg: SimConfig, rx_position=None, radius_m: float = 0.15,
                    n_samples: int = 12, objective_weights: dict | None = None,
                    tx_jitter_deg: float = 2.0, seed: int = 21,
                    n_restarts: int = 4) -> dict:
    """Worst-case + average optimization over receiver positions in a disk of
    `radius_m` around the nominal point (plus small TX tilt jitter).
    Returns angles, mean BER and worst-case BER over the sampled positions."""
    weights = objective_weights or {"power": 1.0, "irradiance": 0.5, "ber": 2.0}
    rng = np.random.default_rng(seed)
    center_list = ([float(v) for v in rx_position[0:3]] if rx_position is not None
                   else [cfg.receiver.position.x, cfg.receiver.position.y, cfg.receiver.position.z])
    center = np.array(center_list)
    # nominal position first, then the disk around it
    positions = np.vstack([
        center[None, :],
        _sample_positions(center, radius_m, max(1, n_samples - 1), rng),
    ])
    jitter = np.deg2rad(tx_jitter_deg)
    obj = _build_objective(cfg, positions, weights, worst_weight=0.35)

    n = cfg.irs.n_elements
    az_lo, az_hi = cfg.irs.azimuth_range_deg
    el_lo, el_hi = cfg.irs.elevation_range_deg
    bounds = [(az_lo, az_hi)] * n + [(el_lo, el_hi)] * n

    best_vec, best_val = None, math.inf
    starts = [np.concatenate([np.zeros(n), np.zeros(n)])]
    for i in range(max(1, n_restarts)):
        starts.append(np.concatenate([rng.uniform(az_lo, az_hi, n), rng.uniform(el_lo, el_hi, n)]))
    for s0 in starts:
        r = minimize(obj, s0, method="L-BFGS-B", bounds=bounds, options={"maxiter": 250})
        if r.fun < best_val:
            best_val, best_vec = float(r.fun), r.x.copy()
    az, el = np.deg2rad(best_vec[:n]), np.deg2rad(best_vec[n:2 * n])

    if tx_jitter_deg > 0:
        # Extend the sample set with TX tilt jitter: jitter cannot rotate the
        # fixed downward LED, so model it at geometry level by adding a small
        # positional-equivalent perturbation to the RX sample set.
        s = _evaluate_samples(cfg, az, el, positions)
        all_p, all_i, all_b = s["p_r"], s["irr"], s["ber"]
        extra = _sample_positions(center, radius_m * 0.4, 8, rng)
        s2 = _evaluate_samples(cfg, az, el, extra)
        all_p = np.concatenate([all_p, s2["p_r"]])
        all_i = np.concatenate([all_i, s2["irr"]])
        all_b = np.concatenate([all_b, s2["ber"]])
    else:
        s = _evaluate_samples(cfg, az, el, positions)
        all_p, all_i, all_b, all_los = s["p_r"], s["irr"], s["ber"], s["g_los"]

    ber = all_b[all_b > 0]
    angles = _angles_from(cfg, az, el)
    nominal = _evaluate_samples(cfg, az, el, center[None, :])
    nominal_split = {k: v[0:1] for k, v in nominal.items()}
    result = _point_result(cfg, az, el, center, nominal_split)
    return {
        "angles": angles,
        "metrics": result,
        "radius_m": radius_m,
        "n_samples": len(positions),
        "mean_ber": float(ber.mean()) if ber.size else None,
        "worst_ber": float(max(ber.max(), ber.min())) if ber.size else None,
        "mean_power_w": float(all_p.mean()),
        "worst_power_w": float(all_p.min()),
        "mean_irradiance_w_m2": float(all_i.mean()),
    }


# -------------------------------------------------------------- baselines --

def baseline_configs(cfg: SimConfig, seed: int = 7) -> dict:
    """Return the four comparison strategies for the same config:
    A: no IRS; B: random IRS; C: fixed-point optimized IRS; D: robust-optimized IRS.
    Angles default to zeros where unused."""
    n = cfg.irs.n_elements
    rng = np.random.default_rng(seed)
    az_lo, az_hi = cfg.irs.azimuth_range_deg
    el_lo, el_hi = cfg.irs.elevation_range_deg
    c_no_irs = cfg.model_copy(deep=True)
    c_no_irs.irs.enabled = False
    random_angles = IRSAngles(
        azimuth_deg=rng.uniform(az_lo, az_hi, n).tolist(),
        elevation_deg=rng.uniform(el_lo, el_hi, n).tolist())
    pos = [cfg.receiver.position.x, cfg.receiver.position.y, cfg.receiver.position.z]
    fixed = optimize_irs(cfg, pos, n_restarts=3, seed=seed + 1)
    robust = robust_optimize(cfg, pos, radius_m=0.15, n_samples=10, seed=seed + 2)
    return {
        "A_no_irs": {"angles": IRSAngles.zeros(n), "config": c_no_irs},
        "B_random": {"angles": random_angles, "config": cfg.model_copy(deep=True)},
        "C_fixed_point": {"angles": fixed["angles"], "config": cfg.model_copy(deep=True)},
        "D_robust": {"angles": robust["angles"], "config": cfg.model_copy(deep=True)},
    }
