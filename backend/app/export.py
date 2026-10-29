"""CSV / Markdown report export helpers."""
from __future__ import annotations


def sweep_to_csv(sweep: dict) -> str:
    lines = ["x_m,y_m,received_power_W,irradiance_W_m2,ber"]
    for j, y in enumerate(sweep["y"]):
        for i, x in enumerate(sweep["x"]):
            ber = sweep["ber"][j][i] if i < len(sweep["ber"][j]) else ""
            line = (f"{x:.4f},{y:.4f},{sweep['received_power_w'][j][i]:.6e},"
                    f"{sweep['irradiance_w_m2'][j][i]:.6e},{ber if ber is not None else ''}")
            lines.append(line)
    return "\n".join(lines) + "\n"


def comparison_to_csv(comparison: dict) -> str:
    lines = ["strategy,outage_probability,mean_ber,worst_ber,mean_power_W,mean_irradiance_W_m2"]
    for key, st in comparison["strategies"].items():
        a = st["aggregates"]
        lines.append(f"{st['label']},{a.get('outage_probability', '')},{a.get('mean_ber') or ''},"
                     f"{a.get('worst_ber') or ''},{a.get('mean_power_w') or ''},"
                     f"{a.get('mean_irradiance_w_m2') or ''}")
    return "\n".join(lines) + "\n"


def report_markdown(config: dict, comparison: dict | None, agent_summary: str | None) -> str:
    from .schemas import SimConfig
    cfg = SimConfig.model_validate(config)
    lines = [
        "# LumiSteer — Link Report",
        "",
        f"Room: {cfg.room.width} x {cfg.room.depth} x {cfg.room.height} m",
        f"LED: power {cfg.led.power_w} W (max {cfg.led.max_power_w}), half-angle {cfg.led.half_angle_deg}°",
        f"Receiver: ({cfg.receiver.position.x:.2f}, {cfg.receiver.position.y:.2f}, {cfg.receiver.position.z:.2f}) m, "
        f"PD area {cfg.receiver.photodiode.area_m2 * 1e4:.2f} cm², FOV {cfg.receiver.photodiode.fov_deg}°",
        f"IRS: {cfg.irs.rows}x{cfg.irs.cols} elements, reflectivity {cfg.irs.reflectivity}, "
        f"sigma {cfg.irs.sigma_deg}°, wall {cfg.irs.wall}",
        f"Obstacle: {'enabled' if cfg.obstacle.enabled else 'off'}, "
        f"radius {cfg.obstacle.radius_m} m at ({cfg.obstacle.center.x}, {cfg.obstacle.center.y})",
        f"Noise: B {cfg.noise.bandwidth_hz / 1e6:.0f} MHz, ambient {cfg.noise.ambient_class}, "
        f"R_L {cfg.noise.load_resistance_ohm:.0f} Ω, T {cfg.noise.temperature_k:.0f} K",
        f"Modulation: {cfg.modulation.scheme}, BER target {cfg.modulation.ber_threshold}",
        "",
    ]
    if agent_summary:
        lines += ["## Agent summary", "", agent_summary, ""]
    if comparison:
        lines += ["## Strategy comparison (" + comparison.get("scenario", "static") + ")", ""]
        lines += ["| Strategy | Outage probability | Mean BER | Worst BER | Mean power (W) | Mean irradiance (W/m²) |",
                  "|---|---|---|---|---|---|"]
        for st in comparison["strategies"].values():
            a = st["aggregates"]
            def fmt(v):
                if v is None:
                    return "—"
                if isinstance(v, float):
                    if 1e-4 < abs(v) < 1e4:
                        return f"{v:.4g}"
                    return f"{v:.3e}"
                return str(v)
            lines.append(f"| {st['label']} | {fmt(a.get('outage_probability'))} | {fmt(a.get('mean_ber'))} | "
                         f"{fmt(a.get('worst_ber'))} | {fmt(a.get('mean_power_w'))} | {fmt(a.get('mean_irradiance_w_m2'))} |")
        lines.append("")
    lines += ["## Model equations", "",
              "- H_los = (m+1)·A / (2π·d²) · cosᵐ(φ) · T_s · g(ψ) · cos(ψ), ψ ≤ FOV else 0",
              "- P_r = P_t · (H_los + Σ_elements H_irs element)",
              "- σ_noise² = 2qR(P_r + P_ambient)B + 4kTB/R_L",
              "- SNR = (R·P_r)²/σ² ; OOK BER = Q(√SNR) = 0.5·erfc(√(SNR/2))",
              ""]
    return "\n".join(lines)
