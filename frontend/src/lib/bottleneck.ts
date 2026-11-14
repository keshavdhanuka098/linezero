import type { Counter, Queue, State } from '../store/types'
import { counterThroughput, demandProfile, demoHour, fmtMin, pct, queueMetrics } from './metrics'
import { mean, median } from './queueMath'

export type BnType = 'Overloaded counter' | 'Underutilized counter' | 'Uneven workload' | 'Excessive service time' | 'Arrival spike' | 'Queue accumulation' | 'Capacity outage'
export type Sev = 'critical' | 'high' | 'medium' | 'low'
export interface Finding {
  id: string; type: BnType; severity: Sev; score: number
  queueId: string; queueName: string; counterId?: string; counterName?: string
  metrics: [string, string][]
  why: string; impact: string; action: string
}
export const SEV_RANK: Record<Sev, number> = { critical: 0, high: 1, medium: 2, low: 3 }

export function recentArrivalRate(s: State, q: Queue, minutes = 15) {
  const h = s.history.slice(-minutes)
  return h.length ? h.reduce((a, x) => a + (x.arrByQueue[q.id] ?? 0), 0) / h.length : 0
}
export function routingShare(q: Queue, c: Counter, cs: Counter[]) {
  const act = cs.filter(x => x.status === 'active')
  if (c.status !== 'active' || !act.length) return 0
  return q.routing === 'weighted' ? c.routeWeight / act.reduce((a, x) => a + x.routeWeight, 0) : counterThroughput(c) / act.reduce((a, x) => a + counterThroughput(x), 0)
}

