import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Bell, ChevronRight, Database, Home, LogOut, Menu, PanelLeftClose, PanelLeftOpen, Pause, Play, RotateCcw, Search, Settings as Cog, User } from 'lucide-react'
import { useStore } from '../../store/store'
import { startServerPolling, useServer } from '../../api/serverStore'
import { ROUTES } from '../routes'
import { deriveAlerts } from '../../lib/alerts'
import { demoTimeLabel } from '../../lib/metrics'
import { Confirm, ErrorBoundary, PageSkeleton, Toasts, cx, toast, useOutside } from '../ui/kit'
import CommandPalette from './CommandPalette'

const Logo = () => (
  <svg viewBox="0 0 64 64" aria-hidden="true"><path d="M4 18h12c7 0 9 7 12 11" stroke="#20D6C5" strokeWidth="3.5" fill="none" strokeLinecap="round" /><path d="M4 32h18" stroke="#20D6C5" strokeWidth="3.5" fill="none" strokeLinecap="round" /><path d="M4 46h12c7 0 9-7 12-11" stroke="#20D6C5" strokeWidth="3.5" fill="none" strokeLinecap="round" /><ellipse cx="43" cy="32" rx="12" ry="15" stroke="#6B65FF" strokeWidth="5" fill="none" /></svg>
)

function useLiveTicker() {
  const live = useStore(s => s.settings.liveFeed), ms = useStore(s => s.settings.tickMs), tick = useStore(s => s.tick)
  useEffect(() => {
    if (!live) return
    const id = window.setInterval(() => { if (!document.hidden) tick() }, ms)
    return () => window.clearInterval(id)
  }, [live, ms, tick])
}

