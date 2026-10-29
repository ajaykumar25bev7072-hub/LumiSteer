import { useState } from 'react'
import * as Recharts from 'recharts'
import Layout from '../components/Layout'
import Heatmap from '../components/Heatmap'
import { api } from '../api'
import type { SimConfig, ComparisonResult } from '../types'
import { fmtPower } from '../lib/format'

const STRATEGY_ORDER = ['A_no_irs', 'B_random', 'C_fixed_point', 'D_robust'] as const

function download(name: string, text: string, mime = 'text/csv'): void {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = name; a.click()
  URL.revokeObjectURL(url)
}

export default function ComparisonPage() {
  const [cfg, setCfg] = useState<SimConfig | null>(null)
  const [scenario, setScenario] = useState<'static' | 'moving' | 'blockage'>('static')
  const [result, setResult] = useState<ComparisonResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const exportCsv = (): void => {
    if (!result) return
    const header = 'strategy,outage_probability,mean_ber,worst_ber,mean_power_W,mean_irradiance_W_m2'
    const rows = STRATEGY_ORDER.map(k => {
      const s = result.strategies[k]
      const a = s.aggregates
      return `${s.label},${s.heatmap.outage_probability},${a.mean_ber ?? ''},${a.worst_ber ?? ''},${a.mean_power_w ?? ''},${a.mean_irradiance_w_m2 ?? ''}`
    })
    download(`lumisteer-comparison-${scenario}.csv`, [header].concat(rows).join('\n'))
  }

  const run = async (): Promise<void> => {
    setBusy(true); setError(null)
    try {
      const config = cfg ?? await api.getConfig()
      setCfg(config)
      setResult(await api.compare(config, scenario, 24))
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  const bars = result
    ? STRATEGY_ORDER.map(k => {
        const a = result.strategies[k]?.aggregates
        return {
          strategy: result.strategies[k].label.split(' — ')[0],
          outage: result.strategies[k].heatmap.outage_probability,
          meanPower: a ? a.mean_power_w * 1e6 : 0,
          meanBerUm: a?.mean_ber ?? 0,
          worstBer: a?.worst_ber ?? 0,
          meanIrr: a ? a.mean_irradiance_w_m2 : 0,
        }
      })
    : []

  return (
    <Layout>
      <div className="mx-auto max-w-7xl px-4 py-6">
        <div className="flex flex-wrap items-center gap-3 mb-5">
          <h1 className="text-2xl font-semibold mr-auto">Strategy comparison</h1>
          <select value={scenario} onChange={e => setScenario(e.target.value as typeof scenario)}
            className="rounded-lg bg-white/10 border border-white/15 px-3 py-2 text-sm">
            <option value="static">Static receiver (full-room sweep)</option>
            <option value="moving">Moving receiver path</option>
            <option value="blockage">Blockage event (person on LOS)</option>
          </select>
          <button onClick={run} disabled={busy}
            className="rounded-lg bg-yellow-300 hover:bg-yellow-200 disabled:opacity-50 px-4 py-2 text-sm font-semibold text-black">
            {busy ? 'Running 4-strategy simulation…' : 'Run comparison'}
          </button>
          {result && <button onClick={exportCsv} className="rounded-lg border border-white/20 px-3 py-2 text-sm hover:bg-white/10">Export CSV</button>}
          {result && <button onClick={async () => {
            const config = cfg ?? await api.getConfig()
            api.exportReport(config, result, null).then(md => download('lumisteer-report.md', md, 'text/markdown'))
          }} className="rounded-lg border border-white/20 px-3 py-2 text-sm hover:bg-white/10">Report (MD)</button>}
        </div>

        {error && <div className="mb-3 rounded-lg bg-rose-500/10 border border-rose-400/40 text-rose-200 px-4 py-2 text-sm">{error}</div>}

        {!result && !busy && (
          <p className="text-white/50">Pick a scenario and run the comparison — four IRS strategies
            (no IRS / random / fixed-point / agent-robust) are simulated on identical geometry.</p>
        )}
        {busy && <p className="text-white/50 animate-pulse">Optimizing IRS configurations and sweeping the room…</p>}

        {result && (
          <div className="space-y-8">
            <section>
              <h2 className="text-sm uppercase tracking-wider text-white/50 mb-2">BER heatmaps · {result.scenario}</h2>
              <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-4">
                {STRATEGY_ORDER.map(k => {
                  const s = result.strategies[k]
                  return (
                    <div key={k} className="rounded-xl border border-white/10 bg-white/5 p-3">
                      <div className="text-sm font-medium mb-1">{s.label}</div>
                      <Heatmap sweep={s.heatmap} />
                      <div className="mt-2 text-[11px] text-white/50 flex justify-between">
                        <span>outage {(s.heatmap.outage_probability * 100).toFixed(1)}%</span>
                        <span>mean P {fmtPower(s.heatmap.mean_power_w)}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>

            <section>
              <h2 className="text-sm uppercase tracking-wider text-white/50 mb-2">Outage probability</h2>
              <div className="rounded-xl border border-white/10 bg-white/5 p-4 h-64">
                {bars.length > 0 && (
                  <ResponsiveBars data={bars} />
                )}
              </div>
            </section>
          </div>
        )}
      </div>
    </Layout>
  )
}

function ResponsiveBars({ data }: { data: Record<string, number | string>[] }) {
  const { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } = Recharts
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data}>
        <CartesianGrid stroke="rgba(255,255,255,.08)" />
        <XAxis dataKey="strategy" stroke="rgba(255,255,255,.5)" fontSize={12} />
        <YAxis stroke="rgba(255,255,255,.5)" fontSize={12} tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} />
        <Tooltip formatter={(v: number) => `${(v * 100).toFixed(1)}%`} contentStyle={{ background: '#111827', border: '1px solid rgba(255,255,255,.15)', borderRadius: 8 }} />
        <Bar dataKey="outage" fill="#38bdf8" radius={[6, 6, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}
