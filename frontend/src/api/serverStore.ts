import { create } from 'zustand'
import { api, pingHealth } from './client'
import type { ApiQueue } from './types'

type Status = 'checking' | 'online' | 'offline'
type Mode = 'browser' | 'server'

const KEY = 'lz.source'
const stored = (): Mode | null => { try { const v = localStorage.getItem(KEY); return v === 'server' || v === 'browser' ? v : null } catch { return null } }
const write = (m: Mode) => { try { localStorage.setItem(KEY, m) } catch {} }

interface ServerState {
  mode: Mode
  status: Status
  queues: ApiQueue[]
  queueId: number | null
  setMode(m: Mode): void
  setQueueId(id: number): void
  refresh(): Promise<void>
}

export const useServer = create<ServerState>((set, get) => ({
  mode: stored() ?? 'browser',
  status: 'checking',
  queues: [],
  queueId: null,
  setMode: m => { write(m); set({ mode: m }) },
  setQueueId: id => set({ queueId: id }),
  refresh: async () => {
    const ok = await pingHealth()
    if (!ok) { set({ status: 'offline' }); return }
    try {
      const queues = await api<ApiQueue[]>('/queues')
      const cur = get().queueId
      if (stored() === null && get().status !== 'online') set({ mode: 'server' })
      set({ status: 'online', queues, queueId: cur !== null && queues.some(q => q.id === cur) ? cur : queues[0]?.id ?? null })
    } catch {
      set({ status: 'offline' })
    }
  },
}))

export const useServerMode = () => useServer(s => s.mode === 'server' && s.status === 'online')

let started = false
export function startServerPolling() {
  if (started) return
  started = true
  void useServer.getState().refresh()
  window.setInterval(() => { if (!document.hidden) void useServer.getState().refresh() }, 20000)
}
