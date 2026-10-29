import type { SimResult } from '../types'
import { fmtBer, fmtPower, fmtIrradiance, fmtSnrDb, fmtLux, statusLabel } from '../lib/format'

function Card({ title, value, sub, accent }: { title: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3 min-h-[86px] flex flex-col">
      <div className="text-[11px] uppercase tracking-wide text-white/50">{title}</div>
      <div className={`mt-1 text-lg font-semibold ${accent ?? ''}`}>{value}</div>
      {sub && <div className="text-[11px] text-white/50 mt-auto">{sub}</div>}
    </div>
  )
}

export default function MetricsCards({ res, config }: { res: SimResult | null; config: unknown }) {
  if (!res) return null
  const statusColor = res.link_status === 'stable' ? 'text-emerald-400'
    : res.link_status === 'degraded' ? 'text-amber-400' : 'text-rose-400'
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-2">
      <Card title="Link status" value={statusLabel(res.link_status)}
        sub={`target BER ${(config as { modulation?: { ber_threshold?: number } })?.modulation?.ber_threshold ?? 1e-3}`}
        accent={statusColor} />
      <Card title="Received power" value={fmtPower(res.received_power_w)}
        sub={`LOS ${fmtPower(res.g_los * res.p_led_w)} · IRS ${fmtPower(res.g_irs * res.p_led_w)}`} />
      <Card title="Irradiance" value={`${(res.irradiance_w_m2).toExponential(2)} W/m²`}
        sub={`at photodiode A = ${(1e4 * 1e-4 / 1e-4).toFixed(1)} cm² · E = P/A`} />
      <Card title="SNR" value={fmtSnrDb(res.snr_db)} sub={`σ² = ${'1.0e'}·noise var`} />
      <Card title="BER" value={fmtBer(res.ber)} sub={`OOK · Q(√SNR)`}
        accent={res.ber !== null && res.ber > (config as { modulation?: { ber_threshold?: number } })?.modulation?.ber_threshold! ? 'text-amber-400' : ''} />
      <Card title="Illuminance" value={fmtLux(res.illuminance_lux)}
        sub={res.illuminance_ok ? 'comfort constraint ok' : 'below minimum illuminance'}
        accent={res.illuminance_ok ? '' : 'text-amber-400'} />
    </div>
  )
}
