import type { Counter, Queue, State, Settings } from '../store/types'
import { clamp, mean } from './queueMath'

export const DEMO_START_HOUR = 8
export const DAY_MIN = 600

export function demoHour(clock: number) { return DEMO_START_HOUR + Math.floor((clock % DAY_MIN) / 60) }
export function demoTimeLabel(clock: number, fmt: '24h' | '12h' = '24h') {
  const m = clock % DAY_MIN, h = DEMO_START_HOUR + Math.floor(m / 60), mm = m % 60
  if (fmt === '24h') return `${String(h).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
  const hh = h % 12 || 12
  return `${hh}:${String(mm).padStart(2, '0')} ${h >= 12 ? 'PM' : 'AM'}`
}

export function demandProfile(hour: number): number {
  if (hour < 8 || hour >= 18) return 0
  const raw = (h: number) => 0.25 + Math.exp(-(((h - 10.5) / 1.5) ** 2)) + 0.8 * Math.exp(-(((h - 14.5) / 1.4) ** 2))
  let s = 0
  for (let h = 8; h < 18; h++) s += raw(h + 0.5)
  return raw(hour + 0.5) / (s / 10)
}
export const dowFactor = (d: number) => [0.3, 1.15, 1.05, 1, 1, 1.1, 0.55][d]

export function countersOf(s: Pick<State, 'counters'>, queueId: string) { return s.counters.filter(c => c.queueId === queueId) }

export function counterEstWait(c: Counter): number {
  if (c.status === 'paused') return Infinity
  const ahead = c.waiting.length
  if (ahead === 0 && c.serving.length < c.servers) return 0
  return ((ahead + (c.serving.length >= c.servers ? 0.5 : 0)) / c.servers) * c.avgService
}

export function counterThroughput(c: Counter) { return c.status === 'active' ? c.servers / c.avgService : 0 }

export interface QueueMetrics {
  waiting: number; serving: number; length: number
  estWait: number
  avgService: number
  util: number
  maxUtil: number
  activeCounters: number
  throughput: number
}

export function queueMetrics(q: Queue, counters: Counter[]): QueueMetrics {
  const cs = counters.filter(c => c.queueId === q.id)
  const act = cs.filter(c => c.status === 'active')
  const waiting = q.holding.length + cs.reduce((s, c) => s + c.waiting.length, 0)
  const serving = cs.reduce((s, c) => s + c.serving.length, 0)
  const sv = act.reduce((s, c) => s + c.servers, 0)
  const avgService = sv ? act.reduce((s, c) => s + c.avgService * c.servers, 0) / sv : mean(cs.map(c => c.avgService))
  let estWait = Infinity
  if (act.length) {
    if (q.routing === 'shortest') estWait = Math.min(...act.map(counterEstWait))
    else {
      const w = act.reduce((s, c) => s + c.routeWeight, 0) || 1
      estWait = act.reduce((s, c) => s + (c.routeWeight / w) * counterEstWait(c), 0)
    }
  }
  return {
    waiting, serving, length: waiting + serving, estWait, avgService,
    util: sv ? act.reduce((s, c) => s + c.utilEma * c.servers, 0) / sv : 0,
    maxUtil: act.length ? Math.max(...act.map(c => c.utilEma)) : 0,
    activeCounters: act.length,
    throughput: act.reduce((s, c) => s + counterThroughput(c), 0),
  }
}

export type RiskLevel = 'Low' | 'Moderate' | 'High' | 'Critical'
export function riskLevel(score: number): RiskLevel { return score < 35 ? 'Low' : score < 60 ? 'Moderate' : score < 80 ? 'High' : 'Critical' }

export function queueRisk(q: Queue, counters: Counter[], history: State['history'], th: Settings['thresholds']): number {
  const m = queueMetrics(q, counters)
  if (!m.activeCounters) return m.waiting > 0 ? 100 : 0
  const wait = Number.isFinite(m.estWait) ? m.estWait : th.waitSla * 3
  let score = 100 * (0.5 * clamp(m.maxUtil, 0, 1) + 0.5 * clamp(wait / (2 * th.waitSla), 0, 1))
  const n = history.length
  if (n > 10) score += clamp(((history[n - 1].byQueue[q.id] ?? 0) - (history[n - 11].byQueue[q.id] ?? 0)) * 3, -10, 15)
  return clamp(Math.round(score), 0, 100)
}

export function systemMetrics(s: State) {
  const qm = s.queues.map(q => ({ q, m: queueMetrics(q, s.counters) }))
  const act = s.counters.filter(c => c.status === 'active')
  const sv = act.reduce((a, c) => a + c.servers, 0)
  const recent = s.completed.slice(-40)
  const risks = s.queues.map(q => queueRisk(q, s.counters, s.history, s.settings.thresholds))
  const risk = risks.length ? Math.round(Math.max(...risks) * 0.6 + mean(risks) * 0.4) : 0
  return {
    activeQueues: s.queues.filter(q => s.counters.some(c => c.queueId === q.id && c.status === 'active')).length,
    totalQueues: s.queues.length,
    waiting: qm.reduce((a, x) => a + x.m.waiting, 0),
    serving: qm.reduce((a, x) => a + x.m.serving, 0),
    avgWait: recent.length ? mean(recent.map(r => r.wait)) : 0,
    avgService: recent.length ? mean(recent.map(r => r.service)) : mean(s.counters.map(c => c.avgService)),
    observed: recent.length,
    util: sv ? act.reduce((a, c) => a + c.utilEma * c.servers, 0) / sv : 0,
    risk, riskLevel: riskLevel(risk), risks,
    activeCounters: act.length, pausedCounters: s.counters.length - act.length,
  }
}

export function fmtMin(x: number): string {
  if (!Number.isFinite(x)) return '—'
  if (x < 1) return `${Math.round(x * 60)}s`
  if (x < 60) return `${x.toFixed(x < 10 ? 1 : 0)}m`
  return `${Math.floor(x / 60)}h ${Math.round(x % 60)}m`
}
export const pct = (x: number, d = 0) => `${(x * 100).toFixed(d)}%`
