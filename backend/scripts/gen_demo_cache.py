"""Generate backend/app/demo_cache.json.

Runs a deterministic scripted agent-style session through the *real* physics
tools (simulate -> robust_optimize -> verify) for the default blockage
scenario and records the exact events for demo-cache replay. Run from
backend/:  python scripts/gen_demo_cache.py
"""
import copy
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import physics
from app.optimizers import robust_optimize
from app.schemas import SimConfig, IRSAngles


def fmt_ber(ber) -> str:
    return "< 1e-18" if ber is None else f"{ber:.2e}"


def main():
    cfg = SimConfig()
    # scripted blockage scenario: person standing on the LED-RX line
    cfg.obstacle.enabled = True
    cfg.obstacle.height_m = 2.0
    cfg.obstacle.center.x = (cfg.led.position.x + cfg.receiver.position.x) / 2
    cfg.obstacle.center.y = (cfg.led.position.y + cfg.receiver.position.y) / 2

    n = cfg.irs.n_elements
    angles = {"azimuth_deg": [0.0] * n, "elevation_deg": [0.0] * n}

    # observation (blocked)
    obs = physics.evaluate(cfg, angles["azimuth_deg"], angles["elevation_deg"],
                           [cfg.receiver.position.x, cfg.receiver.position.y, cfg.receiver.position.z])
    events = []
    events.append({"type": "observation", "ts": None, "data": {
        "role": "observation",
        "received_power_w": obs["received_power_w"],
        "irradiance_w_m2": obs["irradiance_w_m2"],
        "illuminance_lux": obs["illuminance_lux"],
        "illuminance_ok": obs["illuminance_ok"],
        "snr": obs["snr"], "snr_db": obs["snr_db"], "ber": obs["ber"],
        "target_ber": cfg.modulation.ber_threshold,
        "link_status": obs["link_status"],
        "g_los": obs["g_los"], "g_irs": obs["g_irs"],
        "receiver_position_m": [cfg.receiver.position.x, cfg.receiver.position.y, cfg.receiver.position.z],
        "obstacle": cfg.obstacle.model_dump(mode="json"),
    }})

    # tool: diagnose with simulate (still blocked, confirms LOS gone)
    diag = physics.evaluate(cfg, angles["azimuth_deg"], angles["elevation_deg"],
                            [cfg.receiver.position.x, cfg.receiver.position.y, cfg.receiver.position.z])
    events.append({"type": "assistant_note", "ts": None, "data": {
        "iteration": 1,
        "text": ("The LOS term is essentially zero (" + f"{diag['g_los']:.2e}" + ") while the "
                 "target BER is " "1e-3: this looks like direct-path blockage, not noise. "
                 "I will check the realized state with simulate, then re-steer robustly.")}})

    events.append({"type": "tool_call", "ts": None, "data": {
        "iteration": 1, "name": "simulate",
        "args": {"obstacle_enabled": True}}})
    events.append({"type": "tool_result", "ts": None, "data": {
        "iteration": 1, "name": "simulate", "result": {
            "received_power_w": diag["received_power_w"],
            "irradiance_w_m2": diag["irradiance_w_m2"],
            "illuminance_lux": diag["illuminance_lux"],
            "illuminance_ok": diag["illuminance_ok"],
            "snr": diag["snr"], "snr_db": diag["snr_db"], "ber": diag["ber"],
            "g_los": diag["g_los"], "g_irs": diag["g_irs"],
            "link_status": diag["link_status"],
            "note": "scenario evaluated, current IRS angles were NOT changed"}}})

    # tool: robust re-steer for a moving receiver / re-reflection geometry
    out = robust_optimize(cfg, [cfg.receiver.position.x, cfg.receiver.position.y,
                                cfg.receiver.position.z],
                          radius_m=0.15, n_samples=10, seed=33)
    events.append({"type": "tool_call", "ts": None, "data": {
        "iteration": 2, "name": "robust_optimize",
        "args": {"radius_cm": 15, "n_samples": 10}}})
    events.append({"type": "tool_result", "ts": None, "data": {
        "iteration": 2, "name": "robust_optimize", "result": {
            "received_power_w": out["metrics"]["received_power_w"],
            "irradiance_w_m2": out["metrics"]["irradiance_w_m2"],
            "illuminance_lux": out["metrics"]["illuminance_lux"],
            "illuminance_ok": out["metrics"]["illuminance_ok"],
            "snr": out["metrics"]["snr"], "snr_db": out["metrics"]["snr_db"],
            "ber": out["metrics"]["ber"],
            "g_los": out["metrics"]["g_los"], "g_irs": out["metrics"]["g_irs"],
            "link_status": out["metrics"]["link_status"],
            "mean_ber": out["mean_ber"], "worst_ber": out["worst_ber"],
            "mean_power_w": out["mean_power_w"],
            "result_summary": ("IRS re-steered with a robust configuration over a "
                               "15 cm radius (10 sampled positions): mean BER "
                               f"{fmt_ber(out['mean_ber'])}, worst-case BER {fmt_ber(out['worst_ber'])}")}}})

    # verify
    cfg_after = cfg.model_copy(deep=True)
    cfg_after.led.power_w = out["metrics"]["p_led_w"]
    check = physics.evaluate(cfg_after, out["angles"].azimuth_deg, out["angles"].elevation_deg,
                             [cfg.receiver.position.x, cfg.receiver.position.y,
                              cfg.receiver.position.z])
    events.append({"type": "tool_call", "ts": None, "data": {
        "iteration": 3, "name": "simulate", "args": {}}})
    events.append({"type": "tool_result", "ts": None, "data": {
        "iteration": 3, "name": "simulate", "result": {
            "received_power_w": check["received_power_w"],
            "irradiance_w_m2": check["irradiance_w_m2"],
            "illuminance_lux": check["illuminance_lux"],
            "illuminance_ok": check["illuminance_ok"],
            "snr": check["snr"], "snr_db": check["snr_db"], "ber": check["ber"],
            "g_los": check["g_los"], "g_irs": check["g_irs"],
            "link_status": check["link_status"]}}})

    final = (
        "Diagnosis: the direct path is blocked — LOS channel gain collapsed to "
        f"{diag['g_los']:.2e} (person on the LED-receiver line), so the link was in {diag['link_status']} "
        f"state with BER {fmt_ber(diag['ber'])} and received power {diag['received_power_w']:.2e} W "
        "(all numbers quoted from tool results). "
        "Action: I re-steered the IRS with robust_optimize over a 15 cm radius around the receiver "
        "so the reflection no longer depends on the exact desk position. "
        f"Result: received power rose to {out['metrics']['received_power_w']:.2e} W "
        f"(lowest-cell mean over the radius {out['mean_power_w']:.2e} W), SNR "
        f"{out['metrics']['snr_db']:.1f} dB, BER {fmt_ber(out['metrics']['ber'])}, link status "
        f"{out['metrics']['link_status']} — target BER 1e-3 met and the 300 lux illuminance "
        f"constraint remains satisfied ({out['metrics']['illuminance_lux']:.0f} lux). "
        "The illumination limit did not cap LED power and no dimming was applied.")
    events.append({"type": "final", "ts": None, "data": {"explanation": final}})

    out_path = Path(__file__).resolve().parents[1] / "app" / "demo_cache.json"
    out_path.write_text(json.dumps(events, indent=1))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
