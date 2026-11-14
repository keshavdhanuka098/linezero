import type { Counter, Queue } from '../store/types'
import { Rng, hashStr, normal } from './rng'
import { allenCunneenWq, clamp } from './queueMath'
import { demandProfile, dowFactor } from './metrics'

export interface Cell {
  date: string; dow: number; hour: number; queueId: string
  arrivals: number; served: number; abandoned: number | null
  wMu: number; wSigma: number; sMu: number; sSigma: number; util: number
}
export const DATASET_DAYS = 90
export const HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17]

const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
export const parseYmd = (s: string) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d) }
export function datasetRange() { const end = new Date(); end.setHours(0, 0, 0, 0); end.setDate(end.getDate() - 1); const start = new Date(end); start.setDate(start.getDate() - (DATASET_DAYS - 1)); return { start: ymd(start), end: ymd(end) } }

export function tracksAbandonment(q: Queue) { return q.id !== 'q-billing' }

export function generateDataset(queues: Queue[], counters: Counter[]): Cell[] {
  const { start } = datasetRange(), s0 = parseYmd(start), out: Cell[] = []
  for (const q of queues) {
    const cs = counters.filter(c => c.queueId === q.id)
    const capPerMin = cs.reduce((a, c) => a + c.servers / c.avgService, 0) || 0.2
    const nServers = Math.max(1, cs.reduce((a, c) => a + c.servers, 0))
    const svcMean = cs.length ? cs.reduce((a, c) => a + c.avgService * c.servers, 0) / nServers : 4
    for (let d = 0; d < DATASET_DAYS; d++) {
      const day = new Date(s0); day.setDate(s0.getDate() + d)
      const dow = day.getDay(), ds = ymd(day)
      const trend = 1 + 0.0015 * d
      for (const h of HOURS) {
        const r = new Rng(hashStr(`${q.id}|${ds}|${h}`))
        const lam = Math.max(0, q.arrivalRate * 60 * demandProfile(h) * dowFactor(dow) * trend * (1 + 0.14 * normal(r.next)))
        const arrivals = Math.round(lam)
        const rho = clamp((arrivals / 60) / capPerMin, 0, 3)
        const wq = allenCunneenWq(Math.min(arrivals / 60, capPerMin * 0.97) || 1e-6, svcMean, nServers, 1, 0.6)
        const congestion = rho > 0.97 ? (rho - 0.97) * 28 : 0
        const wMean = Math.max(0.2, (Number.isFinite(wq) ? wq : 20) + congestion) * (1 + 0.1 * normal(r.next))
        const sM = svcMean * (1 + 0.04 * normal(r.next))
        const pAb = clamp((wMean - 6) / 70, 0, 0.3)
        const abandoned = tracksAbandonment(q) ? Math.round(arrivals * pAb * (0.8 + 0.4 * r.next())) : null
        out.push({
          date: ds, dow, hour: h, queueId: q.id, arrivals, abandoned, served: arrivals - (abandoned ?? 0),
          wMu: Math.log(wMean) - 0.32, wSigma: 0.8, sMu: Math.log(sM) - 0.125, sSigma: 0.5, util: clamp(rho * (1 + 0.04 * normal(r.next)), 0, 0.99),
        })
      }
    }
  }
  return out
}

function erf(x: number) { const s = Math.sign(x); x = Math.abs(x); const t = 1 / (1 + 0.3275911 * x); return s * (1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x)) }
const lnCdf = (x: number, mu: number, sg: number) => (x <= 0 ? 0 : 0.5 * (1 + erf((Math.log(x) - mu) / (sg * Math.SQRT2))))

export const WAIT_BINS = [0, 2, 5, 10, 15, 20, 30, Infinity]
export const SVC_BINS = [0, 2, 4, 6, 8, 12, 20, Infinity]
const binLabel = (b: number[], i: number) => (b[i + 1] === Infinity ? `${b[i]}+` : `${b[i]}–${b[i + 1]}`)

export interface Filters { start: string; end: string; queueIds: string[]; target: number }
export interface Analytics {
  cells: number
  totals: { arrivals: number; served: number; avgWait: number; avgService: number; efficiency: number; util: number; abandonRate: number | null; days: number }
  hourly: { hour: number; label: string; arrivals: number; avgWait: number; peak: boolean }[]
  daily: { date: string; label: string; arrivals: number; avgWait: number; ma7: number; abandon: number | null }[]
  waitHist: { bin: string; customers: number; beyondTarget: boolean }[]
  svcHist: { bin: string; customers: number }[]
  heat: { dow: number; hour: number; v: number }[]
  heatMax: number
  peaks: { hour: number; arrivals: number }[]
  perQueue: { id: string; name: string; arrivals: number; avgWait: number; efficiency: number; abandonRate: number | null }[]
  counterUtil: { name: string; queue: string; util: number }[]
}

