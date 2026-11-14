export type Errors<T extends string = string> = Partial<Record<T, string>>
export const hasErrors = (e: object) => Object.keys(e).length > 0

export function numberIn(v: unknown, min: number, max: number, label: string, int = false): string | undefined {
  if (v === '' || v === null || v === undefined) return `${label} is required`
  const n = Number(v)
  if (!Number.isFinite(n)) return `${label} must be a number`
  if (int && !Number.isInteger(n)) return `${label} must be a whole number`
  if (n < min || n > max) return `${label} must be between ${min} and ${max}`
  return undefined
}
export function nameValid(v: string, existing: string[], label = 'Name', max = 40): string | undefined {
  const t = v.trim()
  if (!t) return `${label} is required`
  if (t.length > max) return `${label} must be ${max} characters or fewer`
  if (existing.some(x => x.trim().toLowerCase() === t.toLowerCase())) return `${label} already exists`
  return undefined
}
