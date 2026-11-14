import type { Counter, Queue, Settings, State } from './types'
import { stepState } from './engine'

export const defaultSettings: Settings = {
  liveFeed: true, tickMs: 1500, density: 'comfortable', timeFormat: '24h', animateCharts: true,
  sim: { arrivalRate: 1.2, avgService: 4, counters: 5, duration: 120, arrivalCV: 1, serviceCV: 0.8, seed: 2026 },
  notify: { highUtil: true, longWait: true, spike: true, system: true },
  thresholds: { highUtil: 0.85, lowUtil: 0.35, waitSla: 10 },
}

function counter(id: string, queueId: string, name: string, servers: number, avgService: number, routeWeight: number): Counter {
  return { id, queueId, name, servers, status: 'active', avgService, routeWeight, serving: [], waiting: [], utilEma: 0.3, served: 0 }
}

export function seedState(): State {
  const queues: Queue[] = [
    { id: 'q-general', name: 'General Service Desk', prefix: 'G', arrivalRate: 0.42, routing: 'weighted', nextTicket: 100, holding: [] },
    { id: 'q-billing', name: 'Billing & Payments', prefix: 'B', arrivalRate: 0.26, routing: 'shortest', nextTicket: 100, holding: [] },
    { id: 'q-support', name: 'Account Support', prefix: 'A', arrivalRate: 0.12, routing: 'shortest', nextTicket: 100, holding: [] },
  ]
  const counters: Counter[] = [
    counter('c-g1', 'q-general', 'Counter G1', 1, 4.0, 0.9),
    counter('c-g2', 'q-general', 'Counter G2', 1, 4.2, 1.0),
    counter('c-g3', 'q-general', 'Counter G3', 1, 5.0, 1.15),
    counter('c-g4', 'q-general', 'Counter G4', 1, 3.7, 0.6),
    counter('c-g5', 'q-general', 'Counter G5', 1, 3.4, 0.5),
    counter('c-b1', 'q-billing', 'Counter B1', 1, 4.0, 1),
    counter('c-b2', 'q-billing', 'Counter B2', 1, 4.5, 1),
    counter('c-b3', 'q-billing', 'Counter B3', 1, 5.0, 1),
    counter('c-a1', 'q-support', 'Desk A1 (2 agents)', 2, 9.0, 1),
    counter('c-a2', 'q-support', 'Desk A2', 1, 8.0, 1),
  ]
  let s: State = {
    queues, counters, clock: 0, seed: 20260, nextId: 1, history: [], completed: [], activity: [], notifs: [], notifCool: {},
    reports: [], settings: defaultSettings,
  }
  for (let i = 0; i < 150; i++) s = stepState(s, true)
  s.activity = [{ id: 'a0', t: s.clock, kind: 'system', source: 'demo', text: 'Demo workspace initialised with synthetic queues' }]
  s.notifs = []; s.notifCool = {}
  s.reports = seedReports()
  return s
}

function seedReports(): State['reports'] {
  const d = (daysAgo: number, h: number) => new Date(Date.now() - daysAgo * 864e5 - h * 36e5).toISOString()
  return [
    { id: 'r-demo-1', type: 'simulation', title: 'Lunch-peak staffing run (5 counters)', createdAt: d(2, 3), status: 'Reviewed', synthetic: true,
      summary: { Counters: 5, 'Arrival rate /min': 1.4, 'Avg service (min)': 4, 'Avg wait (min)': 6.2, 'Max wait (min)': 21.5, Served: 164 }, rows: [] },
    { id: 'r-demo-2', type: 'bottleneck', title: 'Bottleneck review — General Service Desk', createdAt: d(5, 1), status: 'Completed', synthetic: true,
      summary: { Findings: 3, Critical: 1, 'Most affected': 'Counter G3', Cause: 'Long service time + highest routing weight' }, rows: [] },
    { id: 'r-demo-3', type: 'optimization', title: 'Pool rebalance comparison (10 counters)', createdAt: d(9, 6), status: 'Completed', synthetic: true,
      summary: { 'Total counters': 10, 'Predicted wait before (min)': 9.8, 'Predicted wait after (min)': 5.1, Method: 'Exhaustive search, Allen–Cunneen model' }, rows: [] },
    { id: 'r-demo-4', type: 'metrics', title: 'Weekly queue metrics snapshot', createdAt: d(14, 2), status: 'Archived', synthetic: true,
      summary: { 'Avg wait (min)': 5.4, 'Avg service (min)': 4.6, 'System utilization': '61%', Served: 2210 }, rows: [] },
  ]
}
