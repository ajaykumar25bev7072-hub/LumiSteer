export function fmtBer(ber: number | null): string {
  if (ber === null || ber === undefined) return '< 1e-18'
  if (ber >= 0.01) return ber.toFixed(3)
  return ber.toExponential(2)
}

export function fmtPower(w: number): string {
  if (w >= 1) return `${w.toFixed(2)} W`
  return `${(w * 1e6).toFixed(1)} µW`
}

export function fmtIrradiance(wm2: number): string {
  // show in W/m² with sensible scaling
  if (wm2 >= 0.01) return `${wm2.toFixed(3)} W/m²`
  return `${(wm2 * 100).toFixed(1)} mW/100cm² — ${(wm2).toExponential(2)} W/m²`
}

export function fmtSnrDb(db: number): string {
  if (!isFinite(db)) return '−∞ dB'
  return `${db.toFixed(1)} dB`
}

export function fmtSci(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return '—'
  if (v === 0) return '0'
  return v.toExponential(digits)
}

export function fmtLux(v: number): string {
  return `${v.toFixed(0)} lux`
}

const STATUS_LABEL: Record<string, string> = { stable: 'Stable', degraded: 'Degraded', outage: 'Outage' }
export const statusLabel = (s: string) => STATUS_LABEL[s] ?? s
