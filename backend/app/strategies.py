"""Strategy comparison (A: no IRS, B: random, C: fixed-point, D: robust/agent)
and the scripted blockage timeline scenario. Pure physics + classical
re-optimization; the LLM agent reuses optimize/robust tools on top of the
same functions."""
from __future__ import annotations

import copy
import math
import numpy as np

from . import physics
from .optimizers import robust_optimize, optimize_irs
from .schemas import SimConfig, IRSAngles


def _n(cfg: SimConfig) -> int:
    return cfg.irs.n_elements if cfg.irs.enabled else 0


def _angles_lookup(angles: IRSAngles, cfg: SimConfig) -> tuple[list, list]:
    n = _n(cfg)
    az = list(angles.azimuth_deg)[:n]
    el = list(angles.elevation_deg)[:n]
    return az + [0.0] * max(0, n - len(az)), el + [0.0] * max(0, n - len(el))


def _rx_point(cfg: SimConfig) -> list[float]:
    return [cfg.receiver.position.x, cfg.receiver.position.y, cfg.receiver.position.z]

STRATEGY_KEYS = ["A_no_irs", "B_random", "C_fixed_point", "D_robust"]
STRATEGY_LABELS = {
    "A_no_irs": "A — No IRS",
    "B_random": "B — Random IRS",
    "C_fixed_point": "C — Fixed-point optimized",
    "D_robust": "D — Agent robust IRS",
}


def run_comparison(cfg: SimConfig, scenario: str = "static",
                   heatmap_resolution: int = 24) -> dict:
    """Run the four strategies on an identical scenario.

    static:   receiver at nominal position, no obstacle; aggregates over a
              full room sweep per strategy.
    moving:   receiver walks along a path; strategies A/B/C keep fixed IRS,
              D re-optimizes (robust horizon) whenever the link degrades.
    blockage: person standing on the LED-RX line, receiver static; same
              sweep based aggregates with the obstacle enabled.
    """
    res = max(8, min(int(heatmap_resolution), 40))
    strategies = []
    az, el, cfg_a = None, None, None

    # reference optimization at the nominal receiver position
    pos = _rx_point(cfg)
    no_cfg = cfg.model_copy(deep=True)
    no_cfg.irs.enabled = False

    rng = np.random.default_rng(7)
    az_lo, az_hi = cfg.irs.azimuth_range_deg
    el_lo, el_hi = cfg.irs.elevation_range_deg
    random_angles = IRSAngles(azimuth_deg=rng.uniform(az_lo, az_hi, _n(cfg)).tolist(),
                              elevation_deg=rng.uniform(el_lo, el_hi, _n(cfg)).tolist())
    fixed = optimize_irs(cfg, pos, n_restarts=2, seed=41)
    robust = robust_optimize(cfg, pos, radius_m=0.15, n_samples=10, seed=43, n_restarts=2)
    cfg_rob = cfg.model_copy(deep=True)
    cfg_rob.led.power_w = fixed["metrics"]["p_led_w"]

    strategy_states = {
        "A_no_irs": {"azimuth_deg": [0.0] * _n(cfg), "elevation_deg": [0.0] * _n(cfg), "config": no_cfg},
        "B_random": {"azimuth_deg": random_angles.azimuth_deg, "elevation_deg": random_angles.elevation_deg,
                     "config": cfg.model_copy(deep=True)},
        "C_fixed_point": {"azimuth_deg": fixed["angles"].azimuth_deg,
                          "elevation_deg": fixed["angles"].elevation_deg,
                          "config": cfg.model_copy(deep=True)},
        "D_robust": {"azimuth_deg": robust["angles"].azimuth_deg,
                     "elevation_deg": robust["angles"].elevation_deg,
                     "config": cfg_rob},
    }

    per_strategy = {}
    base_positions = np.linspace(0, 0, 1)
    if scenario == "moving":
        path = _path_points(base_positions)
        waypoints = _default_path(cfg)
    else:
        waypoints = [(_rx_point(cfg), False)]
        path = None

    sweep_cfg_by_key = {}
    for key in STRATEGY_KEYS:
        st = strategy_states[key]
        sc = st["config"].model_copy(deep=True)
        if scenario == "blockage":
            sc.obstacle.enabled = True
            sc.obstacle.center.x = (cfg.led.position.x + cfg.receiver.position.x) / 2.0
            sc.obstacle.center.y = (cfg.led.position.y + cfg.receiver.position.y) / 2.0
        sweep_cfg_by_key[key] = sc
        hm = physics.sweep(sc, st["azimuth_deg"], st["elevation_deg"], res)
        per_strategy[key] = {
            "key": key, "label": STRATEGY_LABELS[key],
            "azimuth_deg": st["azimuth_deg"], "elevation_deg": st["elevation_deg"],
            "heatmap": hm, "path_metrics": None,
        }

    if scenario == "moving":
        per_strategy = _fill_path_metrics(per_strategy, waypoints, strategy_states)
    else:
        per_strategy = _fill_static_metrics(per_strategy, strategy_states)

    payload = {k: {
        "key": v["key"], "label": v["label"],
        "aggregates": v["aggregates"],
        "heatmap": v["heatmap"],
        "path_metrics": v["path_metrics"],
        "azimuth_deg": v["azimuth_deg"], "elevation_deg": v["elevation_deg"],
    } for k, v in per_strategy.items()}
    return {"scenario": scenario, "strategies": payload,
            "receiver_position": _rx_point(cfg),
            "path": [list(p) for p in waypoints] if scenario == "moving" else None}


