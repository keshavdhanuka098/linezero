export type Rand = () => number

export function hashStr(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) }
  return h >>> 0
}

export class Rng {
  private a: number
  constructor(seed: number) { this.a = seed >>> 0 }
  get seed() { return this.a }
  next = (): number => {
    this.a = (this.a + 0x6d2b79f5) >>> 0
    let t = this.a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function normal(r: Rand): number {
  const u = Math.max(r(), 1e-12), v = r()
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

export function gamma(r: Rand, shape: number): number {
  if (shape < 1) return gamma(r, shape + 1) * Math.pow(Math.max(r(), 1e-12), 1 / shape)
  const d = shape - 1 / 3, c = 1 / Math.sqrt(9 * d)
  for (;;) {
    let x: number, v: number
    do { x = normal(r); v = 1 + c * x } while (v <= 0)
    v = v * v * v
    const u = r()
    if (u < 1 - 0.0331 * x ** 4 || Math.log(Math.max(u, 1e-12)) < 0.5 * x * x + d * (1 - v + Math.log(v))) return d * v
  }
}

export function sampleCV(r: Rand, mean: number, cv: number): number {
  if (cv < 0.02) return mean
  const k = 1 / (cv * cv)
  return (gamma(r, k) * mean) / k
}

export function poisson(r: Rand, lambda: number): number {
  if (lambda <= 0) return 0
  if (lambda > 30) return Math.max(0, Math.round(lambda + Math.sqrt(lambda) * normal(r)))
  const L = Math.exp(-lambda)
  let k = 0, p = 1
  do { k++; p *= r() } while (p > L)
  return k - 1
}