export function aggregate(all: Cell[], f: Filters, queues: Queue[], counters: Counter[]): Analytics {
  const sel = new Set(f.queueIds)
  const cells = all.filter(c => c.date >= f.start && c.date <= f.end && sel.has(c.queueId))
  const days = new Set(cells.map(c => c.date)).size || 1
  const meanOf = (mu: number, sg: number) => Math.exp(mu + (sg * sg) / 2)
  let arr = 0, served = 0, wSum = 0, sSum = 0, within = 0, uSum = 0, abN = 0, abA = 0
  const wBins = new Array(WAIT_BINS.length - 1).fill(0), sBins = new Array(SVC_BINS.length - 1).fill(0)
  const hourAgg = new Map<number, { a: number; w: number }>(), dayAgg = new Map<string, { a: number; w: number; ab: number; abA: number }>()
  const heat = new Map<string, number>(), qAgg = new Map<string, { a: number; w: number; within: number; ab: number; abA: number }>()
  for (const c of cells) {
    arr += c.arrivals; served += c.served
    const wm = meanOf(c.wMu, c.wSigma), sm = meanOf(c.sMu, c.sSigma)
    wSum += wm * c.arrivals; sSum += sm * c.served; uSum += c.util
    const wi = c.arrivals * lnCdf(f.target, c.wMu, c.wSigma); within += wi
    for (let i = 0; i < wBins.length; i++) wBins[i] += c.arrivals * (lnCdf(WAIT_BINS[i + 1], c.wMu, c.wSigma) - lnCdf(WAIT_BINS[i], c.wMu, c.wSigma))
    for (let i = 0; i < sBins.length; i++) sBins[i] += c.served * (lnCdf(SVC_BINS[i + 1], c.sMu, c.sSigma) - lnCdf(SVC_BINS[i], c.sMu, c.sSigma))
    const h = hourAgg.get(c.hour) ?? { a: 0, w: 0 }; h.a += c.arrivals; h.w += wm * c.arrivals; hourAgg.set(c.hour, h)
    const d = dayAgg.get(c.date) ?? { a: 0, w: 0, ab: 0, abA: 0 }; d.a += c.arrivals; d.w += wm * c.arrivals; if (c.abandoned !== null) { d.ab += c.abandoned; d.abA += c.arrivals }; dayAgg.set(c.date, d)
    const k = `${c.dow}-${c.hour}`; heat.set(k, (heat.get(k) ?? 0) + c.arrivals)
    const q = qAgg.get(c.queueId) ?? { a: 0, w: 0, within: 0, ab: 0, abA: 0 }; q.a += c.arrivals; q.w += wm * c.arrivals; q.within += wi; if (c.abandoned !== null) { q.ab += c.abandoned; q.abA += c.arrivals }; qAgg.set(c.queueId, q)
    if (c.abandoned !== null) { abN += c.abandoned; abA += c.arrivals }
  }
  const dowCount = new Array(7).fill(0)
  Array.from(new Set(cells.map(c => c.date))).forEach(d => dowCount[parseYmd(d).getDay()]++)
  const hourly = HOURS.map(h => { const x = hourAgg.get(h) ?? { a: 0, w: 0 }; return { hour: h, label: `${String(h).padStart(2, '0')}:00`, arrivals: Math.round((x.a / days) * 10) / 10, avgWait: x.a ? x.w / x.a : 0, peak: false } })
  const mean = hourly.reduce((a, x) => a + x.arrivals, 0) / hourly.length
  hourly.forEach(x => { x.peak = mean > 0 && x.arrivals >= mean * 1.25 })
  const peaks = [...hourly].sort((a, b) => b.arrivals - a.arrivals).filter(x => x.peak).slice(0, 3).map(x => ({ hour: x.hour, arrivals: x.arrivals }))
  const dayKeys = [...dayAgg.keys()].sort()
  const daily = dayKeys.map((k, i) => {
    const x = dayAgg.get(k)!, win = dayKeys.slice(Math.max(0, i - 6), i + 1).map(z => dayAgg.get(z)!.a)
    const dd = parseYmd(k)
    return { date: k, label: `${dd.getDate()} ${dd.toLocaleString('en', { month: 'short' })}`, arrivals: x.a, avgWait: x.a ? x.w / x.a : 0, ma7: Math.round(win.reduce((a, b) => a + b, 0) / win.length), abandon: x.abA ? x.ab / x.abA : null }
  })
  const heatArr: Analytics['heat'] = []
  let heatMax = 0
  for (let d = 0; d < 7; d++) for (const h of HOURS) { const v = dowCount[d] ? (heat.get(`${d}-${h}`) ?? 0) / dowCount[d] : 0; heatArr.push({ dow: d, hour: h, v }); heatMax = Math.max(heatMax, v) }
  const perQueue = queues.filter(q => sel.has(q.id)).map(q => { const x = qAgg.get(q.id); return { id: q.id, name: q.name, arrivals: x?.a ?? 0, avgWait: x?.a ? x.w / x.a : 0, efficiency: x?.a ? x.within / x.a : 0, abandonRate: tracksAbandonment(q) && x?.abA ? x.ab / x.abA : null } })
  const dsDays = days
  const counterUtil = counters.filter(c => sel.has(c.queueId)).map(c => {
    const q = queues.find(z => z.id === c.queueId)!, cs = counters.filter(z => z.queueId === c.queueId)
    const share = q.routing === 'weighted' ? c.routeWeight / cs.reduce((a, z) => a + z.routeWeight, 0) : (c.servers / c.avgService) / cs.reduce((a, z) => a + z.servers / z.avgService, 0)
    const lamPerMin = ((qAgg.get(q.id)?.a ?? 0) / dsDays) / HOURS.length / 60
    return { name: c.name.replace('Counter ', '').replace(/ \(.*\)/, ''), queue: q.name, util: clamp((lamPerMin * share * c.avgService) / c.servers, 0, 1) }
  })
  return {
    cells: cells.length,
    totals: { arrivals: arr, served, avgWait: arr ? wSum / arr : 0, avgService: served ? sSum / served : 0, efficiency: arr ? within / arr : 0, util: cells.length ? uSum / cells.length : 0, abandonRate: abA ? abN / abA : null, days: new Set(cells.map(c => c.date)).size },
    hourly, daily, peaks, heat: heatArr, heatMax, perQueue, counterUtil,
    waitHist: wBins.map((v, i) => ({ bin: binLabel(WAIT_BINS, i), customers: Math.round(v), beyondTarget: WAIT_BINS[i] >= f.target })),
    svcHist: sBins.map((v, i) => ({ bin: binLabel(SVC_BINS, i), customers: Math.round(v) })),
  }
}