def _fill_static_metrics(per_strategy: dict, strategy_states: dict) -> dict:
    for key in STRATEGY_KEYS:
        hm = per_strategy[key]["heatmap"]
        per_strategy[key]["aggregates"] = {
            "outage_probability": hm["outage_probability"],
            "mean_ber": hm["mean_ber"],
            "worst_ber": hm["worst_ber"],
            "mean_power_w": hm["mean_power_w"],
            "mean_irradiance_w_m2": hm["mean_irradiance_w_m2"],
        }
        # also evaluate the exact nominal point
        st = strategy_states[key]
        c = st["config"]
        m = physics.evaluate(c, st["azimuth_deg"], st["elevation_deg"],
                             [c.receiver.position.x, c.receiver.position.y, c.receiver.position.z])
        per_strategy[key]["nominal_point"] = m
    return per_strategy


def _default_path(cfg: SimConfig) -> list[list[float]]:
    """Receiver walks from near one wall toward the nominal desk point."""
    start = {"x": 1.2, "y": 1.6, "z": cfg.receiver.position.z}
    end = {"x": 3.8, "y": 3.4, "z": cfg.receiver.position.z}
    n = 9
    return [[start["x"] + (end["x"] - start["x"]) * i / (n - 1),
             start["y"] + (end["y"] - start["y"]) * i / (n - 1),
             cfg.receiver.position.z] for i in range(n)]


def _fill_path_metrics(per_strategy: dict, waypoints: list, strategy_states: dict) -> dict:
    for key in STRATEGY_KEYS:
        st = strategy_states[key]
        cfg_s = st["config"].model_copy(deep=True)
        rows, events = [], []
        for i, wp in enumerate(waypoints):
            az, el = st["azimuth_deg"], st["elevation_deg"]
            cfg_p = cfg_s.model_copy(deep=True)
            cfg_p.receiver.position.x, cfg_p.receiver.position.y, cfg_p.receiver.position.z = wp
            cfg_p.clamp_vertical()
            m = physics.evaluate(cfg_p, az, el, wp)
            if key == "D_robust" and (m["link_status"] != "stable"):
                # agent-style re-steering: robust re-optimization around new point
                out = robust_optimize(cfg_p, wp, radius_m=0.12, n_samples=8, seed=60 + i, n_restarts=2)
                cfg_p.led.power_w = out["metrics"]["p_led_w"]
                m2 = physics.evaluate(cfg_p, out["angles"].azimuth_deg, out["angles"].elevation_deg, wp)
                rows.append({"waypoint": i, "position": list(wp), **m2})
                events.append({"waypoint": i,
                               "ber_before": m["ber"], "ber_after": m2["ber"]})
                st = copy.deepcopy(st)
                st["azimuth_deg"] = out["angles"].azimuth_deg
                st["elevation_deg"] = out["angles"].elevation_deg
                cfg_s = cfg_p
            else:
                rows.append({"waypoint": i, "position": list(wp), **m})
        bers = [r["ber"] for r in rows if r["ber"] is not None]
        per_strategy[key]["aggregates"] = {
            "outage_probability": sum(1 for r in rows
                                      if r["link_status"] != "stable") / len(rows),
            "mean_ber": float(np.mean(bers)) if bers else None,
            "worst_ber": float(max(bers)) if bers else None,
            "mean_power_w": float(np.mean([r["received_power_w"] for r in rows])),
            "mean_irradiance_w_m2": float(np.mean([r["irradiance_w_m2"] for r in rows])),
        }
        per_strategy[key]["path_metrics"] = rows
        if key == "D_robust":
            per_strategy[key]["reoptimize_events"] = events
    return per_strategy


