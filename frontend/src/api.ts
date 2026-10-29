import type {
  AgentEvent, ComparisonResult, OptimizationResult, SimConfig, SimResult,
  SweepResult, TimelineResult, IRSAngles,
} from './types'

// During dev, Vite proxies /api to the FastAPI backend.
// In production set VITE_API_BASE to the backend URL (e.g. on Render/Railway).
const API_BASE: string = import.meta.env.VITE_API_BASE || ''

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = j.detail ?? JSON.stringify(j)
    } catch { /* ignore */ }
    throw new Error(`POST ${path} failed: ${detail}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => fetch(`${API_BASE}/api/health`).then(r => r.json()) as Promise<{ status: string; llm_configured: boolean; model: string }>,
  getConfig: () => fetch(`${API_BASE}/api/config`).then(r => r.json()) as Promise<SimConfig>,
  simulate: (cfg: SimConfig, rx?: number[], angles?: IRSAngles) =>
    post<SimResult>('/api/simulate', { ...cfg, rx_position: rx, irs_angles: angles }),
  sweep: (cfg: SimConfig, resolution = 40, angles?: IRSAngles) =>
    post<SweepResult>('/api/sweep', { ...cfg, resolution, irs_angles: angles }),
  optimize: (cfg: SimConfig, rx?: number[]) =>
    post<OptimizationResult>('/api/optimize', { ...cfg, rx_position: rx }),
  robustOptimize: (cfg: SimConfig, rx?: number[], radiusM = 0.15, nSamples = 10) =>
    post<OptimizationResult>('/api/robust-optimize', { ...cfg, rx_position: rx, radius_m: radiusM, n_samples: nSamples }),
  compare: (cfg: SimConfig, scenario: 'static' | 'moving' | 'blockage', heatmapResolution = 24) =>
    post<ComparisonResult>('/api/compare', { ...cfg, scenario, heatmap_resolution: heatmapResolution }),
  timeline: (cfg: SimConfig) => post<TimelineResult>('/api/timeline', { ...cfg }),
  exportReport: (cfg: SimConfig, comparison: unknown, agentSummary: string | null) =>
    post<string>('/api/export/report', { ...cfg, comparison, agent_summary: agentSummary }),
}

/** Stream the agent run as SSE events. */
export async function runAgentStream(
  cfg: SimConfig,
  scenarioNote: string,
  angles: IRSAngles | undefined,
  onEvent: (ev: AgentEvent) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/agent/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...cfg, scenario_note: scenarioNote, irs_angles: angles }),
  })
  if (!res.ok || !res.body) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* ignore */ }
    throw new Error(`agent run failed: ${detail}`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      for (const line of chunk.split('\n')) {
        if (line.startsWith('data: ')) {
          try { onEvent(JSON.parse(line.slice(6))) } catch { /* skip malformed */ }
        }
      }
    }
  }
}
