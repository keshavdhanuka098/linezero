import { useCallback, useEffect, useRef, useState } from 'react'

export type PlayStatus = 'idle' | 'playing' | 'paused' | 'done'
export const SPEEDS = [1, 2, 4, 8, 16, 32]

/** Playback clock. `speed` is simulated minutes per real second. Play / Pause / Resume / Reset / seek. */
export function usePlayback(duration: number) {
  const [t, setT] = useState(0)
  const [status, setStatus] = useState<PlayStatus>('idle')
  const [speed, setSpeed] = useState(4)
  const tRef = useRef(0)
  const raf = useRef(0)

  useEffect(() => {
    if (status !== 'playing') return
    let last = performance.now()
    const tick = (now: number) => {
      const next = Math.min(duration, tRef.current + ((now - last) / 1000) * speed)
      last = now
      tRef.current = next
      setT(next)
      if (next >= duration) { setStatus('done'); return }
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [status, speed, duration])

  const seek = useCallback((x: number) => { const v = Math.max(0, Math.min(duration, x)); tRef.current = v; setT(v) }, [duration])
  const play = useCallback(() => { if (tRef.current >= duration) { tRef.current = 0; setT(0) } setStatus('playing') }, [duration])
  const pause = useCallback(() => setStatus(s => (s === 'playing' ? 'paused' : s)), [])
  const reset = useCallback(() => { tRef.current = 0; setT(0); setStatus('idle') }, [])
  return { t, status, speed, setSpeed, seek, play, pause, resume: play, reset, playing: status === 'playing' }
}
export type Playback = ReturnType<typeof usePlayback>