export default function AppShell() {
  useLiveTicker()
  useEffect(() => { startServerPolling() }, [])
  const loc = useLocation(), nav = useNavigate()
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem('lz.sb') === '1' } catch { return false } })
  const [open, setOpen] = useState(false)
  const [palette, setPalette] = useState(false)
  const density = useStore(s => s.settings.density)
  const serverOn = useServer(s => s.mode === 'server' && s.status === 'online')
  const state = useStore()
  const alerts = useMemo(() => deriveAlerts(state), [state.queues, state.counters, state.history, state.settings.thresholds])
  const crit = alerts.filter(a => a.severity !== 'info').length
  useEffect(() => { setOpen(false) }, [loc.pathname])
  useEffect(() => {
    if (!open) return
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', k); return () => document.removeEventListener('keydown', k)
  }, [open])
  useEffect(() => { try { localStorage.setItem('lz.sb', collapsed ? '1' : '0') } catch {} }, [collapsed])
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette(p => !p) } }
    document.addEventListener('keydown', k); return () => document.removeEventListener('keydown', k)
  }, [])
  const route = ROUTES.find(r => loc.pathname.startsWith('/app/' + r.path))
  useEffect(() => { document.title = `${route?.title ?? 'Application'} · LineZero` }, [route])
  const groups = ['Operate', 'Analyze', 'Optimize', 'Intelligence', 'System'] as const

  return (
    <div className={cx('app', density === 'compact' && 'compact')}>
      <aside className={cx('sb', collapsed && 'col', open && 'open')} aria-label="Primary">
        <Link to="/" className="sb-brand" aria-label="LineZero landing page"><Logo /><span>LineZero</span></Link>
        <nav>
          {groups.map(g => (
            <div key={g}>
              <div className="sect">{g}</div>
              {ROUTES.filter(r => r.group === g).map(r => (
                <NavLink key={r.path} to={`/app/${r.path}`} className={({ isActive }) => cx('nl', isActive && 'on')} title={r.title}>
                  <r.icon size={18} /><span>{r.short}</span>
                  {r.path === 'bottlenecks' && crit > 0 && <em className="bd" style={{ fontStyle: 'normal' }}>{crit}</em>}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sb-foot">
          <div className={cx('sb-demo', serverOn && 'live')}><i />{serverOn ? 'Connected to the LineZero API. Seeded data is labelled synthetic.' : 'Demo workspace with synthetic data. No live institutional feed is connected.'}</div>
          <button className="sb-tog hide-m" onClick={() => setCollapsed(c => !c)} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
            {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}<span>Collapse</span>
          </button>
        </div>
      </aside>
      <div className={cx('scrim', open && 'open')} onClick={() => setOpen(false)} />
      <div className="main">
        <header className="top">
          <button className="ibtn mob" onClick={() => setOpen(o => !o)} aria-label="Toggle navigation" aria-expanded={open}><Menu size={18} /></button>
          <Breadcrumbs group={route?.group} title={route?.title} />
          <div className="spacer" />
          <SourcePill />
          <LivePill />
          <button className="search" onClick={() => setPalette(true)} aria-label="Search (Ctrl K)"><Search size={15} /><span>Search…</span><kbd>Ctrl K</kbd></button>
          <Notifications />
          <Profile onNav={nav} />
        </header>
        <ErrorBoundary resetKey={loc.pathname}>
          <Suspense fallback={<RouteFallback />}><div key={loc.pathname} className="page-in"><Outlet /></div></Suspense>
        </ErrorBoundary>
      </div>
      {palette && <CommandPalette onClose={() => setPalette(false)} />}
      <Toasts />
    </div>
  )
}

function RouteFallback() {
  return (<><div className="route-bar" role="progressbar" aria-label="Loading page"><i /></div><PageSkeleton /></>)
}

function Breadcrumbs({ group, title }: { group?: string; title?: string }) {
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      <Link to="/" title="Landing page" aria-label="LineZero home"><Home size={14} /></Link><ChevronRight size={13} />
      {group && <><span className="hide-m">{group}</span><ChevronRight size={13} className="hide-m" /></>}
      <b aria-current="page">{title ?? 'Not found'}</b>
    </nav>
  )
}

function SourcePill() {
  const mode = useServer(s => s.mode), status = useServer(s => s.status), setMode = useServer(s => s.setMode), refresh = useServer(s => s.refresh)
  const server = mode === 'server'
  const label = server ? (status === 'online' ? 'Server API' : status === 'checking' ? 'Connecting…' : 'API offline') : 'Browser demo'
  const toggle = async () => {
    if (server) { setMode('browser'); toast('Using browser demo data'); return }
    await refresh()
    if (useServer.getState().status !== 'online') { toast('Cannot reach the LineZero API. Start the backend (uvicorn app.main:app) and try again.', true); return }
    setMode('server'); toast('Using the LineZero API')
  }
  return (
    <button className={cx('live-pill hide-m', !(server && status === 'online') && 'off')} onClick={toggle} aria-label={server ? 'Switch to browser demo data' : 'Switch to server API data'} title={server ? 'Data comes from the LineZero API. Click to switch to the browser demo.' : 'Data is generated in your browser. Click to use the LineZero API.'}>
      <Database size={12} />{label}
    </button>
  )
}

function LivePill() {
  const live = useStore(s => s.settings.liveFeed), clock = useStore(s => s.clock), fmt = useStore(s => s.settings.timeFormat), setLive = useStore(s => s.setLive)
  return (
    <button className={cx('live-pill hide-m', !live && 'off')} onClick={() => setLive(!live)} aria-label={live ? 'Pause demo feed' : 'Resume demo feed'} title="Demo simulation feed — synthetic data">
      <i />{live ? 'Demo live' : 'Demo paused'} · {demoTimeLabel(clock, fmt)} {live ? <Pause size={12} /> : <Play size={12} />}
    </button>
  )
}

function Notifications() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const notifs = useStore(s => s.notifs), mark = useStore(s => s.markNotifsRead), clear = useStore(s => s.clearNotifs), clock = useStore(s => s.clock), fmt = useStore(s => s.settings.timeFormat)
  const close = useCallback(() => setOpen(false), [])
  useOutside(ref, close, open)
  const unread = notifs.filter(n => !n.read).length
  const col = { info: 'var(--violet)', warn: 'var(--amber)', crit: 'var(--crit)' }
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button className="ibtn" aria-label={`Notifications${unread ? `, ${unread} unread` : ''}`} aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <Bell size={18} />{unread > 0 && <span className="dot2">{unread > 9 ? '9+' : unread}</span>}
      </button>
      {open && (
        <div className="pop wide" role="dialog" aria-label="Notifications">
          <div className="pop-h"><span>Notifications</span><span style={{ display: 'flex', gap: 6 }}><button className="btn sm g" onClick={mark} disabled={!unread}>Mark read</button><button className="btn sm g" onClick={clear} disabled={!notifs.length}>Clear</button></span></div>
          <div style={{ maxHeight: 360, overflow: 'auto' }}>
            {notifs.length === 0 && <div className="empty" style={{ padding: 24 }}><p>No notifications. Alerts raised by the demo feed will appear here.</p></div>}
            {notifs.map(n => (
              <div key={n.id} className={cx('ni', !n.read && 'unread')}><i className="sev" style={{ background: col[n.severity] }} /><div><b>{n.title}</b><small>{n.body}</small><small style={{ display: 'block', opacity: .7 }}>{demoTimeLabel(n.t, fmt)} · {Math.max(0, clock - n.t)}m ago · demo</small></div></div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Profile({ onNav }: { onNav(p: string): void }) {
  const [open, setOpen] = useState(false), [confirm, setConfirm] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const reset = useStore(s => s.resetDemo)
  const close = useCallback(() => setOpen(false), [])
  useOutside(ref, close, open)
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button className="ibtn" style={{ width: 34 }} aria-label="User menu" aria-expanded={open} onClick={() => setOpen(o => !o)}><span className="avatar">DO</span></button>
      {open && (
        <div className="pop" role="menu">
          <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--line)', marginBottom: 4 }}><b className="hd" style={{ fontSize: 13 }}>Demo operator</b><div style={{ color: 'var(--muted)', fontSize: 12 }}>Local demo profile · no sign-in</div></div>
          <button className="mi" role="menuitem" onClick={() => { close(); onNav('/app/settings') }}><User size={16} />Profile & preferences</button>
          <button className="mi" role="menuitem" onClick={() => { close(); onNav('/app/settings') }}><Cog size={16} />Settings</button>
          <button className="mi" role="menuitem" onClick={() => { close(); setConfirm(true) }}><RotateCcw size={16} />Reset demo data</button>
          <button className="mi dng" role="menuitem" onClick={() => { close(); onNav('/') }}><LogOut size={16} />Exit to landing page</button>
        </div>
      )}
      {confirm && <Confirm title="Reset demo data?" text="Queues, counters, reports and settings return to the original synthetic demo workspace." confirmLabel="Reset" onClose={() => setConfirm(false)} onConfirm={() => { reset(); toast('Demo data reset') }} />}
    </div>
  )
}
