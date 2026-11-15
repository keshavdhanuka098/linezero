import type { ImprovementSet } from '../../api/twinTypes'
import { cx } from '../ui/kit'

export const f1 = (v: number | null | undefined, d = 2) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—')

export interface MetricDef { key: string; label: string; fmt: (v: number) => string }
export const METRICS: MetricDef[] = [
  { key: 'avg_waiting_time', label: 'Average wait', fmt: v => `${f1(v)} min` },
  { key: 'p95_waiting_time', label: 'P95 wait', fmt: v => `${f1(v)} min` },
  { key: 'max_queue_length', label: 'Max queue length', fmt: v => f1(v, 1) },
  { key: 'total_served', label: 'Customers served', fmt: v => f1(v, 0) },
  { key: 'abandoned', label: 'Abandoned', fmt: v => f1(v, 1) },
  { key: 'avg_utilization_available', label: 'Counter utilization', fmt: v => `${f1(v * 100, 0)}%` },
  { key: 'resource_cost', label: 'Resource cost', fmt: v => f1(v) },
]
export const metricFmt = (key: string) => METRICS.find(m => m.key === key)?.fmt ?? ((v: number) => f1(v))

/** Colour for a change: green when it moved in the "better" direction. */
export function tone(better: 'lower' | 'higher' | null | undefined, delta: number): string {
  if (!better || Math.abs(delta) < 1e-9) return 'delta-flat'
  return (better === 'lower') === (delta < 0) ? 'delta-good' : 'delta-bad'
}

export function ImprovementTable({ imp, before = 'Before', after = 'After' }: { imp: ImprovementSet; before?: string; after?: string }) {
  return (
    <div className="tw"><table className="tbl">
      <thead><tr><th>Metric</th><th>{before}</th><th>{after}</th><th>Change</th><th>Evidence</th></tr></thead>
      <tbody>
        {METRICS.map(m => {
          const r = imp[m.key]
          if (!r) return null
          return (
            <tr key={m.key}>
              <td>{m.label}</td><td className="mono">{m.fmt(r.before)}</td><td className="mono">{m.fmt(r.after)}</td>
              <td className={cx('mono', tone(r.better, r.delta))}>{r.delta > 0 ? '+' : ''}{m.fmt(r.delta).replace(/^-/, '−')}{r.pct !== null ? ` (${r.pct > 0 ? '+' : ''}${f1(r.pct, 0)}%)` : ''}</td>
              <td className="twin-note">{r.paired ? (r.significant ? 'clear difference' : 'within noise') : 'n/a'}</td>
            </tr>
          )
        })}
      </tbody>
    </table></div>
  )
}
