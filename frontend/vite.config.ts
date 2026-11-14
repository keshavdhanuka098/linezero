import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_PROXY || 'http://127.0.0.1:8000'
  const proxy = { '/api': { target, changeOrigin: true }, '/health': { target, changeOrigin: true } }
  return {
    plugins: [react()],
    build: { chunkSizeWarningLimit: 900 },
    server: { proxy },
    preview: { proxy },
    test: { include: ['src/**/*.test.ts'] },
  }
})
