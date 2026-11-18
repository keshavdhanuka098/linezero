import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { SPLASH_FADE_MS, SPLASH_MS, finishSplash } from './splashGate'
import './splash.css'

/** Count 0 → 100 over `ms`, easing out so it settles gently on 100. */
function useCounter(ms: number, enabled: boolean) {
  const [n, setN] = useState(enabled ? 0 : 100)
  useEffect(() => {
    if (!enabled) { setN(100); return }
    let raf = 0
    const t0 = performance.now()
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / ms)
      setN(Math.round((1 - Math.pow(1 - p, 3)) * 100))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [ms, enabled])
  return n
}

const STAGES = ['Connecting systems', 'Analysing flow', 'Calibrating intelligence']

export default function Splash({ onDone }: { onDone: () => void }) {
  const reduce = useRef(typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches).current
  const total = reduce ? 1800 : SPLASH_MS
  const [leaving, setLeaving] = useState(false)
  const [stage, setStage] = useState(0)
  const n = useCounter(total - SPLASH_FADE_MS - 250, !reduce)
  const doneRef = useRef(onDone)
  doneRef.current = onDone

  useEffect(() => {
    document.documentElement.classList.add('lz-splash-on')
    const seg = (total - SPLASH_FADE_MS) / STAGES.length
    const timers = [
      window.setTimeout(() => setStage(1), seg),
      window.setTimeout(() => setStage(2), seg * 2),
      window.setTimeout(() => { setLeaving(true); finishSplash(); document.documentElement.classList.remove('lz-splash-on') }, total - SPLASH_FADE_MS),
      window.setTimeout(() => doneRef.current(), total),
    ]
    return () => { timers.forEach(clearTimeout); document.documentElement.classList.remove('lz-splash-on') }
  }, [total])

  return (
    <div className={`lzs${leaving ? ' out' : ''}${reduce ? ' rm' : ''}`} role="status" aria-live="polite" aria-label="Loading LineZero">
      <div className="lzs-glow" aria-hidden="true" />
      <div className="lzs-grain" aria-hidden="true" />
      <i className="lzs-c tl" aria-hidden="true" /><i className="lzs-c tr" aria-hidden="true" />
      <i className="lzs-c bl" aria-hidden="true" /><i className="lzs-c br" aria-hidden="true" />

      <div className="lzs-core">
        <svg className="lzs-mark" viewBox="0 0 64 64" aria-hidden="true">
          <path className="lzs-p" pathLength="1" d="M4 18h12c7 0 9 7 12 11" stroke="#20D6C5" strokeWidth="3.5" fill="none" strokeLinecap="round" />
          <path className="lzs-p" pathLength="1" d="M4 32h18" stroke="#20D6C5" strokeWidth="3.5" fill="none" strokeLinecap="round" />
          <path className="lzs-p" pathLength="1" d="M4 46h12c7 0 9-7 12-11" stroke="#20D6C5" strokeWidth="3.5" fill="none" strokeLinecap="round" />
          <ellipse className="lzs-e" cx="43" cy="32" rx="12" ry="15" stroke="#6B65FF" strokeWidth="5" fill="none" />
        </svg>

        <p className="lzs-word" aria-label="LineZero">
          {'LINEZERO'.split('').map((ch, i) => (
            <span key={i} aria-hidden="true" style={{ '--d': `${0.9 + i * 0.07}s` } as CSSProperties}>{ch}</span>
          ))}
        </p>

        <div className="lzs-rule" aria-hidden="true" />
        <p className="lzs-tag">Intelligent queue operations</p>
      </div>

      <div className="lzs-foot">
        <div className="lzs-stage" aria-hidden="true"><span key={stage}>{STAGES[stage]}</span></div>
        <div className="lzs-track" aria-hidden="true"><i style={{ transform: `scaleX(${n / 100})` }} /></div>
        <div className="lzs-pct" aria-hidden="true">{String(n).padStart(3, '0')}</div>
      </div>
    </div>
  )
}
