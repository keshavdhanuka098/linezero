export type CounterStatus = 'active' | 'paused'
export type Routing = 'shortest' | 'weighted'

export interface Customer {
  id: string
  ticket: string
  label: string
  queueId: string
  arrivedAt: number
  startedAt?: number
  duration?: number
}

export interface Counter {
  id: string
  queueId: string
  name: string
  servers: number
  status: CounterStatus
  avgService: number
  routeWeight: number
  serving: Customer[]
  waiting: Customer[]
  utilEma: number
  served: number
}

export interface Queue {
  id: string
  name: string
  prefix: string
  arrivalRate: number
  routing: Routing
  nextTicket: number
  holding: Customer[]
}

export interface Completed { queueId: string; counterId: string; wait: number; service: number; at: number }

export interface Sample {
  t: number
  waiting: number
  serving: number
  arrivals: number
  avgWait: number
  util: number
  risk: number
  byQueue: Record<string, number>
  arrByQueue: Record<string, number>
}

export interface Activity { id: string; t: number; kind: 'arrival' | 'served' | 'queue' | 'counter' | 'alert' | 'system' | 'report'; text: string; source: 'demo' | 'user' }
export interface Notif { id: string; t: number; severity: 'info' | 'warn' | 'crit'; title: string; body: string; read: boolean; key: string }

export type ReportType = 'simulation' | 'metrics' | 'bottleneck' | 'optimization'
export type ReportStatus = 'Completed' | 'Reviewed' | 'Archived'
export interface Report {
  id: string
  type: ReportType
  title: string
  createdAt: string
  status: ReportStatus
  synthetic: boolean
  summary: Record<string, string | number>
  rows: Record<string, string | number>[]
}

export interface SimDefaults { arrivalRate: number; avgService: number; counters: number; duration: number; arrivalCV: number; serviceCV: number; seed: number }
export interface Settings {
  liveFeed: boolean
  tickMs: number
  density: 'comfortable' | 'compact'
  timeFormat: '24h' | '12h'
  animateCharts: boolean
  sim: SimDefaults
  notify: { highUtil: boolean; longWait: boolean; spike: boolean; system: boolean }
  thresholds: { highUtil: number; lowUtil: number; waitSla: number }
}

export interface State {
  queues: Queue[]
  counters: Counter[]
  clock: number
  seed: number
  nextId: number
  history: Sample[]
  completed: Completed[]
  activity: Activity[]
  notifs: Notif[]
  notifCool: Record<string, number>
  reports: Report[]
  settings: Settings
}
