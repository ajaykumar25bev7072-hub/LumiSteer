import Layout from '../components/Layout'

function Eq({ children }: { children: React.ReactNode }) {
  return <code className="block font-mono text-[13px] bg-white/5 border border-white/10 rounded-lg px-3 py-2 overflow-x-auto">{children}</code>
}

function H2({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xl font-semibold mt-10 mb-3">{children}</h2>
}

export default function MethodologyPage() {
  return (
    <Layout>
      <div className="mx-auto max-w-4xl px-4 py-8 leading-relaxed text-white/80">
        <h1 className="text-3xl font-bold">Methodology</h1>
        <p className="mt-3">
          Every number in LumiSteer (received power, irradiance, SNR, BER, illuminance, outage
          probability) is computed by the deterministic backend physics engine — the LLM never
          computes or invents a metric; it selects tools and quotes their outputs.
        </p>

        <H2>1 · Model overview</H2>
        <p className="mt-2">Room 5 × 5 × 3 m (configurable), one ceiling LED facing down, one photodiode on a
          desk facing up (default height 0.8 m), one rectangular IRS panel of N×M two-tilt mirror
          elements on a wall (default 8×8), and a cylindrical movable blocker (person).</p>

        <H2>2 · Direct LOS channel gain</H2>
        <Eq>H_los = (m+1) · A_pd / (2π · d²) · cos^m(φ) · T_s · g(ψ) · cos(ψ),   ψ ≤ FOV else 0</Eq>
        <Eq>m = −ln 2 / ln cos(Φ_half)     (default Φ_half = 60° → m = 1.0)</Eq>
        <p className="mt-2 text-sm text-white/60">
          A_pd = photodiode area, T_s = optical filter gain, g(ψ) = 1 when the optical
          concentrator is off, else n²/sin²(concentrator FOV). Blocker: a circular person model —
          the closest-approach point of the LED→RX segment to the person's XY axis must fall
          inside the radius and within the person's vertical extent; blocked segments are
          attenuated by a configurable factor (default 0 = full block).
        </p>

        <H2>3 · IRS path model</H2>
        <p className="mt-2">Each element j contributes:</p>
        <Eq>H_j = [(m+1)/(2π d₁²)] · cos^m(φ₁) · cos(α₁) · A_el · ρ</Eq>
        <Eq>&nbsp;&nbsp;· exp(−δ² / 2σ²) · [A_pd / d₂²] · cos(ψ₂) · blockage(d₁,d₂)</Eq>
        <p className="mt-2 text-sm text-white/60">
          φ₁ = incidence on the element from the LED's Lambertian cone; α₁ = incidence on the
          element's tilted normal; the reflected direction follows the specular law
          r = s − 2(s·n)n for the element normal n (azimuth tilt about the wall's vertical axis,
          elevation tilt about the wall's horizontal axis); δ is the angle between the actual
          specular direction and the direction to the receiver, with a Gaussian beam-spread
          σ (default 5°) modeling non-ideal element directivity; d₁/d₂ are LED→element and
          element→RX distances. Total IRS gain is the sum over elements (H_irs = Σ H_j).
          <br />
          <b>Swappability:</b> this is a deliberately simple, swappable module — replace
          <code className="mx-1">app/physics.py · irs_gain()</code> with your own model; nothing else changes.
        </p>

        <H2>4 · Noise and BER</H2>
        <Eq>σ² = 2·q·R·(P_r + P_ambient)·B + 4·k·T·B / R_L   (shot + thermal)</Eq>
        <Eq>SNR = (R · P_r)² / σ²</Eq>
        <Eq>BER_OOK = Q(√SNR) = 0.5 · erfc(√(SNR/2))   (scipy.special.erfc)</Eq>
        <p className="mt-2 text-sm text-white/60">
          q = 1.602e-19 C, k = Boltzmann, defaults B = 10 MHz, R = 0.54 A/W, R_L = 10 kΩ, T = 295 K.
          Ambient light slider maps to background optical power at the receiver
          (low 1e-4 W · medium 1e-3 W · high 1e-2 W). P_ambient enters shot noise; BER is the
          OOK formula and the BER function is modular (PAM-4 slot ready). Outage ⇔ BER {'>'} target
          (default 1e-3).
        </p>

        <H2>5 · Received power, irradiance, illuminance</H2>
        <Eq>P_r = P_t · (H_los + H_irs);  E = P_r / A_pd [W/m²]</Eq>
        <Eq>E_v(work plane) = η_lum · (m+1)/(2π d²) · cos^m(θ) · cos(θ_w) · P_t + E_ambient [lux]</Eq>
        <p className="mt-2 text-sm text-white/60">
          η_lum = 264 lm/W (documented conversion). Comfort illumination includes the ambient
          background lighting of the room (ambient background irradiance at the photodiode plane ×
          the same efficacy) because a single 1 W VLC LED cannot reach typical room-lighting levels
          alone. Constraint: 300 lux ≤ E_v ≤ 1000 lux by default; enforced in all optimizations.
        </p>

        <H2>6 · Optimization tools (classical, never the LLM)</H2>
        <p className="mt-2 text-sm text-white/60">
          Objective per sample: weighted score of normalized received power and irradiance minus
          a clamped log10(BER) penalty; robust mode averages per-position scores with a 35 %
          worst-case term. Optimizer: scipy L-BFGS-B over the 2·N·M tilt variables with
          deterministic multi-start; robust mode samples receiver positions in a disk (default
          15 cm radius) plus TX-tilt-jitter-equivalent perturbations. LED power is jointly capped
          so that max-illuminance holds and never drops below the 10 % dim floor.
        </p>
        <Eq>score = w_p·P_r/P_ref + w_i·E/E_ref − w_b·(log10(BER_clamped) − (−18))</Eq>

        <H2>7 · Blockage predictor</H2>
        <p className="mt-2 text-sm text-white/60">
          Pure classical code (moving average + least-squares slope of recent received-power
          samples, plus obstacle velocity toward the LED→RX line). Output is a risk score in
          [0,1]. No LLM involved.
        </p>

        <H2>8 · How the Nemotron agent is (and is not) used</H2>
        <ul className="list-disc pl-6 text-sm text-white/60 space-y-1">
          <li>Served via Nebius Token Factory (OpenAI-compatible API, base URL https://api.tokenfactory.nebius.com/v1, NVIDIA Nemotron open model, temperature 0.2).</li>
          <li>Role: supervisor — observe telemetry JSON, diagnose (blockage? receiver moved? ambient noise? stale IRS?), choose and sequence tools (simulate, optimize_irs, robust_optimize, predict_blockage), verify targets, explain in plain language.</li>
          <li>Hard rules in the system prompt: never compute numbers, quote only values returned by tools, respect power/illuminance/tilt constraints; at most 4 tool iterations per event.</li>
          <li>Native function/tool calling with a strict JSON-output fallback ({"{"}action, args{"}"}); tool arguments re-validated server-side; timeouts, retry, and a labelled "demo cache" replay if the API is unavailable.</li>
          <li>NOT used for: physics, optimization math, or any displayed metric. The app works fully without the LLM with manual optimize buttons.</li>
        </ul>

        <H2>9 · Parameter table (defaults — all editable)</H2>
        <div className="overflow-x-auto">
          <table className="text-sm w-full border-collapse">
            <thead><tr className="text-left text-white/50 border-b border-white/10">
              <th className="py-2 pr-4">Parameter</th><th>Value</th></tr></thead>
            <tbody className="align-top">
              {[
                ['Room', '5 × 5 × 3 m'],
                ['LED position / power / half-angle', 'ceiling center (2.5, 2.5, 3.0) m · 1.0 W (dimmable 10–100 %) · 60°'],
                ['Photodiode', '1 cm² · R = 0.54 A/W · FOV 70° · filter gain 1 · concentrator off'],
                ['IRS', 'wall north · 8 × 8 elements · 3×3 cm each · reflectivity 0.9 · σ = 5° · tilts ±75°'],
                ['Noise', 'B = 10 MHz · ambient medium (1e-3 W) · R_L = 10 kΩ · T = 295 K'],
                ['Modulation / threshold', 'OOK · BER target 1e-3'],
                ['Illumination', 'min 300 lux · max 1000 lux · η = 264 lm/W'],
                ['Obstacle', 'circle r = 0.3 m · 1.7 m tall · attenuation 0 (off by default)'],
              ].map(([k, v]) => (
                <tr key={k} className="border-b border-white/5">
                  <td className="py-2 pr-4 text-white/70">{k}</td>
                  <td className="py-2 text-white/60 font-mono text-[12px]">{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <H2>10 · Limitations</H2>
        <ul className="list-disc pl-6 text-sm text-white/60 space-y-1">
          <li>Simulation only — no real hardware control, no real-time sub-millisecond control, no multi-user networking.</li>
          <li>Simplified IRS model: specular element reflection with a Gaussian alignment factor; no inter-element scattering, surface roughness or manufacturing tolerances.</li>
          <li>Ambient background is position-independent; diffusive reflections from walls are not modeled (LOS + IRS only).</li>
          <li>Photometric conversion uses a single efficacy constant rather than a spectral power distribution.</li>
          <li>Strategy-D "agent re-steer" events on the timeline/comparison pages are the classical robust optimizer triggered by the same threshold rule the live agent applies, so demos never depend on API uptime.</li>
        </ul>
      </div>
    </Layout>
  )
}
