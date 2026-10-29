import { useCallback, useEffect, useRef, useState } from 'react'
import Layout from '../components/Layout'
import RoomView from '../components/RoomView'
import ControlPanel from '../components/ControlPanel'
import MetricsCards from '../components/MetricsCards'
import AgentConsole from '../components/AgentConsole'
import { api, runAgentStream } from '../api'
import type { AgentEvent, SimConfig, SimResult, IRSAngles } from '../types'
import { fmtBer } from '../lib/format'

const ZEROS = (n: number): IRSAngles => ({ azimuth_deg: Array(n).fill(0), elevation_deg: Array(n).fill(0) })

export default function SimulatorPage() {
  const [config, setConfig] = useState<SimConfig | null>(null)
  const [result, setResult] = useState<SimResult | null>(null)
  const [angles, setAngles] = useState<IRSAngles | null>(null)
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([])
  const [agentRunning, setAgentRunning] = useState(false)
  const [agentSummary, setAgentSummary] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [optimizing, setOptimizing] = useState<'none' | 'point' | 'robust'>('none')
  const [health, setHealth] = useState<{ llm_configured: boolean; model: string } | null>(null)
  const simToken = useRef(0)

  const patched = useCallback(<K extends keyof SimConfig>(k: K, v: Partial<SimConfig[K]>): void => {
    setConfig(c => c && ({ ...c, [k]: { ...(c[k] as object), ...(v as object) } } as SimConfig))
  }, [])

  useEffect(() => {
    api.health().then(h => setHealth({ llm_configured: h.llm_configured, model: h.model })).catch(() => setHealth({ llm_configured: false, model: 'unreachable' }))
    api.getConfig().then(cfg => {
      setConfig(cfg)
      setAngles(ZEROS(cfg.irs.rows * cfg.irs.cols))
    }).catch(e => setError(String(e)))
  }, [])

  // re-simulate whenever config / angles change (debounced)
  useEffect(() => {
    if (!config) return
    const id = setTimeout(() => {
      const token = ++simToken.current
      const n = config.irs.enabled ? config.irs.rows * config.irs.cols : 1
      const a = angles ? { azimuth_deg: angles.azimuth_deg.slice(0, n), elevation_deg: angles.elevation_deg.slice(0, n) } : ZEROS(n)
      if (a.azimuth_deg.length < n) a.azimuth_deg = a.azimuth_deg.concat(Array(n - a.azimuth_deg.length).fill(0))
      if (a.elevation_deg.length < n) a.elevation_deg = a.elevation_deg.concat(Array(n - a.elevation_deg.length).fill(0))
      api.simulate(config, undefined, a).then(r => {
        if (token === simToken.current) { setResult(r); setError(null) }
      }).catch(e => setError(String(e)))
    }, 120)
    return () => clearTimeout(id)
  }, [config, angles])

  const onReceiverMove = (x: number, y: number): void => {
    setConfig(c => c && ({ ...c, receiver: { ...c.receiver, position: { ...c.receiver.position, x, y } } }))
  }
  const onObstacleMove = (x: number, y: number): void => {
    setConfig(c => c && ({ ...c, obstacle: { ...c.obstacle, center: { ...c.obstacle.center, x, y, z: c.obstacle.center.z } } }))
  }

  const toggleBlock = (): void => {
    setConfig(c => {
      if (!c) return c
      if (!c.obstacle.enabled) {
        // place the person on the LED -> RX line, at the midpoint
        return { ...c, obstacle: { ...c.obstacle, enabled: true,
          center: {
            ...c.obstacle.center,
            x: (c.led.position.x + c.receiver.position.x) / 2,
            y: (c.led.position.y + c.receiver.position.y) / 2,
          } } }
      }
      return { ...c, obstacle: { ...c.obstacle, enabled: false } }
    })
  }

  const jitterReceiver = (): void => {
    setConfig(c => c && ({
      ...c,
      receiver: { ...c.receiver, position: {
        ...c.receiver.position,
        x: Math.min(c.room.width - 0.2, Math.max(0.2, c.receiver.position.x + (Math.random() - 0.5) * 0.8)),
        y: Math.min(c.room.depth - 0.2, Math.max(0.2, c.receiver.position.y + (Math.random() - 0.5) * 0.8)),
      } },
    }))
  }

  const runOptimizer = async (mode: 'point' | 'robust'): Promise<void> => {
    if (!config) return
    setOptimizing(mode)
    try {
      const out = mode === 'point'
        ? await api.optimize(config)
        : await api.robustOptimize(config)
      setAngles(out.angles)
      if (out.optimized_power_w != null) {
        setConfig(c => c && ({ ...c, led: { ...c.led, power_w: out.optimized_power_w! } }))
      }
      setAgentEvents(evts => [...evts, {
        type: 'assistant_note', ts: Date.now(), cached: false, data: {
          iteration: 0,
          text: `Manual ${mode === 'point' ? 'point' : 'robust'} re-optimization applied — new BER ${fmtBer((out.metrics as { ber: number | null }).ber)}`,
        },
      }])
    } catch (e) { setError(String(e)) } finally { setOptimizing('none') }
  }

  const runAgent = async (): Promise<void> => {
    if (!config) return
    setAgentEvents([])
    setAgentSummary(null)
    setAgentRunning(true)
    const note = (result && result.link_status !== 'stable')
      ? `The link is currently ${result.link_status}: received power ${result.received_power_w.toExponential(2)} W, BER ${fmtBer(result.ber)}.`
      : 'Routine check: keep the link stable.'
    try {
      await runAgentStream(config, note, angles ?? undefined, ev => setAgentEvents(prev => [...prev, ev]))
    } catch (e) { setAgentEvents(prev => [...prev, { type: 'api_error', ts: Date.now(), data: { error: String(e) }, cached: true }]) }
    finally { setAgentRunning(false) }
    const last = agentEvents.length === 0 ? null : null
    void last
    // final text is captured via events below
    setAgentEvents(prev => {
      const final = prev.filter(e => e.type === 'final').pop()
      setAgentSummary((final?.data as { explanation?: string })?.explanation ?? null)
      return prev
    })
  }

  const badge = health ? `${health.llm_configured ? 'Nemotron agent: configured' : 'Nemotron agent: no key — demo cache mode'} · ${health.model}` : ''

  if (!config) {
    return <Layout llmBadge={badge}><div className="p-10 text-white/60">{error ?? 'Loading simulator…'}</div></Layout>
  }

  return (
    <Layout llmBadge={badge}>
      <div className="mx-auto max-w-7xl px-4 py-6">
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <h1 className="text-2xl font-semibold mr-auto">Simulator</h1>
          <button onClick={toggleBlock} disabled={agentRunning}
            className="rounded-lg px-4 py-2 border border-white/20 hover:bg-white/10 text-sm">
            {config.obstacle.enabled ? 'Remove blocker' : 'Block the direct path'}
          </button>
          <button onClick={jitterReceiver}
            className="rounded-lg px-4 py-2 border border-white/20 hover:bg-white/10 text-sm">Move receiver (jitter)</button>
          <button onClick={() => runOptimizer('point')} disabled={optimizing !== 'none'}
            className="rounded-lg bg-sky-500/90 hover:bg-sky-400 px-4 py-2 text-sm font-medium text-white">
            {optimizing === 'point' ? 'Optimizing…' : 'Optimize IRS (point)'}
          </button>
          <button onClick={() => runOptimizer('robust')} disabled={optimizing !== 'none'}
            className="rounded-lg bg-sky-700 hover:bg-sky-600 px-4 py-2 text-sm font-medium text-white">
            {optimizing === 'robust' ? 'Optimizing…' : 'Robust IRS (15 cm)'}
          </button>
          <button onClick={runAgent} disabled={agentRunning}
            className="rounded-lg bg-yellow-300 hover:bg-yellow-200 px-4 py-2 text-sm font-semibold text-black">
            {agentRunning ? 'Agent working…' : '▶ Run agent'}
          </button>
        </div>

        {error && <div className="mb-3 rounded-lg bg-rose-500/10 border border-rose-400/40 text-rose-200 px-4 py-2 text-sm">{error}</div>}

        <div className="grid lg:grid-cols-[1fr_340px] gap-6">
          <div className="space-y-4">
            <RoomView config={config} onReceiverMove={onReceiverMove} onObstacleMove={onObstacleMove} />
            <MetricsCards res={result} config={config} />
            <AgentConsole events={agentEvents} running={agentRunning} />
          </div>

          <div className="rounded-xl border border-white/10 bg-white/5 p-4 h-fit">
            <ControlPanel config={config} onChange={(patch) => setConfig(c => c && ({ ...c, ...patch } as SimConfig))} />
            <div className="mt-4 text-[11px] leading-relaxed text-white/40">
              Receiver and blocker are draggable in the top view. Metric refresh is debounced 120 ms.
              <br />
              {agentSummary && <button
                className="rounded border border-white/15 px-2 py-1 mt-2 text-white/60 hover:bg-white/5"
                onClick={() => navigator.clipboard.writeText(agentSummary)}>Copy agent summary</button>}
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}
