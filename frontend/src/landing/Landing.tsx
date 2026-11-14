import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { mountLanding } from './landingEngine.js'
import { landingMarkup } from './landingMarkup'
import './landing.css'

export default function Landing() {
  const nav = useNavigate()
  const ref = useRef<HTMLDivElement>(null)
  const [launching, setLaunching] = useState(false)

  useEffect(() => {
    let seen = false
    try { seen = sessionStorage.getItem('lz_seen') === '1'; sessionStorage.setItem('lz_seen', '1') } catch {}
    const cleanup = mountLanding({ skipLoader: seen })
    return cleanup
  }, [])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const onClick = (e: MouseEvent) => {
      const a = (e.target as HTMLElement).closest('[data-launch]')
      if (!a) return
      e.preventDefault()
      setLaunching(true)
      window.setTimeout(() => nav('/app/dashboard'), 900)
    }
    el.addEventListener('click', onClick)
    return () => el.removeEventListener('click', onClick)
  }, [nav])

  return (
    <div className="lz-landing" ref={ref}>
      <div dangerouslySetInnerHTML={{ __html: landingMarkup }} />
      {launching && (
        <div className="lz-launch" role="status" aria-label="Opening LineZero application">
          <svg viewBox="0 0 64 64" aria-hidden="true">
            <path d="M4 18h12c7 0 9 7 12 11" stroke="#20D6C5" strokeWidth="3.5" fill="none" strokeLinecap="round" />
            <path d="M4 32h18" stroke="#20D6C5" strokeWidth="3.5" fill="none" strokeLinecap="round" />
            <path d="M4 46h12c7 0 9-7 12-11" stroke="#20D6C5" strokeWidth="3.5" fill="none" strokeLinecap="round" />
            <ellipse cx="43" cy="32" rx="12" ry="15" stroke="#6B65FF" strokeWidth="5" fill="none" />
          </svg>
          <span>ENTERING OPERATIONS</span>
        </div>
      )}
    </div>
  )
}
