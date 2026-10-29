"""Classical blockage-risk predictor (no LLM involved).

Consumes a short history of telemetry samples (received power + obstacle
position over time) and returns a risk score in [0, 1]:
  - falling received-power trend raises risk (moving average + slope test),
  - an obstacle moving toward the LED->RX line raises risk.
"""
from __future__ import annotations

import math
from typing import List

WINDOW = 8


def _moving_avg(xs: List[float]) -> float:
    xs = xs[-WINDOW:]
    return sum(xs) / len(xs) if xs else 0.0


def _slope(xs: List[float]) -> float:
    """Least-squares slope of the last WINDOW samples (index vs value)."""
    y = xs[-WINDOW:]
    n = len(y)
    if n < 3:
        return 0.0
    xm = (n - 1) / 2.0
    ym = sum(y) / n
    num = sum((i - xm) * (v - ym) for i, v in enumerate(y))
    den = sum((i - xm) ** 2 for i in range(n))
    return num / den if den else 0.0


def _closest_2d(p0, p1, point) -> float:
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    den = dx * dx + dy * dy
    if den < 1e-12:
        return math.hypot(point[0] - p0[0], point[1] - p0[1])
    t = max(0.0, min(1.0, ((point[0] - p0[0]) * dx + (point[1] - p0[1]) * dy) / den))
    cx, cy = p0[0] + t * dx, p0[1] + t * dy
    return math.hypot(point[0] - cx, point[1] - cy)


def predict_blockage(cfg, history: List[dict], tx_pos=None, rx_pos=None) -> dict:
    """history: list of dicts with optional keys
    {received_power_w, obstacle_x, obstacle_y, t}.
    Returns {"risk": 0..1, "reason": str, "suggested_action": str}.
    """
    powers = [h.get("received_power_w", 0.0) for h in history if "received_power_w" in h]
    obs = [(h.get("obstacle_x"), h.get("obstacle_y"))
           for h in history if "obstacle_x" in h and "obstacle_y" in h]

    reasons: list[str] = []
    risk = 0.0

    if len(powers) >= 3:
        slope = _slope(powers)
        avg = _moving_avg(powers)
        base = max(powers[0], 1e-12)
        rel_drop = max(0.0, (base - avg) / base)
        rel_slope = max(0.0, -slope / base)
        if rel_drop > 0.2:
            risk = max(risk, min(1.0, 0.5 + rel_drop))
            reasons.append(f"received power trend down {rel_drop:.0%} vs window start")
        elif rel_slope > 0.02:
            risk = max(risk, min(0.6, 0.2 + 2 * rel_slope))
            reasons.append("received power starting to decline")

    if len(obs) >= 2 and tx_pos and rx_pos:
        (ox, oy), (ox0, oy0) = obs[-1], obs[-2]
        vel = math.hypot(ox - ox0, oy - oy0)
        if vel > 1e-6:
            # unit velocity vector
            vx, vy = (ox - ox0) / vel, (oy - oy0) / vel
            d_line = _closest_2d(tx_pos, rx_pos, (ox, oy))
            d_prev = _closest_2d(tx_pos, rx_pos, (ox0, oy0))
            approaching = d_line < d_prev - 1e-9
            if approaching and d_line < 1.5:
                closeness = max(0.0, 1.0 - d_line / 1.5)
                risk = max(risk, min(0.95, 0.3 + 0.5 * closeness + 0.1 * min(vel, 1.0)))
                reasons.append(
                    f"obstacle approaching the LED-RX line (closest 2D distance {d_line:.2f} m)")
            elif d_line < 0.6:
                risk = max(risk, 0.55)
                reasons.append(f"obstacle hovering near the direct path ({d_line:.2f} m)")

    risk = float(min(max(risk, 0.0), 1.0))
    if risk > 0.7:
        action = "Switch to a robust IRS configuration and/or verify LOS availability"
    elif risk > 0.4:
        action = "Prepare a fallback IRS configuration (robust_optimize)"
    else:
        action = "No action required"
    reason = "; ".join(reasons) if reasons else "no degradation indicators"
    return {"risk": risk, "reason": reason, "suggested_action": action}
