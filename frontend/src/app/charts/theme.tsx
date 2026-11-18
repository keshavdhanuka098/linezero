import type { ReactNode } from 'react'
import { useStore } from '../../store/store'

export const C = {
  violet: '#6B65FF', teal: '#20D6C5', warn: '#FF7A45', amber: '#F5B84B', crit: '#FF5C7A', muted: '#8997AD',
  grid: '#1b2740', axis: '#64748f', text: '#E9F0FA',
  cat: ['#6B65FF', '#20D6C5', '#F5B84B', '#FF7A45', '#5BB6FF', '#E283E8'],
}
export const axisProps = { stroke: C.axis, tick: { fill: C.axis, fontSize: 11 }, tickLine: false, axisLine: { stroke: C.grid } }
export const gridProps = { stroke: C.grid, strokeDasharray: '3 4', vertical: false }
export const useAnimate = () => useStore(s => s.settings.animateCharts)

interface TipItem { name?: string | number; value?: number | string; color?: string; dataKey?: string | number; payload?: unknown }
export function ChartTooltip({ active, payload, label, fmt, labelFmt }: { active?: boolean; payload?: TipItem[]; label?: string | number; fmt?: (v: number, name: string) => string; labelFmt?: (l: string | number) => string }) {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: '#0C1426', border: '1px solid #26365A', borderRadius: 10, padding: '8px 12px', fontSize: 12, boxShadow: '0 10px 30px rgba(0,0,0,.5)', minWidth: 120 }}>
      {label !== undefined && <div style={{ color: C.muted, marginBottom: 4 }}>{labelFmt ? labelFmt(label) : label}</div>}
      {payload.map((p, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'space-between' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}><i style={{ width: 8, height: 8, borderRadius: 2, background: p.color, display: 'inline-block' }} />{p.name}</span>
          <b style={{ fontFamily: 'var(--font-h)' }}>{typeof p.value === 'number' ? (fmt ? fmt(p.value, String(p.name)) : (Math.round(p.value * 100) / 100).toLocaleString()) : p.value}</b>
        </div>
      ))}
    </div>
  )
}
export function Legend({ items }: { items: { label: string; color: string; dashed?: boolean }[] }) {
  return <div className="legend" aria-label="Legend">{items.map(i => <span key={i.label}><i style={{ background: i.dashed ? 'transparent' : i.color, border: i.dashed ? `1.5px dashed ${i.color}` : undefined }} />{i.label}</span>)}</div>
}
export const ChartBox = ({ h = 240, children }: { h?: number; children: ReactNode }) => <div style={{ width: '100%', height: h, minWidth: 0 }}>{children}</div>
