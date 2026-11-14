export const API_BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? '/api/v1').replace(/\/$/, '')
const ROOT = API_BASE.replace(/\/api\/v1$/, '')

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string, readonly details?: unknown) {
    super(message)
  }
}

type Params = Record<string, string | number | boolean | null | undefined>

function url(path: string, params?: Params) {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params ?? {})) if (v !== null && v !== undefined && v !== '') qs.set(k, String(v))
  const s = qs.toString()
  return `${API_BASE}${path}${s ? `?${s}` : ''}`
}

async function send(path: string, opts: { method?: string; body?: unknown; params?: Params; signal?: AbortSignal } = {}) {
  let res: Response
  try {
    res = await fetch(url(path, opts.params), {
      method: opts.method ?? 'GET',
      headers: opts.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError('Cannot reach the LineZero API. Is the backend running?', 0, 'network_error')
  }
  if (!res.ok) {
    let body: { error?: { code?: string; message?: string; details?: unknown }; detail?: unknown } | null = null
    try { body = await res.json() } catch { body = null }
    throw new ApiError(body?.error?.message ?? res.statusText ?? 'Request failed', res.status, body?.error?.code, body?.error?.details ?? body?.detail)
  }
  return res
}

export async function api<T>(path: string, opts?: Parameters<typeof send>[1]): Promise<T> {
  const res = await send(path, opts)
  if (res.status === 204) return null as T
  return (await res.json()) as T
}

export async function apiBlob(path: string, params?: Params) {
  const res = await send(path, { params })
  const cd = res.headers.get('content-disposition') ?? ''
  const name = /filename="?([^";]+)"?/.exec(cd)?.[1]
  return { blob: await res.blob(), name }
}

export async function pingHealth(signal?: AbortSignal) {
  try {
    const r = await fetch(`${ROOT}/health`, { signal })
    return r.ok
  } catch {
    return false
  }
}

export const errMsg = (e: unknown) => (e instanceof Error ? e.message : 'Unexpected error')
