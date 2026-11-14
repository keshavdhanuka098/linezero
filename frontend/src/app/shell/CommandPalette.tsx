import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileText, Layers, Search } from 'lucide-react'
import { useStore } from '../../store/store'
import { ROUTES } from '../routes'
import { cx } from '../ui/kit'

interface Item { id: string; group: string; label: string; hint: string; to: string; icon: React.ReactNode }

export default function CommandPalette({ onClose }: { onClose(): void }) {
  const nav = useNavigate()
  const queues = useStore(s => s.queues), counters = useStore(s => s.counters), reports = useStore(s => s.reports)
  const [q, setQ] = useState(''), [i, setI] = useState(0)
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => ref.current?.focus(), [])
  const items = useMemo<Item[]>(() => {
    const all: Item[] = [
      ...ROUTES.map(r => ({ id: r.path, group: 'Pages', label: r.title, hint: r.blurb, to: `/app/${r.path}`, icon: <r.icon size={16} /> })),
      ...queues.map(x => ({ id: x.id, group: 'Queues', label: x.name, hint: 'Open in Live Monitor', to: '/app/monitor', icon: <Layers size={16} /> })),
      ...counters.map(x => ({ id: x.id, group: 'Counters', label: x.name, hint: queues.find(y => y.id === x.queueId)?.name ?? '', to: '/app/monitor', icon: <Layers size={16} /> })),
      ...reports.map(x => ({ id: x.id, group: 'Reports', label: x.title, hint: x.type, to: '/app/reports', icon: <FileText size={16} /> })),
    ]
    const t = q.trim().toLowerCase()
    return (t ? all.filter(a => (a.label + ' ' + a.hint).toLowerCase().includes(t)) : all.filter(a => a.group === 'Pages')).slice(0, 30)
  }, [q, queues, counters, reports])
  useEffect(() => setI(0), [q])
  const go = (it: Item) => { nav(it.to); onClose() }
  const key = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setI(x => Math.min(items.length - 1, x + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setI(x => Math.max(0, x - 1)) }
    else if (e.key === 'Enter' && items[i]) go(items[i])
    else if (e.key === 'Escape') onClose()
  }
  let last = ''
  return (
    <div className="ov pal" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Global search">
        <input ref={ref} value={q} onChange={e => setQ(e.target.value)} onKeyDown={key} placeholder="Search pages, queues, counters, reports…" aria-label="Search" />
        <ul role="listbox">
          {items.length === 0 && <li style={{ padding: 24, textAlign: 'center', color: 'var(--muted)' }}><Search size={18} style={{ verticalAlign: -4 }} /> No results for “{q}”</li>}
          {items.map((it, n) => {
            const head = it.group !== last; last = it.group
            return (
              <li key={it.group + it.id} className={cx(n === i && 'sel')} role="option" aria-selected={n === i}>
                {head && <div className="grp">{it.group}</div>}
                <button onMouseEnter={() => setI(n)} onClick={() => go(it)}>{it.icon}<span>{it.label}</span><small>{it.hint}</small></button>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
