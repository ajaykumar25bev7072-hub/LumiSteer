import { useMemo } from 'react'
import type { SweepResult } from '../types'
import { ramp } from '../lib/viridis'

/** Colorblind-safe BER heatmap (log color scale), rendered as SVG quads. */
export default function Heatmap({ sweep, width = 320, height = 300 }: { sweep: SweepResult; width?: number; height?: number }) {
  const cells = useMemo(() => {
    const xs = sweep.x, ys = sweep.y
    // log scale from 1e-8 .. 0.5
    const lo = Math.log10(1e-8), hi = Math.log10(0.5)
    const out: { x: number; y: number; w: number; h: number; t: number }[] = []
    for (let j = 0; j < ys.length - 1; j++) {
      const row = sweep.ber[j]
      const row2 = sweep.ber[j + 1]
      void row2
      for (let i = 0; i < xs.length - 1; i++) {
        const ber = row[i] ?? null
        const t = ber === null ? 0.0
          : (Math.log10(Math.max(ber, 1e-8)) - lo) / (hi - lo)
        out.push({
          x: (xs[i] / xs[xs.length - 1]) * width,
          y: ((1 - ys[j] / ys[ys.length - 1]) * height),
          w: ((xs[i + 1] - xs[i]) / xs[xs.length - 1]) * width,
          h: ((ys[j + 1] - ys[j]) / ys[ys.length - 1]) * height,
          t,
        })
      }
    }
    return out
  }, [sweep, width, height])

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full rounded-lg">
        <rect width={width} height={height} fill="rgba(0,0,0,.35)" />
        {cells.map((c, i) => (
          <rect key={i} x={c.x} y={height - c.y - c.h} width={c.w + 0.6} height={c.h + 0.6} fill={ramp(c.t)} />
        ))}
      </svg>
      <div className="flex items-center gap-2 mt-1 text-[10px] text-white/50">
        <span>BER 1e-8</span>
        <div className="flex flex-1 h-2 rounded overflow-hidden">
          {Array.from({ length: 24 }, (_, i) => (
            <div key={i} style={{ background: ramp(i / 23), flex: 1 }} />
          ))}
        </div>
        <span>0.5 (outage)</span>
      </div>
    </div>
  )
}
