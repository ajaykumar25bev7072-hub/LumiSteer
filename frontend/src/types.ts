// Shared types: mirror of the backend Pydantic models (constitutive subset).

export interface Vec3 { x: number; y: number; z: number }

export interface Room { width: number; depth: number; height: number }

export interface LEDConfig {
  position: Vec3
  downward: boolean
  max_power_w: number
  power_w: number
  dim_min_fraction: number
  half_angle_deg: number
}

export interface Photodiode {
  area_m2: number
  responsivity: number
  fov_deg: number
  filter_gain: number
  concentrator_enabled: boolean
  concentrator_fov_deg: number
  concentrator_refractive_index: number
}

export interface Receiver { position: Vec3; height_min_m: number; height_max_m: number; photodiode: Photodiode }

export interface IRSConfig {
  enabled: boolean
  rows: number
  cols: number
  element_area_m2: number
  reflectivity: number
  sigma_deg: number
  wall: 'north' | 'south' | 'east' | 'west'
  center: Vec3
  azimuth_range_deg: [number, number]
  elevation_range_deg: [number, number]
}

export interface Obstacle {
  enabled: boolean
  shape: 'circle' | 'box'
  center: Vec3
  radius_m: number
  box_semi_x: number
  box_semi_y: number
  height_m: number
  attenuation: number
}

export interface NoiseCfg {
  bandwidth_hz: number
  ambient_class: 'low' | 'medium' | 'high'
  p_ambient_w: number | null
  load_resistance_ohm: number
  temperature_k: number
}

export interface Modulation { scheme: 'ook'; ber_threshold: number }
export interface Illumination { min_lux: number; max_lux: number; luminous_efficacy: number }

export interface SimConfig {
  room: Room
  led: LEDConfig
  receiver: Receiver
  irs: IRSConfig
  obstacle: Obstacle
  noise: NoiseCfg
  modulation: Modulation
  illumination: Illumination
}

export interface IRSAngles { azimuth_deg: number[]; elevation_deg: number[] }

export interface SimResult {
  received_power_w: number
  irradiance_w_m2: number
  illuminance_lux: number
  illuminance_led_lux?: number
  illuminance_ok: boolean
  snr: number
  snr_db: number
  ber: number | null
  g_los: number
  g_irs: number
  total_gain: number
  p_led_w: number
  link_status: 'stable' | 'degraded' | 'outage'
  los_block_factor: number
  irs_block_factor: number
  noise_std: number
}

export interface SweepResult {
  resolution: number
  x: number[]
  y: number[]
  ber: (number | null)[][]
  received_power_w: number[][]
  irradiance_w_m2: number[][]
  outage_probability: number
  mean_ber: number | null
  worst_ber: number | null
  mean_power_w: number
  mean_irradiance_w_m2: number
  outage_positions: number
}

export interface OptimizationResult {
  angles: IRSAngles
  metrics: SimResult & Record<string, unknown>
  radius_m?: number
  n_samples?: number
  mean_ber?: number | null
  worst_ber?: number | null
  mean_power_w?: number
  worst_power_w?: number
  mean_irradiance_w_m2?: number
  optimized_power_w?: number
  power_optimized?: boolean
}

export interface AgentEvent {
  type: 'observation' | 'assistant_note' | 'tool_call' | 'tool_result'
    | 'final' | 'api_error' | 'note' | 'cached_notice' | 'done' | 'fallback_to_cache'
  ts: number | null
  data?: any
  cached?: boolean
}

export interface StrategyAggregate {
  outage_probability: number
  mean_ber: number | null
  worst_ber: number | null
  mean_power_w: number
  mean_irradiance_w_m2: number
}

export interface ComparisonStrategy {
  key: string
  label: string
  aggregates: StrategyAggregate
  heatmap: SweepResult
  path_metrics?: unknown[] | null
  reoptimize_events?: unknown[] | null
  nominal_point?: unknown
  azimuth_deg: number[]
  elevation_deg: number[]
}

export interface ComparisonResult {
  scenario: 'static' | 'moving' | 'blockage'
  strategies: Record<string, ComparisonStrategy>
  receiver_position: number[]
  path: number[][] | null
}

export interface TimelineStep {
  step: number
  obstacle_x: number
  obstacle_y: number
  blockage_risk: number
  ber_A_no_irs: number | null
  ber_B_random: number | null
  ber_C_fixed_point: number | null
  ber_D_robust: number | null
  status_D_robust?: string
}

export interface TimelineResult {
  steps: TimelineStep[]
  reoptimize_events: { step: number; ber_before: number | null; ber_after: number | null; received_power_after_w: number }[]
  obstacle_path: { x: number[]; y: number }
}
