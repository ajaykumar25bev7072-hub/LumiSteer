// Okabe-Ito based perceptual ramp for BER heatmaps (colorblind friendly).
// Maps [0,1] -> color; dark = low BER (good), yellow = poor.
const STOPS: [number, [number, number, number]][] = [
  [0.0, [10, 8, 37]],
  [0.25, [49, 103, 142]],
  [0.5, [85, 198, 103]],
  [0.75, [208, 225, 28]],
  [1.0, [255, 235, 181]],
]

export function ramp(t: number): string {
  t = Math.min(1, Math.max(0, t))
  for (let i = 1; i < STOPS.length; i++) {
    if (t <= STOPS[i][0]) {
      const [t0, c0] = STOPS[i - 1]
      const [t1, c1] = STOPS[i]
      const f = (t - t0) / (t1 - t0)
      const c = c0.map((v, k) => Math.round(v + f * (c1[k] - v)))
      return `rgb(${c[0]},${c[1]},${c[2]})`
    }
  }
  return 'rgb(255,235,181)'
}
