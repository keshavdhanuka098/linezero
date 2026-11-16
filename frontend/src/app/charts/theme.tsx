import type { ReactNode } from 'react'
import { useStore } from '../../store/store'

/** Chart palette. Hues are kept apart in lightness so series stay distinguishable; status colours match tokens.css. */
export const C = {
  violet: '#7b75ff', teal: '#2ad4c3', warn: '#ff8a4c', amber: '#f3b84b', crit: '#ff6b82', muted: '#8791a4',
  grid: '#1d2430', axis: '#6a7487', text: '#e8ebf1',
  cat: ['#7b75ff', '#2ad4c3', '#f3b84b', '#ff8a4c', '#5bb6ff', '#e283e8'],
}
export const axisProps = { stroke: C.axis, tick: { fill: C.axis, fontSize: 12 }, tickLine: false, axisLine: { stroke: C.grid } }
export const gridProps = { stroke: C.grid, strokeDasharray: '2 4', vertical: false }
export const useAnimate = () => useStore(s => s.settings.animateCharts)

interface TipItem { name?: string | number; value?: number | string; color?: string; dataKey?: string | number; payload?: unknown }
export function ChartTooltip({ active, payload, label, fmt, labelFmt }: { active?: boolean; payload?: TipItem[]; label?: string | number; fmt?: (v: number, name: string) => string; labelFmt?: (l: string | number) => string }) {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: '#151a23', border: '1px solid #2d3748', borderRadius: 10, padding: '9px 12px', fontSize: 12.5, boxShadow: '0 12px 32px rgba(0,0,0,.5)', minWidth: 130 }}>
      {label !== undefined && <div style={{ color: C.muted, marginBottom: 6, fontWeight: 500 }}>{labelFmt ? labelFmt(label) : label}</div>}
      {payload.map((p, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 14, justifyContent: 'space-between', lineHeight: 1.7 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 7, color: '#b4bccb' }}><i style={{ width: 8, height: 8, borderRadius: 2, background: p.color, display: 'inline-block' }} />{p.name}</span>
          <b style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{typeof p.value === 'number' ? (fmt ? fmt(p.value, String(p.name)) : (Math.round(p.value * 100) / 100).toLocaleString()) : p.value}</b>
        </div>
      ))}
    </div>
  )
}
export function Legend({ items }: { items: { label: string; color: string; dashed?: boolean }[] }) {
  return <div className="legend" aria-label="Legend">{items.map(i => <span key={i.label}><i style={{ background: i.dashed ? 'transparent' : i.color, border: i.dashed ? `1.5px dashed ${i.color}` : undefined }} />{i.label}</span>)}</div>
}
export const ChartBox = ({ h = 240, children }: { h?: number; children: ReactNode }) => <div style={{ width: '100%', height: h, minWidth: 0 }}>{children}</div>
