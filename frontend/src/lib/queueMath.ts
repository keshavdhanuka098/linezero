export interface ErlangResult {
  lambda: number; mu: number; c: number
  rho: number
  stable: boolean
  pWait: number
  wq: number
  lq: number
}

export function erlangC(lambda: number, mu: number, c: number): ErlangResult {
  const base = { lambda, mu, c }
  if (lambda <= 0) return { ...base, rho: 0, stable: true, pWait: 0, wq: 0, lq: 0 }
  const a = lambda / mu
  const rho = a / c
  if (rho >= 1) return { ...base, rho, stable: false, pWait: 1, wq: Infinity, lq: Infinity }
  let term = 1, sum = 1
  for (let k = 1; k < c; k++) { term *= a / k; sum += term }
  const last = (term * a) / c
  const tail = last / (1 - rho)
  const pWait = tail / (sum + tail)
  const wq = pWait / (c * mu - lambda)
  return { ...base, rho, stable: true, pWait, wq, lq: lambda * wq }
}

export function probWaitWithin(r: ErlangResult, t: number): number {
  if (!r.stable) return 0
  return 1 - r.pWait * Math.exp(-(r.c * r.mu - r.lambda) * t)
}

export function allenCunneenWq(lambda: number, meanService: number, c: number, ca: number, cs: number): number {
  const r = erlangC(lambda, 1 / meanService, c)
  if (!r.stable) return Infinity
  return r.wq * ((ca * ca + cs * cs) / 2)
}

export const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x))
export const mean = (a: number[]) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0)
export const median = (a: number[]) => {
  if (!a.length) return 0
  const s = [...a].sort((x, y) => x - y), m = s.length >> 1
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}
