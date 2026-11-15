import { lazy } from 'react'
import { Navigate, Route, Routes, Link } from 'react-router-dom'
import Landing from './landing/Landing'
import AppShell from './app/shell/AppShell'
import { EmptyState } from './app/ui/kit'
import { Compass } from 'lucide-react'

const Dashboard = lazy(() => import('./app/pages/Dashboard'))
const Monitor = lazy(() => import('./app/pages/Monitor'))
const Analytics = lazy(() => import('./app/pages/Analytics'))
const Simulator = lazy(() => import('./app/pages/Simulator'))
const Bottlenecks = lazy(() => import('./app/pages/Bottlenecks'))
const Optimizer = lazy(() => import('./app/pages/Optimizer'))
const DigitalTwin = lazy(() => import('./app/twin/TwinPage'))
const Reports = lazy(() => import('./app/pages/Reports'))
const Settings = lazy(() => import('./app/pages/Settings'))

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/app" element={<AppShell />}>
        <Route index element={<Navigate to="dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="monitor" element={<Monitor />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="simulator" element={<Simulator />} />
        <Route path="bottlenecks" element={<Bottlenecks />} />
        <Route path="optimizer" element={<Optimizer />} />
        <Route path="digital-twin" element={<DigitalTwin />} />
        <Route path="reports" element={<Reports />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<div className="page"><div className="card"><EmptyState icon={Compass} title="Page not found" text="That part of LineZero doesn’t exist." action={<Link className="btn p" to="/app/dashboard">Back to dashboard</Link>} /></div></div>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
