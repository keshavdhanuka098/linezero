import { useCallback, useEffect, useRef, useState } from 'react'
import { Minus, Plus, Zap } from 'lucide-react'
import { Simulation } from '../lib/simEngine'

/**
 * Hero visualization. This is LineZero's real discrete-event simulation engine (src/lib/simEngine.ts),
 * stepped in the browser with synthetic arrivals. Nothing here is a canned animation.
 */
const SERVICE = 4          // mean service time, minutes
const BASE_RATE = 0.6     // arrivals per minute, normal demand
const SURGE_RATE = 1.0     // arrivals per minute, surge
const SIM_MIN_PER_SEC = 3  // playback speed
const SEED = 20241

const make = (counters: number, rate: number) => {
  const s = new Simulation({ arrivalRate: rate, avgService: SERVICE, counters, duration: 1e7, arrivalCV: 1, serviceCV: 0.6, seed: SEED })
  s.advanceTo(45)
  return s
}

export default function HeroSim() {
  const canvas = useRef<HTMLCanvasElement>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const sim = useRef<Simulation>(make(3, BASE_RATE))
  const [counters, setCounters] = useState(3)
  const [surge, setSurge] = useState(false)
  const [stats, setStats] = useState({ q: 0, wait: 0, util: 0, served: 0 })
  const reduced = useRef(typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches)

  const draw = useCallback(() => {
    const cv = canvas.current, s = sim.current
    if (!cv) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const w = cv.clientWidth, h = cv.clientHeight
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr) }
    const g = cv.getContext('2d')
    if (!g) return
    g.setTransform(dpr, 0, 0, dpr, 0, 0)
    g.clearRect(0, 0, w, h)
    const view = s.view(), n = view.counters.length
    const cW = Math.min(132, w * 0.3), cX = w - cW - 20
    const gap = 10, cH = Math.min(46, (h - 70 - gap * (n - 1)) / n)
    const top = (h - (cH * n + gap * (n - 1))) / 2 + 6
    const cs = getComputedStyle(cv)
    const col = (v: string, f: string) => cs.getPropertyValue(v).trim() || f
    const teal = col('--teal', '#2ad4c3'), violet = col('--violet', '#6f69ff'), amber = col('--amber', '#f3b84b'), warn = col('--warn', '#ff8a4c')
    const line = col('--line2', '#2d3748'), muted = col('--muted', '#8791a4'), panel = col('--panel2', '#151a23')

    // lanes feeding each counter
    const midY = h / 2 + 6
    g.lineWidth = 1.5; g.strokeStyle = line; g.lineCap = 'round'
    for (let i = 0; i < n; i++) {
      const y = top + i * (cH + gap) + cH / 2
      g.beginPath(); g.moveTo(cX - 26, midY); g.bezierCurveTo(cX - 10, midY, cX - 14, y, cX, y); g.stroke()
    }
    // arrivals entry
    g.fillStyle = teal; g.beginPath(); g.arc(20, midY, 4.5, 0, 7); g.fill()
    g.strokeStyle = line; g.beginPath(); g.moveTo(26, midY); g.lineTo(cX - 26, midY); g.stroke()

    // waiting customers
    const rows = 5, step = 13, qRight = cX - 40, maxCols = Math.max(1, Math.floor((qRight - 44) / step))
    const cap = rows * maxCols
    const waits = view.line
    for (let i = 0; i < Math.min(waits.length, cap); i++) {
      const c = Math.floor(i / rows), r = i % rows
      const x = qRight - c * step, y = midY + (r - (rows - 1) / 2) * step
      g.fillStyle = waits[i] > 10 ? warn : waits[i] > 4 ? amber : teal
      g.globalAlpha = 0.95
      g.beginPath(); g.arc(x, y, 4.2, 0, 7); g.fill()
    }
    g.globalAlpha = 1
    if (waits.length > cap) { g.fillStyle = muted; g.font = '500 12px Inter, sans-serif'; g.textAlign = 'left'; g.fillText(`+${waits.length - cap} more`, 44, midY - 44) }

    // counters
    g.font = '500 12px Inter, sans-serif'
    for (let i = 0; i < n; i++) {
      const y = top + i * (cH + gap), c = view.counters[i]
      g.fillStyle = panel; g.strokeStyle = c.busy ? violet : line; g.lineWidth = 1.5
      g.beginPath(); g.roundRect(cX, y, cW, cH, 9); g.fill(); g.stroke()
      if (c.busy) {
        g.save(); g.beginPath(); g.roundRect(cX, y, cW, cH, 9); g.clip()
        g.fillStyle = 'rgba(111,105,255,.28)'; g.fillRect(cX, y, cW * Math.min(1, Math.max(0, c.progress)), cH); g.restore()
      }
      g.fillStyle = c.busy ? '#e8ebf1' : muted; g.textAlign = 'left'; g.textBaseline = 'middle'
      g.fillText(`Counter ${i + 1}`, cX + 12, y + cH / 2 - (cH > 34 ? 7 : 0))
      if (cH > 34) { g.fillStyle = muted; g.fillText(c.busy ? 'serving' : 'idle', cX + 12, y + cH / 2 + 9) }
      g.fillStyle = c.busy ? teal : line; g.beginPath(); g.arc(cX + cW - 14, y + cH / 2, 4, 0, 7); g.fill()
    }
    g.textBaseline = 'alphabetic'; g.fillStyle = muted; g.textAlign = 'left'
    g.fillText('Arrivals', 10, h - 14); g.fillText('Waiting line', Math.max(86, (qRight - 60) / 2), h - 14); g.fillText('Counters', cX, h - 14)
  }, [])

  const publish = useCallback(() => {
    const m = sim.current.metrics(), v = sim.current.view()
    setStats({ q: m.queueLength, wait: v.line[0] ?? 0, util: m.inService / Math.max(1, v.counters.length), served: m.served })
  }, [])

  // playback loop: paused when off-screen or tab hidden, static when reduced motion is requested
  useEffect(() => {
    let raf = 0, last = 0, visible = true, acc = 0
    const frame = (t: number) => {
      raf = 0
      if (!visible || document.hidden) { last = 0; return }
      if (last) { const dt = Math.min(0.1, (t - last) / 1000); sim.current.advanceTo(sim.current.t + dt * SIM_MIN_PER_SEC); acc += dt; draw(); if (acc > 0.25) { acc = 0; publish() } }
      last = t
      raf = requestAnimationFrame(frame)
    }
    const kick = () => { if (!raf && !reduced.current) raf = requestAnimationFrame(frame) }
    draw(); publish()
    const io = new IntersectionObserver(e => { visible = e[0]?.isIntersecting ?? true; if (visible) kick() }, { threshold: 0.05 })
    if (wrap.current) io.observe(wrap.current)
    const ro = new ResizeObserver(() => draw()); if (wrap.current) ro.observe(wrap.current)
    document.addEventListener('visibilitychange', kick)
    kick()
    return () => { io.disconnect(); ro.disconnect(); document.removeEventListener('visibilitychange', kick); if (raf) cancelAnimationFrame(raf) }
  }, [draw, publish])

  const setCount = (n: number) => {
    const c = Math.max(2, Math.min(5, n)); setCounters(c)
    sim.current = make(c, surge ? SURGE_RATE : BASE_RATE); draw(); publish()
  }
  const toggleSurge = () => {
    const next = !surge; setSurge(next)
    sim.current.p.arrivalRate = next ? SURGE_RATE : BASE_RATE
    if (reduced.current) { sim.current.advanceTo(sim.current.t + 40) } ; draw(); publish()
  }

  const rate = surge ? SURGE_RATE : BASE_RATE
  const load = (rate * SERVICE) / counters
  const state = load >= 1 ? 'over' : load >= 0.85 ? 'tight' : 'ok'
  return (
    <div className="hs" ref={wrap}>
      <div className="hs-head">
        <div><b>Live queue simulation</b><span>LineZero’s simulation engine, running in your browser</span></div>
        <span className={`hs-state ${state}`}>{state === 'over' ? 'Over capacity' : state === 'tight' ? 'Near capacity' : 'Healthy'}</span>
      </div>
      <div className="hs-canvas"><canvas ref={canvas} aria-label="Animated queue: customers arrive, wait in line and are served at counters" role="img" /></div>
      <dl className="hs-stats">
        <div><dt>In line</dt><dd>{stats.q}</dd></div>
        <div><dt>Longest wait</dt><dd>{stats.wait.toFixed(1)}<small> min</small></dd></div>
        <div><dt>Counters busy</dt><dd>{Math.round(stats.util * 100)}<small>%</small></dd></div>
        <div><dt>Load ratio</dt><dd className={`l-${state}`}>{load.toFixed(2)}</dd></div>
      </dl>
      <div className="hs-ctl">
        <div className="hs-step" role="group" aria-label="Counters">
          <button onClick={() => setCount(counters - 1)} disabled={counters <= 2} aria-label="Remove a counter"><Minus size={14} /></button>
          <span>{counters} counters</span>
          <button onClick={() => setCount(counters + 1)} disabled={counters >= 5} aria-label="Add a counter"><Plus size={14} /></button>
        </div>
        <button className={`hs-surge ${surge ? 'on' : ''}`} onClick={toggleSurge} aria-pressed={surge}><Zap size={14} />{surge ? 'Surge on' : 'Simulate a demand surge'}</button>
      </div>
      <p className="hs-note">Synthetic arrivals · mean service {SERVICE} min · {rate} arrivals/min. Try adding a counter during a surge.</p>
    </div>
  )
}
