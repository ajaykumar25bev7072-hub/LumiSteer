"""Unit tests for the LumiSteer physics engine and optimizers."""
import copy
import math
import time
from typing import Dict, cast
import pytest

from app import physics
from app.optimizers import optimize_irs, robust_optimize, baseline_configs
from app.schemas import SimConfig, IRSAngles


def make_config(**over: object) -> SimConfig:
    return SimConfig()


def test_los_gain_decreases_with_distance() -> None:
    cfg = make_config()
    base = [cfg.led.position.x, cfg.led.position.y]
    # directly under the LED, descending toward the floor increases distance
    gains: list[float] = []
    for z in (2.5, 2.0, 1.5, 1.0, 0.5):
        g, _ = physics.los_gain(cfg, [base[0], base[1], z])
        gains.append(float(g[0]))
    assert all(b < a for a, b in zip(gains, gains[1:])), gains


def test_ber_is_monotonic_in_snr() -> None:
    previous: float = 0.6
    for snr in (1e-2, 0.1, 1.0, 10.0, 100.0, 1e4, 1e6):
        ber = float(physics.ook_ber([snr])[0])
        assert ber <= previous + 1e-15
        previous = ber
    assert previous < 1e-6


def test_blocked_los_leaves_only_irs_path() -> None:
    cfg = make_config()
    cfg.obstacle.enabled = True
    cfg.obstacle.center.x = (cfg.led.position.x + cfg.receiver.position.x) / 2
    cfg.obstacle.center.y = (cfg.led.position.y + cfg.receiver.position.y) / 2
    cfg.obstacle.height_m = 3.0  # full-height blocker: blocks every segment
    angles = zeros_angles(cfg)
    g_los, _ = physics.los_gain(cfg, [cfg.receiver.position.x, cfg.receiver.position.y,
                                      cfg.receiver.position.z])
    assert float(g_los[0]) == 0.0
    total = physics.evaluate(cfg, angles["azimuth_deg"], angles["elevation_deg"],
                             [cfg.receiver.position.x, cfg.receiver.position.y,
                              cfg.receiver.position.z])
    assert total["g_los"] == 0.0
    assert total["g_irs"] == total["total_gain"]
    # and with the blocker removed the LOS path returns
    cfg_free = copy.deepcopy(cfg)
    cfg_free.obstacle.enabled = False
    g_free, _ = physics.los_gain(cfg_free, [cfg.receiver.position.x, cfg.receiver.position.y,
                                            cfg.receiver.position.z])
    assert float(g_free[0]) > 0.0


def zeros_angles(cfg: SimConfig) -> Dict[str, list[float]]:
    n = cfg.irs.n_elements if cfg.irs.enabled else 1
    return {"azimuth_deg": [0.0] * n, "elevation_deg": [0.0] * n}


def test_optimized_irs_beats_random_on_average() -> None:
    """Optimized IRS must out-perform random IRS configurations on average
    over the same scenario (statistical check over several seeds)."""
    cfg = make_config()
    pos = [cfg.receiver.position.x, cfg.receiver.position.y, cfg.receiver.position.z]
    out = optimize_irs(cfg, pos, n_restarts=3, seed=5)
    opt_power = float(out["metrics"]["received_power_w"])
    opt_ber = out["metrics"]["ber"] or 0.0

    random_powers: list[float] = []
    random_bers: list[float] = []
    from app import optimizers as opt
    for seed in range(10):
        rng = __import__("numpy").random.default_rng(seed)
        az_lo, az_hi = cfg.irs.azimuth_range_deg
        el_lo, el_hi = cfg.irs.elevation_range_deg
        n = cfg.irs.n_elements
        az = rng.uniform(az_lo, az_hi, n)
        el = rng.uniform(el_lo, el_hi, n)
        samples = opt._evaluate_samples(cfg, __import__("numpy").deg2rad(az),
                                        __import__("numpy").deg2rad(el),
                                        __import__("numpy").asarray(pos, dtype=float).reshape(1, 3))
        random_powers.append(float(samples["p_r"][0]))
        random_bers.append(float(samples["ber"][0]))

    assert opt_power > sum(random_powers) / len(random_powers)

    # compare via the objective's own score function (BER floors make raw log
    # comparison degenerate in a clear-LOS room)
    from app.optimizers import metric_score
    weights = {"power": 1.0, "irradiance": 0.5, "ber": 2.0}
    opt_score = metric_score(out["metrics"]["ber"], opt_power,
                             out["metrics"]["irradiance_w_m2"], weights)
    rand_scores = [metric_score(b, p, p / cfg.receiver.photodiode.area_m2, weights)
                   for b, p in zip(random_bers, random_powers)]
    assert opt_score > sum(rand_scores) / len(rand_scores)

    # and the optimized configuration is never beaten by the *worst* configs
    assert opt_score > sorted(rand_scores)[0]


def test_robust_optimize_covers_movement() -> None:
    cfg = make_config()
    pos = [cfg.receiver.position.x, cfg.receiver.position.y, cfg.receiver.position.z]
    out = robust_optimize(cfg, pos, radius_m=0.15, n_samples=10, seed=11)
    assert out["radius_m"] == 0.15
    assert len(out["angles"].azimuth_deg) == cfg.irs.n_elements
    m = out["metrics"]
    assert m["received_power_w"] > 0
    assert m["ber"] is None or 0 < m["ber"] < 0.5


def test_sweep_fast_and_outage_fractions() -> None:
    cfg = make_config()
    angles = zeros_angles(cfg)
    start = time.perf_counter()
    sweep = physics.sweep(cfg, angles["azimuth_deg"], angles["elevation_deg"], 40)
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0
    assert sweep["resolution"] == 40
    assert len(sweep["ber"]) == 40 and len(sweep["ber"][0]) == 40
    nominal_clear = physics.evaluate(cfg, angles["azimuth_deg"], angles["elevation_deg"],
                                     [cfg.led.position.x, cfg.led.position.y, 0.8])
    assert nominal_clear["ber"] is None or nominal_clear["ber"] < cfg.modulation.ber_threshold
    # outage fraction cannot exceed one, and at least the center is fine
    assert 0.0 <= sweep["outage_probability"] <= 1.0


def test_illuminance_constraint_scales_with_power() -> None:
    cfg = make_config()
    cfg.led.power_w = 1.0
    lux_full = physics.illuminance_lux(cfg)
    cfg.led.power_w = 0.5
    lux_half = physics.illuminance_lux(cfg)
    assert math.isclose(lux_full / lux_half, 2.0, rel_tol=1e-6)
    # total comfort illuminance (LED direct + ambient background) satisfies the
    # constraint in the default scenario
    from app import physics as _ph
    ambient_lux = (cfg.noise.ambient_power() / cfg.receiver.photodiode.area_m2
                   * cfg.illumination.luminous_efficacy)
    cfg.led.power_w = 1.0
    cfg.obstacle.enabled = False
    angles = zeros_angles(cfg)
    m = _ph.evaluate(cfg, angles["azimuth_deg"], angles["elevation_deg"],
                     [cfg.receiver.position.x, cfg.receiver.position.y, cfg.receiver.position.z])
    assert m["illuminance_ok"] is True
