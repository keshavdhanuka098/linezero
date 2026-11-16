import { useEffect, useState } from 'react'
import type { CounterView, Dot, SceneCounter } from '../../lib/twinPlayback'

const PER_ROW = 12, GAP = 24, X0 = 96, Y0 = 34
const slotXY = (slot: number) => ({ x: X0 + (slot % PER_ROW) * GAP, y: Y0 + Math.floor(slot / PER_ROW) * GAP })
const DOOR = { x: 26, y: 70 }

function DotView({ x, y, cls, ms }: { x: number; y: number; cls: string; ms: number }) {
  const [entered, setEntered] = useState(false)
  useEffect(() => { const r = requestAnimationFrame(() => setEntered(true)); return () => cancelAnimationFrame(r) }, [])
  const p = entered ? { x, y } : DOOR
  return <g className="dot" style={{ transform: `translate(${p.x}px, ${p.y}px)`, transitionDuration: `${ms}ms` }}><circle r={8} className={cls} /></g>
}

export interface FloorProps {
  counters: SceneCounter[]
  dots: Dot[]
  overflow: number
  waiting: number
  /** shown under each busy counter, e.g. the token being served */
  label?: (c: SceneCounter) => string
  transitionMs?: number
  title?: string
}

const STATE_TEXT: Record<CounterView, string> = { idle: 'idle', busy: 'serving', failed: 'failed', closed: 'closed' }

/** Animated floor plan: arrivals enter at the door, wait in the lane, and move to a counter when service starts. */
export default function FloorView({ counters, dots, overflow, waiting, label, transitionMs = 250, title = 'Queue floor view' }: FloorProps) {
  const n = counters.length
  const rowH = n > 12 ? 30 : 56
  const height = Math.max(150, 30 + n * rowH)
  const cx = 560
  return (
    <div className="floor">
      <svg viewBox={`0 0 760 ${height}`} role="img" aria-label={`${title}: ${waiting} waiting, ${counters.filter(c => c.state === 'busy').length} of ${n} counters serving`}>
        <rect x={X0 - 18} y={Y0 - 20} width={PER_ROW * GAP + 14} height={Math.max(3, Math.ceil(Math.max(dots.length, 1) / PER_ROW)) * GAP + 10} rx={10} className="lane" />
        <text x={DOOR.x - 14} y={DOOR.y + 28}>Arrivals</text>
        <path d={`M ${DOOR.x - 14} ${DOOR.y - 20} v 40`} stroke="#33405f" strokeWidth={3} />
        <text x={X0 - 8} y={Y0 + 3 * GAP + 18}>{waiting} waiting{overflow > 0 ? ` (showing ${dots.length}, +${overflow} more)` : ''}</text>
        {dots.map(d => { const p = slotXY(d.slot); return <DotView key={d.id} x={p.x} y={p.y} cls="dw" ms={transitionMs} /> })}
        {counters.map((c, i) => {
          const y = 14 + i * rowH
          return (
            <g key={c.index}>
              <rect x={cx} y={y} width={176} height={rowH - 8} rx={10} className={`ctr ${c.state}`} />
              <text x={cx + 12} y={y + (rowH - 8) / 2 - (n > 12 ? 0 : 3)} className="cl">{c.name}</text>
              {n <= 12 && <text x={cx + 12} y={y + (rowH - 8) / 2 + 13}>{STATE_TEXT[c.state]}{label && c.state === 'busy' ? ` · ${label(c)}` : ''}</text>}
              {c.state === 'busy' && c.servingId !== null && <DotView key={c.servingId} x={cx + 150} y={y + (rowH - 8) / 2} cls="ds" ms={transitionMs} />}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
