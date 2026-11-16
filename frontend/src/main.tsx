import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'
import './styles/tokens.css'
import './styles/app.css'

createRoot(document.getElementById('root')!).render(<StrictMode><BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><App /></BrowserRouter></StrictMode>)

// Dismiss the branded boot screen as soon as React has painted its first frame (no artificial delay).
requestAnimationFrame(() => requestAnimationFrame(() => {
  const boot = document.getElementById('boot')
  if (!boot) return
  boot.classList.add('done')
  window.setTimeout(() => boot.remove(), 300)
}))
