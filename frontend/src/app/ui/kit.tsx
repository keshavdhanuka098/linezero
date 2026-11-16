import { Component, useEffect, useRef, type ErrorInfo, type ReactNode } from 'react'
import { create } from 'zustand'
import { AlertTriangle, Inbox, Loader2, X, type LucideIcon } from 'lucide-react'

export const cx = (...a: (string | false | undefined | null)[]) => a.filter(Boolean).join(' ')

interface T { id: number; msg: string; err?: boolean }
const useToasts = create<{ list: T[]; push(m: string, err?: boolean): void }>(set => ({
  list: [],
  push: (msg, err) => {
    const id = Date.now() + Math.random()
    set(s => ({ list: [...s.list, { id, msg, err }] }))
    setTimeout(() => set(s => ({ list: s.list.filter(t => t.id !== id) })), 3600)
  },
}))
export const toast = (m: string, err = false) => useToasts.getState().push(m, err)
export function Toasts() {
  const list = useToasts(s => s.list)
  return <div className="toasts" role="status" aria-live="polite">{list.map(t => <div key={t.id} className={cx('toast', t.err && 'err')}>{t.msg}</div>)}</div>
}

export function PageHeader({ title, sub, children, demo = true }: { title: string; sub?: ReactNode; children?: ReactNode; demo?: boolean }) {
  return (
    <div className="ph">
      <div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><h1>{title}</h1>{demo && <DemoBadge />}</div>
        {sub && <p>{sub}</p>}
      </div>
      {children && <div className="acts">{children}</div>}
    </div>
  )
}
export const DemoBadge = ({ label = 'Demo data' }: { label?: string }) => <span className="chip demo" title="Synthetic demonstration data — not live institutional data">{label}</span>

export function Card({ title, sub, right, children, className, hl }: { title?: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; hl?: boolean }) {
  return (
    <section className={cx('card', hl && 'hl', className)}>
      {(title || right) && <div className="ch-h"><div><h3>{title}</h3>{sub && <small>{sub}</small>}</div>{right && <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>{right}</div>}</div>}
      {children}
    </section>
  )
}

export function Kpi({ label, value, unit, sub, icon: Icon, tone, bar }: { label: string; value: ReactNode; unit?: string; sub?: ReactNode; icon?: LucideIcon; tone?: 'ok' | 'warn' | 'hot' | 'crit'; bar?: number }) {
  const color = tone === 'crit' ? '#ff8da1' : tone === 'hot' ? 'var(--warn)' : tone === 'warn' ? 'var(--amber)' : undefined
  return (
    <div className="card kpi">
      {Icon && <Icon className="ic" size={18} />}
      <div className="l">{label}</div>
      <div className="v" style={{ color }}>{value}{unit && <small>{unit}</small>}</div>
      {bar !== undefined && <div className={cx('bar', tone === 'hot' || tone === 'crit' ? 'hot' : tone === 'warn' ? 'warm' : '')}><i style={{ width: `${Math.min(100, Math.max(0, bar * 100))}%` }} /></div>}
      {sub && <div className="s">{sub}</div>}
    </div>
  )
}

export function Chip({ tone, children }: { tone?: 'ok' | 'warn' | 'hot' | 'crit' | 'vio' | 'demo'; children: ReactNode }) { return <span className={cx('chip', tone)}>{children}</span> }

export function Bar({ v, tone }: { v: number; tone?: 'hot' | 'warm' | 'vio' }) { return <div className={cx('bar', tone)}><i style={{ width: `${Math.min(100, Math.max(0, v * 100))}%` }} /></div> }

export function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: { v: T; l: string }[]; onChange(v: T): void; label?: string }) {
  return <div className="seg" role="group" aria-label={label}>{options.map(o => <button key={o.v} className={cx(value === o.v && 'on')} aria-pressed={value === o.v} onClick={() => onChange(o.v)}>{o.l}</button>)}</div>
}

