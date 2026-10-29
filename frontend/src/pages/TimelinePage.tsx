import { useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer,
  CartesianGrid, BarChart, Bar, ReferenceDot, YAxis as Y,
} from 'recharts'
import Layout from '../components/Layout'
import { api } from '../api'
import type { TimelineResult } from '../types'
import { fmtBer, fmtSci } from '../lib/format'

const SERIES = [
  { key: 'ber_A_no_irs', label: 'A — No IRS', color: '#f43f5e' },
  { key: 'ber_B_random', label: 'B — Random IRS', color: '#f97316' },
  { key: 'ber_C_fixed_point', label: 'C — Fixed-point', color: '#a78bfa' },
  { key: 'ber_D_robust', label: 'D — Agent robust', color: '#34d399' },
]

export default function TimelinePage() {
  const [result, setResult] = useState<TimelineResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [ic, setIc] = useState({ // recharts y-scaling
    lo: 1e-10,
  })
  void ic
  const [error, setError] = useState<string | null>(null)

  const run = async (): Promise<void> => {
    setBusy(true); setError(null)
    try {
      const cfg = await api.getConfig()
      setResult(await api.timeline(cfg))
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  const data = result?.steps.map(s => ({
    step: s.step,
    ...SERIES.reduce<Record<string, number>>((acc, sv) => {
      const v = (s as unknown as Record<string, number | null>)[sv.key]
      acc[sv.key] = Math.max(v ?? 1e-18, 1e-18)
      return acc
    }, {}),
    risk: s.blockage_risk,
  })) ?? []

  const events = result?.reoptimize_events ?? []

  return (
    <Layout>
      <div className="mx-auto max-w-6xl px-4 py-6">
        <div className="flex items-center gap-3 mb-5 flex-wrap">
          <h1 className="text-2xl font-semibold mr-auto">Blockage timeline — a person walks across the beam</h1>
          <button onClick={run} disabled={busy}
            className="rounded-lg bg-yellow-300 hover:bg-yellow-200 disabled:opacity-50 px-4 py-2 text-sm font-semibold text-black">
            {busy ? 'Simulating…' : 'Run scripted walk'}
          </button>
        </div>

        {error && <div className="mb-3 rounded-lg bg-rose-500/10 border border-rose-400/40 text-rose-200 px-4 py-2 text-sm">{error}</div>}

        <p className="text-white/60 text-sm mb-4 max-w-3xl">
          The obstacle moves along a line crossing the LED→receiver path. Strategies A/B/C keep
          their fixed IRS. Strategy D is the agent's stand-in: when the link leaves the "Stable"
          state it performs a robust re-optimization — those re-steering events are marked below
          with vertical ticks on the walk. BER chart is log-scale; lower is better.
        </p>

        {result && (
          <div className="space-y-6">
            <div className="rounded-xl border border-white/10 bg-white/5 p-4 h-[380px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data}>
                  <CartesianGrid stroke="rgba(255,255,255,.08)" />
                  <XAxis dataKey="step" stroke="rgba(255,255,255,.5)" fontSize={12}
                    label={{ value: 'walk step (obstacle crossing)', position: 'insideBottom', offset: -4, fill: 'rgba(255,255,255,.4)', fontSize: 11 }} />
                  <Y domain={[1e-16, 0.5]} scale="log" stroke="rgba(255,255,255,.5)" fontSize={11} tickFormatter={(v: number) => v.toExponential(0)} />
                  <Tooltip
                    formatter={(v: number, name: string) => [fmtBer(v), name]}
                    labelFormatter={(l) => `step ${l}`}
                    contentStyle={{ background: '#111827', border: '1px solid rgba(255,255,255,.15)', borderRadius: 8 }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {SERIES.map(s => (
                    <Line key={s.key} type="monotone" dataKey={s.key} name={s.label}
                      stroke={s.color} dot={false} strokeWidth={2} />
                  ))}
                  {events.map((ev, i) => (
                    <ReferenceDot key={i} x={ev.step} y={Math.max(ev.ber_after ?? 1e-12, 1e-16)}
                      r={5} fill="#22d3ee" stroke="#0e7490" />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="grid md:grid-cols-2 gap-4">
              <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                <h3 className="text-sm uppercase tracking-wider text-white/50 mb-2">Blockage-risk predictor (classical)</h3>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={result.steps}>
                      <CartesianGrid stroke="rgba(255,255,255,.08)" />
                      <XAxis dataKey="step" stroke="rgba(255,255,255,.5)" fontSize={11} />
                      <Y domain={[0, 1]} stroke="rgba(255,255,255,.5)" fontSize={11} />
                      <Tooltip contentStyle={{ background: '#111827', border: '1px solid rgba(255,255,255,.15)', borderRadius: 8 }} />
                      <Bar dataKey="blockage_risk" name="risk score" fill="#fbbf24" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                <h3 className="text-sm uppercase tracking-wider text-white/50 mb-2">Agent re-steering events (strategy D)</h3>
                <div className="space-y-2 text-sm max-h-56 overflow-y-auto thin-scroll">
                  {events.length === 0 && <p className="text-white/40">No re-steering required in this run.</p>}
                  {events.map((ev, i) => (
                    <div key={i} className="rounded-lg border border-white/10 px-3 py-2 flex justify-between">
                      <span>step {ev.step}</span>
                      <span className="font-mono text-white/70">
                        {fmtBer(ev.ber_before)} → {fmtBer(ev.ber_after)}
                      </span>
                      <span className="text-cyan-300">re-steered (robust, power {fmtSci(ev.received_power_after_w)} W)</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
        {!result && !busy && <p className="text-white/50">Run the scripted walk to see the four strategies react.</p>}
      </div>
    </Layout>
  )
}
