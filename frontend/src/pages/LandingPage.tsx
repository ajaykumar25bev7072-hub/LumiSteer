import { Link } from 'react-router-dom'
import Layout from '../components/Layout'

export default function LandingPage() {
  return (
    <Layout>
      <section className="mx-auto max-w-5xl px-4 py-16">
        <div className="grid md:grid-cols-2 gap-10 items-center">
          <div>
            <div className="inline-flex items-center gap-2 text-xs rounded-full border border-white/15 bg-white/5 px-3 py-1 text-white/60">
              Nebius x NVIDIA Global AI Hackathon · Nebius Token Factory · NVIDIA Nemotron
            </div>
            <h1 className="mt-4 text-4xl md:text-5xl font-bold leading-tight">
              Keep a working VLC link, <span className="text-yellow-300">even when someone walks through it.</span>
            </h1>
            <p className="mt-4 text-white/70 leading-relaxed text-lg">
              LumiSteer simulates an indoor visible-light communication link with a wall-mounted
              Intelligent Reflecting Surface. A Nemotron agent watches the physics engine's telemetry,
              diagnoses path blockage and receiver drift, and re-steers the IRS with real optimization
              tools — every number you see comes from the simulator, never from the LLM.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Link to="/simulator"
                className="rounded-xl bg-yellow-300 text-black font-semibold px-6 py-3 hover:bg-yellow-200 transition">
                Launch simulator →
              </Link>
              <Link to="/methodology"
                className="rounded-xl border border-white/20 px-6 py-3 hover:bg-white/5 transition">
                How it works
              </Link>
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-[#0d1424] p-4">
            <svg viewBox="0 0 320 240" className="w-full">
              {/* room */}
              <rect x="10" y="10" width="300" height="220" fill="none" stroke="rgba(255,255,255,.15)" rx="8" />
              {/* beam after agent re-steer */}
              <path d="M160 30 L 35 200" stroke="rgba(255,220,100,.25)" strokeWidth="2" strokeDasharray="3 4" />
              {/* person blocking */}
              <rect x="140" y="120" width="36" height="96" fill="rgba(244,63,94,.6)" rx="18" />
              <text x="158" y="112" textAnchor="middle" fontSize="9" fill="white/60">person</text>
              {/* IRS panel */}
              <g transform="rotate(-90 22 150)">
                <rect x="16" y="150" width="120" height="12" fill="#38bdf8" rx="3" />
              </g>
              {/* reflected beam */}
              <path d="M26 40 L 92 150 L 250 200" stroke="#38bdf8" strokeWidth="2.5" fill="none"
                markerEnd="url(#arrow)" />
              <circle cx="160" cy="28" r="7" fill="#fde047" />
              <circle cx="255" cy="202" r="8" fill="#4ade80" />
              <text x="255" y="228" textAnchor="middle" fontSize="9" fill="rgba(255,255,255,.5)">RX (desk)</text>
              <text x="160" y="16" textAnchor="middle" fontSize="9" fill="rgba(255,255,255,.5)">LED (ceiling)</text>
              <circle cx="160" cy="28" r="12" fill="none" stroke="rgba(253,224,71,.4)">
                <animate attributeName="r" values="10;16;10" dur="2s" repeatCount="indefinite" />
              </circle>
              <defs>
                <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
                  <path d="M0,0 L8,4 L0,8 z" fill="#38bdf8" />
                </marker>
              </defs>
            </svg>
            <p className="text-xs text-white/50 text-center mt-2">
              direct path blocked → IRS redirects the beam → agent explains every step
            </p>
          </div>
        </div>

        <div className="mt-16 grid md:grid-cols-3 gap-4">
          {[
            ['1 · Physics first', 'Deterministic NumPy engine: LOS Lambertian gain, per-element IRS reflection with a Gaussian alignment factor, shot+thermal noise, OOK BER via erfc. Unit-tested.'],
            ['2 · Optimize for movement', 'scipy L-BFGS-B over every mirror element — point mode and robust worst-case mode over a 15 cm receiver radius.'],
            ['3 · Nemotron supervises', 'The agent reads telemetry, picks tools (optimize, robust-optimize, predict blockage), verifies targets, and explains — strictly quoting tool outputs.'],
          ].map(([t, d]) => (
            <div key={t} className="rounded-xl border border-white/10 bg-white/5 p-4">
              <div className="font-semibold text-white/90">{t}</div>
              <p className="mt-1 text-sm text-white/60 leading-relaxed">{d}</p>
            </div>
          ))}
        </div>
      </section>
    </Layout>
  )
}
