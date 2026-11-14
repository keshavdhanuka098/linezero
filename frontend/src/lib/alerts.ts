import type { State } from '../store/types'
import { queueMetrics, queueRisk, riskLevel, fmtMin } from './metrics'

export interface Alert { id: string; severity: 'info' | 'warn' | 'crit'; title: string; detail: string; to: string }

export function deriveAlerts(s: State): Alert[] {
  const out: Alert[] = []
  const th = s.settings.thresholds
  for (const q of s.queues) {
    const m = queueMetrics(q, s.counters)
    const risk = queueRisk(q, s.counters, s.history, th)
    if (!m.activeCounters) out.push({ id: `nc:${q.id}`, severity: 'crit', title: `${q.name} has no active counters`, detail: `${m.waiting} waiting with nothing able to serve them.`, to: '/app/monitor' })
    else if (risk >= 60) out.push({ id: `risk:${q.id}`, severity: risk >= 80 ? 'crit' : 'warn', title: `${riskLevel(risk)} congestion risk — ${q.name}`, detail: `Risk ${risk}/100 · est. wait ${fmtMin(m.estWait)} vs ${th.waitSla}m target`, to: '/app/bottlenecks' })
    else if (Number.isFinite(m.estWait) && m.estWait > th.waitSla) out.push({ id: `wait:${q.id}`, severity: 'warn', title: `Wait above target — ${q.name}`, detail: `Est. ${fmtMin(m.estWait)} vs ${th.waitSla}m target`, to: '/app/monitor' })
  }
  for (const c of s.counters) {
    if (c.status === 'active' && c.utilEma >= th.highUtil) out.push({ id: `hot:${c.id}`, severity: 'warn', title: `${c.name} at ${(c.utilEma * 100).toFixed(0)}% utilization`, detail: `Above the ${(th.highUtil * 100).toFixed(0)}% limit`, to: '/app/bottlenecks' })
    if (c.status === 'paused') out.push({ id: `p:${c.id}`, severity: 'info', title: `${c.name} is paused`, detail: 'Capacity currently unavailable', to: '/app/monitor' })
  }
  const rank = { crit: 0, warn: 1, info: 2 }
  return out.sort((a, b) => rank[a.severity] - rank[b.severity])
}
