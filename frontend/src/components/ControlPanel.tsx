import type { SimConfig } from '../types'

interface Props {
  config: SimConfig
  onChange: (patch: Partial<SimConfig>) => void
  actions?: React.ReactNode
}

function Slider({ label, value, min, max, step, unit, onChange }: {
  label: string; value: number; min: number; max: number; step: number; unit?: string
  onChange: (v: number) => void
}) {
  return (
    <label className="block text-sm">
      <div className="flex justify-between text-white/70">
        <span>{label}</span>
        <span className="font-mono text-white">{step < 1 ? value.toFixed(2) : Math.round(value)}{unit}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-full accent-blue-400" />
    </label>
  )
}

export default function ControlPanel({ config, onChange, actions }: Props) {
  const set = (path: string[], _v: number | string | boolean) => {
    // handled inline by section patches below
    void set
  }
  void set

  return (
    <div className="space-y-5">
      <section className="space-y-3">
        <h3 className="text-xs uppercase tracking-wider text-white/50">LED</h3>
        <Slider label="LED power" unit=" W" value={config.led.power_w} min={0.1} max={config.led.max_power_w} step={0.05}
          onChange={v => onChange({ led: { ...config.led, power_w: v } })} />
        <Slider label="Half-power semi-angle" unit="°" value={config.led.half_angle_deg} min={10} max={80} step={5}
          onChange={v => onChange({ led: { ...config.led, half_angle_deg: v } })} />
        <Slider label="LED x position" unit=" m" value={config.led.position.x} min={0.3} max={config.room.width - 0.3} step={0.1}
          onChange={v => onChange({ led: { ...config.led, position: { ...config.led.position, x: v } } })} />
      </section>

      <section className="space-y-3">
        <h3 className="text-xs uppercase tracking-wider text-white/50">Environment</h3>
        <label className="block text-sm">
          <div className="flex justify-between text-white/70"><span>Ambient light</span></div>
          <select value={config.noise.ambient_class}
            onChange={e => onChange({ noise: { ...config.noise, ambient_class: e.target.value as 'low' | 'medium' | 'high' } })}
            className="w-full mt-1 rounded-lg bg-white/10 border border-white/15 px-2 py-1.5 text-white">
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
          <div className="text-[11px] text-white/40">
            maps to background optical power at the receiver: low 1e-4 W · medium 1e-3 W · high 1e-2 W
          </div>
        </label>
        <label className="block text-sm">
          <div className="flex justify-between text-white/70"><span>Obstacle</span></div>
          <select value={config.obstacle.enabled ? 'on' : 'off'}
            onChange={e => onChange({ obstacle: { ...config.obstacle, enabled: e.target.value === 'on' } })}
            className="w-full mt-1 rounded-lg bg-white/10 border border-white/15 px-2 py-1.5 text-white">
            <option value="off">Off</option>
            <option value="on">Person on floor</option>
          </select>
        </label>
        {config.obstacle.enabled && (
          <>
            <Slider label="Blocker radius" unit=" m" value={config.obstacle.radius_m} min={0.1} max={0.6} step={0.05}
              onChange={v => onChange({ obstacle: { ...config.obstacle, radius_m: v } })} />
            <Slider label="Blocker height" unit=" m" value={config.obstacle.height_m} min={0.5} max={2.9} step={0.1}
              onChange={v => onChange({ obstacle: { ...config.obstacle, height_m: v } })} />
          </>
        )}
      </section>

      <section className="space-y-3">
        <h3 className="text-xs uppercase tracking-wider text-white/50">Receiver</h3>
        <Slider label="Receiver height" unit=" m" value={config.receiver.position.z} min={config.receiver.height_min_m} max={config.receiver.height_max_m} step={0.05}
          onChange={v => onChange({ receiver: { ...config.receiver, position: { ...config.receiver.position, z: v } } })} />
        <Slider label="Photodiode area" unit=" cm²" value={config.receiver.photodiode.area_m2 * 1e4} min={0.2} max={4} step={0.1}
          onChange={v => onChange({ receiver: { ...config.receiver, photodiode: { ...config.receiver.photodiode, area_m2: v / 1e4 } } })} />
        <Slider label="Field of view (semi-angle)" unit="°" value={config.receiver.photodiode.fov_deg} min={20} max={90} step={5}
          onChange={v => onChange({ receiver: { ...config.receiver, photodiode: { ...config.receiver.photodiode, fov_deg: v } } })} />
      </section>

      <section className="space-y-3">
        <h3 className="text-xs uppercase tracking-wider text-white/50">IRS</h3>
        <Slider label="Panel size (rows = cols)" unit="×.." value={config.irs.rows} min={2} max={16} step={2}
          onChange={v => onChange({ irs: { ...config.irs, rows: v, cols: v } })} />
        <Slider label="Element area" unit=" cm²" value={config.irs.element_area_m2 * 1e4} min={1} max={25} step={1}
          onChange={v => onChange({ irs: { ...config.irs, element_area_m2: v / 1e4 } })} />
        <Slider label="Beam sigma (alignment)" unit="°" value={config.irs.sigma_deg} min={2} max={15} step={1}
          onChange={v => onChange({ irs: { ...config.irs, sigma_deg: v } })} />
      </section>

      <section className="space-y-3">
        <h3 className="text-xs uppercase tracking-wider text-white/50">Link</h3>
        <label className="block text-sm">
          <div className="flex justify-between text-white/70"><span>Modulation</span></div>
          <select value="ook" disabled className="w-full mt-1 rounded-lg bg-white/10 border border-white/15 px-2 py-1.5 text-white/70">
            <option value="ook">OOK</option>
          </select>
          <div className="text-[11px] text-white/40">PAM-ready backend: the BER function is modular</div>
        </label>
        <Slider label="BER target" value={Math.log10(config.modulation.ber_threshold)} min={-8} max={-1} step={1}
          onChange={v => onChange({ modulation: { ...config.modulation, ber_threshold: Math.pow(10, v) } })} />
        <div className="text-[11px] text-white/40 font-mono">BER target = {config.modulation.ber_threshold.toExponential(0)}</div>
      </section>

      {actions}
    </div>
  )
}