export function detectBottlenecks(s: State): Finding[] {
  const th = s.settings.thresholds, out: Finding[] = []
  for (const q of s.queues) {
    const cs = s.counters.filter(c => c.queueId === q.id), act = cs.filter(c => c.status === 'active')
    const m = queueMetrics(q, s.counters)
    const base = { queueId: q.id, queueName: q.name }
    const lam = recentArrivalRate(s, q), cap = m.throughput

    if (!act.length && (m.waiting > 0 || cs.length)) {
      out.push({ ...base, id: `out:${q.id}`, type: 'Capacity outage', severity: m.waiting ? 'critical' : 'high', score: 100, metrics: [['Active counters', `0 / ${cs.length}`], ['Waiting', String(m.waiting)]],
        why: `All ${cs.length} counter(s) in this queue are paused or missing, so nothing can serve the ${m.waiting} waiting customer(s).`, impact: 'Customers cannot be served; waiting time grows without bound and abandonment is likely.', action: 'Resume at least one counter or add capacity in the Live Monitor.' })
      continue
    }
    const qMedianSvc = median(act.map(c => c.avgService)), avgWaiting = mean(act.map(c => c.waiting.length))
    for (const c of act) {
      const share = routingShare(q, c, cs)
      if (c.utilEma >= th.highUtil) {
        const sv = c.avgService / (qMedianSvc || c.avgService)
        out.push({ ...base, id: `ovl:${c.id}`, type: 'Overloaded counter', severity: c.utilEma >= 0.96 ? 'critical' : 'high', score: 60 + c.utilEma * 40 + c.waiting.length, counterId: c.id, counterName: c.name,
          metrics: [['Utilization', pct(c.utilEma)], ['Limit', pct(th.highUtil)], ['Own line', `${c.waiting.length} waiting`], ['Queue avg line', avgWaiting.toFixed(1)], ['Avg service', fmtMin(c.avgService)], ['Routing share', pct(share)]],
          why: `${c.name} has been busy ${pct(c.utilEma)} of the time (limit ${pct(th.highUtil)}). Its own line holds ${c.waiting.length} people versus ${avgWaiting.toFixed(1)} on average across the queue${q.routing === 'weighted' ? `, and it is routed ${pct(share)} of arrivals` : ''}${sv > 1.2 ? `; its ${fmtMin(c.avgService)} service time is ${sv.toFixed(1)}× the queue median` : ''}.`,
          impact: `Customers routed here wait ≈ ${fmtMin(((c.waiting.length + 1) / c.servers) * c.avgService)}; delays spill into overall queue wait.`,
          action: q.routing === 'weighted' && share > 1 / act.length ? `Lower ${c.name}'s routing weight or switch the queue to “shortest line” routing; consider adding a parallel server.` : `Add a parallel server to ${c.name} or move arrivals to less busy counters.` })
      }
      if (c.avgService > 1.4 * qMedianSvc && act.length >= 3) {
        out.push({ ...base, id: `svc:${c.id}`, type: 'Excessive service time', severity: c.avgService > 1.8 * qMedianSvc ? 'high' : 'medium', score: 40 + (c.avgService / qMedianSvc) * 10, counterId: c.id, counterName: c.name,
          metrics: [['Avg service', fmtMin(c.avgService)], ['Queue median', fmtMin(qMedianSvc)], ['Ratio', `${(c.avgService / qMedianSvc).toFixed(2)}×`], ['Throughput', `${(counterThroughput(c) * 60).toFixed(1)}/h`]],
          why: `${c.name} needs ${fmtMin(c.avgService)} per customer versus a ${fmtMin(qMedianSvc)} median in the same queue (${(c.avgService / qMedianSvc).toFixed(2)}×; flagged above 1.4×).`,
          impact: `Serves ${(counterThroughput(c) * 60).toFixed(1)} customers/hour — fewer than its peers — so its line backs up first.`, action: 'Review task mix and tooling at this counter; route complex cases elsewhere or provide additional training/support.' })
      }
      if (c.utilEma <= th.lowUtil && (act.some(x => x.id !== c.id && x.utilEma >= th.highUtil) || m.waiting >= 3)) {
        out.push({ ...base, id: `und:${c.id}`, type: 'Underutilized counter', severity: c.utilEma < th.lowUtil / 2 ? 'medium' : 'low', score: 20 + (th.lowUtil - c.utilEma) * 50, counterId: c.id, counterName: c.name,
          metrics: [['Utilization', pct(c.utilEma)], ['Floor', pct(th.lowUtil)], ['Queue waiting', String(m.waiting)], ['Routing share', pct(share)]],
          why: `${c.name} is busy only ${pct(c.utilEma)} of the time (floor ${pct(th.lowUtil)}) while ${m.waiting} customer(s) wait elsewhere in the queue or another counter exceeds ${pct(th.highUtil)}.`,
          impact: 'Spare capacity is not being used, so other counters carry avoidable load.', action: q.routing === 'weighted' ? `Increase ${c.name}'s routing weight or use shortest-line routing to send it more arrivals.` : 'Cross-train staff to take overflow or reassign this counter to a busier queue.' })
      }
    }
    if (act.length >= 2) {
      const us = act.map(c => c.utilEma), hi = act[us.indexOf(Math.max(...us))], lo = act[us.indexOf(Math.min(...us))], spread = Math.max(...us) - Math.min(...us)
      if (spread >= 0.4) out.push({ ...base, id: `uneven:${q.id}`, type: 'Uneven workload', severity: spread >= 0.6 ? 'high' : 'medium', score: 30 + spread * 60, counterId: hi.id, counterName: hi.name,
        metrics: [['Busiest', `${hi.name} ${pct(hi.utilEma)}`], ['Quietest', `${lo.name} ${pct(lo.utilEma)}`], ['Spread', `${Math.round(spread * 100)} pts`], ['Flag at', '≥ 40 pts']],
        why: `Utilization ranges from ${pct(lo.utilEma)} (${lo.name}) to ${pct(hi.utilEma)} (${hi.name}) — a ${Math.round(spread * 100)}-point spread (flagged at ≥ 40). Total capacity is sufficient but it is not shared evenly.`,
        impact: 'Some customers queue behind a hot counter while others sit idle, inflating average wait without adding capacity.', action: 'Rebalance routing weights or use shortest-line routing; open the Resource Optimizer to test a different allocation.' })
    }
    const exp = q.arrivalRate * demandProfile(demoHour(s.clock))
    if (exp > 0 && lam / exp >= 1.6 && lam * 15 >= 5) out.push({ ...base, id: `spike:${q.id}`, type: 'Arrival spike', severity: lam / exp >= 2.4 ? 'high' : 'medium', score: 35 + (lam / exp) * 10,
      metrics: [['Recent rate', `${lam.toFixed(2)}/min`], ['Expected', `${exp.toFixed(2)}/min`], ['Ratio', `${(lam / exp).toFixed(1)}×`], ['Window', '15 min']],
      why: `Arrivals over the last 15 min average ${lam.toFixed(2)}/min versus ${exp.toFixed(2)}/min expected from the daily demand profile (${(lam / exp).toFixed(1)}×; flagged at ≥ 1.6×).`,
      impact: 'A short surge can saturate counters even when average capacity is adequate.', action: 'Bring forward a standby counter, enable overflow routing, or notify customers of expected delay.' })
    const n = s.history.length, past = n > 10 ? (s.history[n - 11].byQueue[q.id] ?? 0) : m.waiting, grow = m.waiting - past
    const rho = cap > 0 ? lam / cap : Infinity
    if ((rho >= 1 && m.waiting >= 4) || (grow >= 4 && m.waiting >= 8)) out.push({ ...base, id: `acc:${q.id}`, type: 'Queue accumulation', severity: rho >= 1.2 || (Number.isFinite(m.estWait) && m.estWait > 2 * th.waitSla) ? 'critical' : 'high', score: 55 + Math.min(40, m.waiting),
      metrics: [['Waiting now', String(m.waiting)], ['Change (10 min)', `${grow >= 0 ? '+' : ''}${grow}`], ['Arrival rate', `${lam.toFixed(2)}/min`], ['Service capacity', `${cap.toFixed(2)}/min`], ['Load ρ', Number.isFinite(rho) ? rho.toFixed(2) : '∞'], ['Est. wait', fmtMin(m.estWait)]],
      why: `${m.waiting} people are waiting (${grow >= 0 ? '+' : ''}${grow} in 10 min). Arrivals (${lam.toFixed(2)}/min) ${rho >= 1 ? 'exceed' : 'are close to'} active service capacity (${cap.toFixed(2)}/min), load ρ = ${Number.isFinite(rho) ? rho.toFixed(2) : '∞'}.`,
      impact: `New arrivals face an estimated ${fmtMin(m.estWait)} wait against a ${th.waitSla}m target.`, action: 'Add capacity now (resume paused counters, add a parallel server) or shorten service time for simple requests.' })
  }
  return out.sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity] || b.score - a.score)
}
