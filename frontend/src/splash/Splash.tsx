import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { SPLASH_FADE_MS, SPLASH_MS, finishSplash } from './splashGate'
import './splash.css'

const STAGES = ['Connecting systems', 'Analysing flow', 'Calibrating intelligence', 'Ready']
const stageOf = (n: number) => (n >= 100 ? 3 : n >= 67 ? 2 : n >= 34 ? 1 : 0)
const ease = (p: number) => 0.5 - Math.cos(Math.PI * p) / 2 // easeInOutSine: steady, visible 0 → 100

/** Counts 0 → 100 over `ms`. Always runs (reduced-motion users still see the count). */
function useCounter(ms: number) {
  const [n, setN] = useState(0)
  useEffect(() => {
    let raf = 0
    const t0 = performance.now()
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / ms)
      setN(Math.round(ease(p) * 100))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [ms])
  return n
}

export default function Splash({ onDone }: { onDone: () => void }) {
  const reduce = useRef(typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches).current
  const [leaving, setLeaving] = useState(false)
  const n = useCounter(SPLASH_MS - SPLASH_FADE_MS - 250)
  const doneRef = useRef(onDone)
  doneRef.current = onDone
  const stage = stageOf(n)

  // Deterministic gold dust (no Math.random → stable across StrictMode renders)
  const dust = useMemo(() => Array.from({ length: 16 }, (_, i) => ({
    '--x': `${(i * 37 + 11) % 100}%`, '--s': `${2 + (i % 3)}px`,
    '--t': `${4.5 + (i % 5) * 0.7}s`, '--dl': `${((i * 0.43) % 3).toFixed(2)}s`,
  } as CSSProperties)), [])

  useEffect(() => {
    document.documentElement.classList.add('lz-splash-on')
    const timers = [
      window.setTimeout(() => { setLeaving(true); finishSplash(); document.documentElement.classList.remove('lz-splash-on') }, SPLASH_MS - SPLASH_FADE_MS),
      window.setTimeout(() => doneRef.current(), SPLASH_MS),
    ]
    return () => { timers.forEach(clearTimeout); document.documentElement.classList.remove('lz-splash-on') }
  }, [])

  return (
    <div className={`lzs${leaving ? ' out' : ''}${reduce ? ' rm' : ''}`} role="status" aria-live="polite" aria-label={`Loading LineZero, ${n} percent`}>
      <div className="lzs-glow" aria-hidden="true" />
      <div className="lzs-dust" aria-hidden="true">{dust.map((s, i) => <i key={i} style={s} />)}</div>
      <div className="lzs-grain" aria-hidden="true" />
      <i className="lzs-c tl" aria-hidden="true" /><i className="lzs-c tr" aria-hidden="true" />
      <i className="lzs-c bl" aria-hidden="true" /><i className="lzs-c br" aria-hidden="true" />

      <div className="lzs-core">
        <div className="lzs-logo" aria-hidden="true">
          <svg className="lzs-ring" viewBox="0 0 100 100">
            <circle className="lzs-orbit" cx="50" cy="50" r="48" fill="none" stroke="rgba(217,192,140,.35)" strokeWidth=".6" strokeDasharray="1 3" />
            <circle cx="50" cy="50" r="44" fill="none" stroke="rgba(217,192,140,.14)" strokeWidth="1" />
            <circle className="lzs-arc" cx="50" cy="50" r="44" fill="none" stroke="url(#lzsG)" strokeWidth="1.4" strokeLinecap="round" pathLength="1" strokeDasharray="1" strokeDashoffset={1 - n / 100} transform="rotate(-90 50 50)" />
            <defs><linearGradient id="lzsG" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#D9C08C" /><stop offset="1" stopColor="#FFF3D0" /></linearGradient></defs>
          </svg>
          <svg className="lzs-mark" viewBox="0 0 64 64">
            <path className="lzs-p" pathLength="1" d="M4 18h12c7 0 9 7 12 11" stroke="#20D6C5" strokeWidth="3.5" fill="none" strokeLinecap="round" />
            <path className="lzs-p" pathLength="1" d="M4 32h18" stroke="#20D6C5" strokeWidth="3.5" fill="none" strokeLinecap="round" />
            <path className="lzs-p" pathLength="1" d="M4 46h12c7 0 9-7 12-11" stroke="#20D6C5" strokeWidth="3.5" fill="none" strokeLinecap="round" />
            <ellipse className="lzs-e" cx="43" cy="32" rx="12" ry="15" stroke="#6B65FF" strokeWidth="5" fill="none" />
          </svg>
        </div>

        <p className="lzs-word" aria-hidden="true">
          {'LINEZERO'.split('').map((ch, i) => (
            <span key={i} style={{ '--d': `${0.9 + i * 0.07}s` } as CSSProperties}>{ch}</span>
          ))}
        </p>
        <div className="lzs-rule" aria-hidden="true" />
        <p className="lzs-tag" aria-hidden="true">Intelligent queue operations</p>
      </div>

      <div className="lzs-foot" aria-hidden="true">
        <div className="lzs-num"><b>{String(n).padStart(3, '0')}</b><small>%</small></div>
        <div className="lzs-track"><i style={{ transform: `scaleX(${n / 100})` }} /></div>
        <div className={`lzs-stage${stage === 3 ? ' ready' : ''}`}><span key={stage}>{STAGES[stage]}</span></div>
      </div>
    </div>
  )
}