export function Field({ label, error, hint, right, children }: { label: string; error?: string; hint?: string; right?: ReactNode; children: ReactNode }) {
  return <label className="fld"><span>{label}{right}</span>{children}{error ? <span className="err" role="alert">{error}</span> : hint ? <span className="hint">{hint}</span> : null}</label>
}

export function EmptyState({ icon: Icon = Inbox, title, text, action }: { icon?: LucideIcon; title: string; text?: string; action?: ReactNode }) {
  return <div className="empty"><div className="eic"><Icon size={24} /></div><h4>{title}</h4>{text && <p>{text}</p>}{action}</div>
}
export function ErrorState({ title = 'Something went wrong', text, onRetry }: { title?: string; text?: string; onRetry?: () => void }) {
  return <div className="empty err"><div className="eic"><AlertTriangle size={24} /></div><h4>{title}</h4>{text && <p>{text}</p>}{onRetry && <button className="btn" onClick={onRetry}>Try again</button>}</div>
}
export const Skeleton = ({ h = 120, w = '100%' }: { h?: number; w?: number | string }) => <div className="sk" style={{ height: h, width: w }} aria-hidden="true" />
export function PageSkeleton() {
  return <div className="page" role="status" aria-label="Loading"><Skeleton h={44} w={320} /><div className="grid g4 kp">{[0, 1, 2, 3].map(i => <Skeleton key={i} h={96} />)}</div><div className="grid g2"><Skeleton h={300} /><Skeleton h={300} /></div></div>
}
export const Spinner = ({ size = 16 }: { size?: number }) => <Loader2 size={size} className="spin" />

export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { err: Error | null }> {
  state = { err: null as Error | null }
  static getDerivedStateFromError(err: Error) { return { err } }
  componentDidCatch(e: Error, i: ErrorInfo) { console.error('Page error', e, i.componentStack) }
  componentDidUpdate(p: { resetKey?: string }) { if (p.resetKey !== this.props.resetKey && this.state.err) this.setState({ err: null }) }
  render() {
    if (this.state.err) return <div className="page"><div className="card"><ErrorState text={this.state.err.message} onRetry={() => this.setState({ err: null })} /></div></div>
    return this.props.children
  }
}

export function Modal({ title, sub, onClose, children, footer, large }: { title: string; sub?: string; onClose(): void; children: ReactNode; footer?: ReactNode; large?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null
    const first = ref.current?.querySelector<HTMLElement>('input,select,button:not([data-x])')
    first?.focus()
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', k)
    return () => { document.removeEventListener('keydown', k); prev?.focus?.() }
  }, [onClose])
  return (
    <div className="ov" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className={cx('modal', large && 'lg')} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
          <div><h3 className="hd">{title}</h3>{sub && <div style={{ color: 'var(--muted)', fontSize: 13 }}>{sub}</div>}</div>
          <button className="btn g ic sm" data-x aria-label="Close" onClick={onClose}><X size={16} /></button>
        </div>
        <div style={{ marginTop: 14, display: 'grid', gap: 14 }}>{children}</div>
        {footer && <div className="mf">{footer}</div>}
      </div>
    </div>
  )
}
export function Confirm({ title, text, confirmLabel = 'Delete', onConfirm, onClose }: { title: string; text: string; confirmLabel?: string; onConfirm(): void; onClose(): void }) {
  return <Modal title={title} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn d" onClick={() => { onConfirm(); onClose() }}>{confirmLabel}</button></>}><p style={{ margin: 0, color: 'var(--muted)' }}>{text}</p></Modal>
}

export function useOutside(ref: React.RefObject<HTMLElement | null>, on: () => void, active: boolean) {
  useEffect(() => {
    if (!active) return
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) on() }
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') on() }
    document.addEventListener('mousedown', h); document.addEventListener('keydown', k)
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k) }
  }, [ref, on, active])
}
