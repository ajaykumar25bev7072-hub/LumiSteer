import { useEffect, useRef } from 'react'
import type { AgentEvent } from '../types'
import { fmtBer, fmtSci } from '../lib/format'

function renderData(ev: AgentEvent): { title: string; body: React.ReactNode } {
  switch (ev.type) {
    case 'observation': {
      const d = ev.data?.[0] ?? ev.data
      return {
        title: 'observe (telemetry)',
        body: <div className="font-mono text-[12px] space-y-0.5 text-white/80">
          <div>received_power = {fmtSci(d?.received_power_w)} W</div>
          <div>BER = {fmtBer(d?.ber)} · status = {d?.link_status}</div>
          <div>g_los = {fmtSci(d?.g_los)} · g_irs = {fmtSci(d?.g_irs)}</div>
          {d?.obstacle ? <div>obstacle: enabled={String(d.obstacle.enabled)} at ({d.obstacle.center?.x}, {d.obstacle.center?.y})</div> : null}
        </div>,
      }
    }
    case 'assistant_note':
      return { title: 'thought', body: <p className="text-[13px] text-white/85">{ev.data?.text}</p> }
    case 'tool_call':
      return {
        title: `tool call · ${ev.data?.name}`,
        body: <pre className="font-mono text-[11px] whitespace-pre-wrap text-cyan-200/90">{JSON.stringify(ev.data?.args, null, 1)}</pre>,
      }
    case 'tool_result': {
      const r = ev.data?.result
      return {
        title: `tool result · ${ev.data?.name}`,
        body: <div className="font-mono text-[12px] space-y-0.5 text-white/80">
          <div>P_r = {fmtSci(r?.received_power_w)} W · BER = {fmtBer(r?.ber)} · {r?.link_status}</div>
          <div>illuminance = {r?.illuminance_lux?.toFixed?.(1)} lux</div>
          {(r?.mean_ber !== undefined) && <div>mean BER = {fmtBer(r.mean_ber)} · worst = {fmtBer(r.worst_ber)}</div>}
          {r?.result_summary && <div className="text-white/60">{r.result_summary}</div>}
          {r?.error && <div className="text-rose-300">{r.error}</div>}
        </div>,
      }
    }
    case 'final':
      return {
        title: 'final explanation',
        body: <p className="text-[13px] leading-relaxed text-emerald-100">{ev.data?.explanation}</p>,
      }
    case 'api_error':
      return { title: 'API error', body: <p className="text-[12px] text-rose-300 font-mono">{JSON.stringify(ev.data)}</p> }
    case 'cached_notice':
      return { title: 'demo cache', body: <p className="text-[12px] text-amber-200">{ev.data?.text}</p> }
    case 'note':
      return { title: 'note', body: <p className="text-[12px] text-white/70">{ev.data?.text}</p> }
    default:
      return { title: ev.type, body: null }
  }
}

export default function AgentConsole({ events, running }: { events: AgentEvent[]; running: boolean }) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [events.length])
  return (
    <div className="rounded-xl border border-white/10 bg-black/30 p-3 h-full overflow-y-auto thin-scroll min-h-[260px]">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs uppercase tracking-wider text-white/50">Agent console</h3>
        <span className={`text-xs ${running ? 'text-cyan-300 animate-pulse' : 'text-white/40'}`}>
          {running ? 'agent running…' : 'idle'}
        </span>
      </div>
      {events.length === 0 && <p className="text-sm text-white/40">Press “Run agent” to start a live run.</p>}
      <div className="space-y-2">
        {events.map((ev, i) => {
          const { title, body } = renderData(ev)
          return (
            <div key={i} className={`rounded-lg border px-3 py-2 ${ev.cached ? 'border-amber-400/40 bg-amber-400/5' : 'border-white/10 bg-white/5'}`}>
              <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-white/40">
                <span>step {i + 1}</span>
                <span>{title}</span>
                {ev.cached && <span className="ml-auto rounded bg-amber-400/20 text-amber-200 px-1.5 py-0.5">cached replay</span>}
              </div>
              {body && <div className="mt-1">{body}</div>}
            </div>
          )
        })}
      </div>
      <div ref={endRef} />
    </div>
  )
}
