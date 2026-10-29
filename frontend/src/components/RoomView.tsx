import type { SimConfig } from '../types'

interface Props {
  config: SimConfig
  onReceiverMove?: (x: number, y: number) => void
  onObstacleMove?: (x: number, y: number) => void
  showBlockedPath?: boolean
}

const SVG_W = 300
const SVG_H = 300

export default function RoomView({ config, onReceiverMove, onObstacleMove }: Props) {
  const { room, led, receiver, obstacle, irs } = config

  const toSvg = (x: number, y: number) => ({ x: (x / room.width) * SVG_W, y: (room.depth - y) / room.depth * SVG_H })

  const ledP = toSvg(led.position.x, led.position.y)
  const rxP = toSvg(receiver.position.x, receiver.position.y)
  const obsP = toSvg(obstacle.center.x, obstacle.center.y)
  const nez = { h: 0.05 * SVG_H }

  // IRS strip along the wall (default: north wall at y=0 => top edge)
  const pix = (room.height > 0 ? room.height : 3) // unused; keep for clarity
  let irsRect: null | { x: number; y: number; w: number; h: number } = null
  if (irs.enabled) {
    const panelLen = Math.sqrt(irs.element_area_m2) * irs.cols
    const panelH = Math.sqrt(irs.element_area_m2) * irs.rows
    const t = 6
    if (irs.wall === 'north') {
      const cx = toSvg(irs.center.x, 0).x
      const verticalScale = t / (room.height * 0.4)
      irsRect = { x: cx - (panelLen / room.width) * SVG_W / 2, y: SVG_H - t, w: (panelLen / room.width) * SVG_W, h: t + verticalScale * panelH }
    }
  }
  const rPx = Math.max(8, (obstacle.radius_m / room.width) * SVG_W)
  const gridCols = irs.enabled ? irs.cols : 0

  const dragRx = (e: React.PointerEvent<SVGCircleElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    const move = (ev: PointerEvent | React.PointerEvent) => {}
    void move
  }

  const handle = (
    which: 'rx' | 'obstacle',
    e: React.PointerEvent<SVGCircleElement>,
  ) => {
    const el = e.currentTarget
    el.setPointerCapture(e.pointerId)
    const svg = el.ownerSVGElement!
    const onMove = (clientX: number, clientY: number) => {
      const rect = svg.getBoundingClientRect()
      const sx = ((clientX - rect.left) / rect.width) * SVG_W
      const sy = ((clientY - rect.top) / rect.height) * SVG_H
      const x = (sx / SVG_W) * room.width
      const y = room.depth - (sy / SVG_H) * room.depth
      const clampedX = Math.min(room.width - 0.05, Math.max(0.05, x))
      const clampedY = Math.min(room.depth - 0.05, Math.max(0.05, y))
      if (which === 'rx') onReceiverMove?.(clampedX, clampedY)
      else onObstacleMove?.(clampedX, clampedY)
    }
    const move = (ev: PointerEvent) => onMove(ev.clientX, ev.clientY)
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    void dragRx
  }

  return (
    <div className="grid grid-cols-2 gap-3">
      <figure>
        <svg viewBox={`0 0 ${SVG_W} ${SVG_H}`} className="w-full rounded-xl border border-white/10 bg-[#0d1424]">
          {/* room */}
          <rect x={2} y={2} width={SVG_W - 4} height={SVG_H - 4} fill="none" stroke="rgba(255,255,255,.2)" rx={6} />
          {/* blockage ray LED -> RX */}
          {obstacle.enabled && (
            <line
              x1={ledP.x} y1={ledP.y} x2={rxP.x} y2={rxP.y}
              stroke="rgba(255,140,90,.5)" strokeDasharray="4 4" strokeWidth={2} />
          )}
          {/* IRS panel */}
          {irsRect && (
            <g>
              <rect x={irsRect.x} y={SVG_H - nez.h - 4} width={irsRect.w} height={nez.h} fill="#38bdf8" opacity={0.9} />
              {Array.from({ length: gridCols }, (_, i) => (
                <line key={i}
                  x1={irsRect.x + (i / gridCols) * irsRect.w} y1={SVG_H - nez.h - 4}
                  x2={irsRect.x + (i / gridCols) * irsRect.w} y2={SVG_H}
                  stroke="#0d1424" strokeWidth={1} />
              ))}
            </g>
          )}
          {/* LED */}
          <circle cx={ledP.x} cy={ledP.y} r={7} fill="#fde047" stroke="#facc15" />
          <circle cx={ledP.x} cy={ledP.y} r={3} fill="#fff7c2" />
          {/* obstacle */}
          {obstacle.enabled && (
            <circle cx={obsP.x} cy={obsP.y} r={rPx} fill="rgba(244,63,94,.55)" stroke="rgba(244,63,94,.9)"
              onPointerDown={(e) => handle('obstacle', e)} style={{ cursor: 'grab' }} />
          )}
          {/* receiver */}
          <circle cx={rxP.x} cy={rxP.y} r={9} fill="#4ade80" stroke="#22c55e" strokeWidth={2}
            onPointerDown={(e) => handle('rx', e)} style={{ cursor: 'grab' }} />
          <text x={rxP.x} y={rxP.y - 14} textAnchor="middle" className="fill-white/70" fontSize={10}>RX</text>
        </svg>
        <figcaption className="text-[11px] text-white/50 mt-1">Top view — drag the green receiver and the red blocker</figcaption>
      </figure>

      <figure>
        <svg viewBox={`0 0 ${SVG_W} ${SVG_H}`} className="w-full rounded-xl border border-white/10 bg-[#0d1424]">
          <rect x={2} y={2} width={SVG_W - 4} height={SVG_H - 4} fill="none" stroke="rgba(255,255,255,.2)" rx={6} />
          {/* side view: x = room width, y = room height (floor at bottom) */}
          {(() => {
            const H = SVG_H
            const ledS = { x: (led.position.x / room.width) * SVG_W, y: H - (led.position.z / room.height) * H }
            const rxS = { x: (receiver.position.x / room.width) * SVG_W, y: H - (receiver.position.z / room.height) * H }
            const obsS = {
              x: (obstacle.center.x / room.width) * SVG_W,
              y: H - ((obstacle.center.z + obstacle.height_m / 2) / room.height) * H,
              h: (obstacle.height_m / room.height) * H,
            }
            return (
              <>
                <line x1={ledS.x} y1={ledS.y} x2={rxS.x} y2={rxS.y}
                  stroke={obstacle.enabled ? 'rgba(255,140,90,.5)' : 'rgba(255,255,255,.25)'}
                  strokeDasharray="4 4" strokeWidth={1.5} />
                {irs.enabled && (
                  <rect x={(irs.wall === 'north' ? 4 : (irs.wall === 'south' ? (0.04) * SVG_W : irs.center.x * 0 + 2))}
                    y={H - (irs.center.z / room.height) * H - 10} width={6} height={20} fill="#38bdf8" />
                )}
                <circle cx={ledS.x} cy={ledS.y} r={7} fill="#fde047" />
                {obstacle.enabled && (
                  <rect x={obsS.x - rPx / 2} y={obsS.y - obsS.h / 2} width={rPx} height={obsS.h} fill="rgba(244,63,94,.55)" />
                )}
                <circle cx={rxS.x} cy={rxS.y} r={8} fill="#4ade80" />
                <text x={8} y={16} className="fill-white/40" fontSize={10}>side</text>
              </>
            )
          })()}
        </svg>
        <figcaption className="text-[11px] text-white/50 mt-1">Side view — ceiling LED, desk receiver, blocker height</figcaption>
      </figure>
    </div>
  )
}