def run_timeline(cfg: SimConfig, x_res: int = 14) -> dict:
    """Scripted demo: a person walks across the direct LED-RX path.

    Every time step evaluates all four strategies. Strategy D is the
    agent stand-in: when the blockage predictor raises its risk above 0.5
    (or BER exceeds target while unstable), it performs a robust
    re-optimization, marked as a re-steering event.
    """
    steps = 15
    ox0 = cfg.led.position.x - 0.8
    ox1 = cfg.receiver.position.x + cfg.receiver.position.x * 0.2
    oy = 0.5 * (cfg.led.position.y + cfg.receiver.position.y)
    xs = np.linspace(ox0, ox1, steps)

    midx = 0.5 * (cfg.led.position.x + cfg.receiver.position.x)
    midy = 0.5 * (cfg.led.position.y + cfg.receiver.position.y)

    # baseline IRS states are computed without the obstacle
    unblocked = cfg.model_copy(deep=True)
    unblocked.obstacle.enabled = False
    pos = _rx_point(cfg)
    fixed = optimize_irs(unblocked, pos, n_restarts=2, seed=77)
    robust = robust_optimize(unblocked, pos, radius_m=0.15, n_samples=8, seed=78, n_restarts=2)
    no_cfg = unblocked.model_copy(deep=True)
    no_cfg.irs.enabled = False
    rng = np.random.default_rng(9)
    az_lo, az_hi = unblocked.irs.azimuth_range_deg
    el_lo, el_hi = unblocked.irs.elevation_range_deg
    states = {
        "A_no_irs": {"config": no_cfg, "angles": {"azimuth_deg": [0.0] * _n(cfg), "elevation_deg": [0.0] * _n(cfg)}},
        "B_random": {"config": unblocked.model_copy(deep=True), "angles": {
            "azimuth_deg": rng.uniform(az_lo, az_hi, _n(cfg)).tolist(),
            "elevation_deg": rng.uniform(el_lo, el_hi, _n(cfg)).tolist()}},
        "C_fixed_point": {"config": unblocked.model_copy(deep=True),
                          "angles": {"azimuth_deg": fixed["angles"].azimuth_deg,
                                     "elevation_deg": fixed["angles"].elevation_deg}},
        "D_robust": {"config": unblocked.model_copy(deep=True),
                     "angles": {"azimuth_deg": robust["angles"].azimuth_deg,
                                "elevation_deg": robust["angles"].elevation_deg}},
    }

    rows = []
    events = []
    history = []
    for i, ox in enumerate(xs):
        row = {"step": i, "obstacle_x": round(float(ox), 3),
               "obstacle_y": round(float(midy), 3)}
        for key, st in states.items():
            c = st["config"].model_copy(deep=True)
            c.obstacle.enabled = True
            c.obstacle.center.x = float(ox)
            c.obstacle.center.y = float(midy)
            m = physics.evaluate(c, st["angles"]["azimuth_deg"], st["angles"]["elevation_deg"], pos)
            m.pop("link_status", None)
            status = physics.link_status(c, m["ber"]) if _n(c) else physics.link_status(c, m["ber"])
            m["link_status"] = status
            history.append({"received_power_w": m["received_power_w"],
                            "obstacle_x": float(ox), "obstacle_y": float(midy), "t": i})
            if key == "D_robust" and status != "stable" and i >= 2:
                out = robust_optimize(c, pos, radius_m=0.10, n_samples=6, seed=90 + i, n_restarts=2)
                cfg_apply = c.model_copy(deep=True)
                cfg_apply.led.power_w = out["metrics"]["p_led_w"]
                m2 = physics.evaluate(cfg_apply, out["angles"].azimuth_deg,
                                      out["angles"].elevation_deg, pos)
                ber_before = m.get("ber")
                st["angles"] = {"azimuth_deg": out["angles"].azimuth_deg,
                                "elevation_deg": out["angles"].elevation_deg}
                m = m2
                events.append({"step": i, "ber_before": ber_before,
                               "ber_after": m.get("ber"),
                               "received_power_after_w": m["received_power_w"]})
            row[f"ber_{key}"] = m.get("ber")
            row[f"power_{key}"] = m.get("received_power_w")
            row[f"status_{key}"] = m.get("link_status", status)
        from .predictor import predict_blockage
        risk_rec = predict_blockage(c if False else states["D_robust"]["config"],
                                    history[-8:] if len(history) >= 3 else history,
                                    (cfg.led.position.x, cfg.led.position.y),
                                    (cfg.receiver.position.x, cfg.receiver.position.y))
        row["blockage_risk"] = risk_rec["risk"]
        rows.append(row)
    return {"steps": rows, "reoptimize_events": events,
            "obstacle_path": {"x": xs.tolist(), "y": float(midy)}}
