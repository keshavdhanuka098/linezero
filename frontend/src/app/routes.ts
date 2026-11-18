import { BarChart3, Timer, Brain, Cpu, Crosshair, ShieldAlert, Wand2, Gauge, GitFork, History, LayoutDashboard, Radio, Settings, SlidersHorizontal, type LucideIcon } from 'lucide-react'

export interface RouteDef { path: string; title: string; short: string; icon: LucideIcon; group: 'Operate' | 'Analyze' | 'Optimize' | 'Intelligence' | 'System'; blurb: string }
export const ROUTES: RouteDef[] = [
  { path: 'dashboard', title: 'Dashboard', short: 'Dashboard', icon: LayoutDashboard, group: 'Operate', blurb: 'Queue intelligence overview' },
  { path: 'monitor', title: 'Live Queue Monitor', short: 'Live Monitor', icon: Radio, group: 'Operate', blurb: 'Manage queues, counters and customers' },
  { path: 'sla-intelligence', title: 'SLA Intelligence', short: 'SLA', icon: Timer, group: 'Operate', blurb: 'Breach prediction, customer risk and compliance' },
  { path: 'analytics', title: 'Queue Analytics', short: 'Analytics', icon: BarChart3, group: 'Analyze', blurb: 'Demand, waiting and service patterns' },
  { path: 'simulator', title: 'Queue Simulator', short: 'Simulator', icon: Gauge, group: 'Analyze', blurb: 'What-if queue simulation workspace' },
  { path: 'bottlenecks', title: 'Bottleneck Investigator', short: 'Bottlenecks', icon: GitFork, group: 'Analyze', blurb: 'Find where congestion originates' },
  { path: 'optimizer', title: 'Resource Optimizer', short: 'Optimizer', icon: SlidersHorizontal, group: 'Optimize', blurb: 'Compare current vs proposed allocation' },
  { path: 'digital-twin', title: 'Digital Twin', short: 'Digital Twin', icon: Cpu, group: 'Optimize', blurb: 'Predict, simulate, stress-test and recover' },
  { path: 'adaptive-intelligence', title: 'Adaptive Intelligence', short: 'Adaptive', icon: Brain, group: 'Intelligence', blurb: 'Self-learning twin: calibration, drift, versions' },
  { path: 'risk-radar', title: 'Operational Risk Radar', short: 'Risk Radar', icon: ShieldAlert, group: 'Intelligence', blurb: 'Predict and explain operational risks' },
  { path: 'interventions', title: 'Autonomous Interventions', short: 'Interventions', icon: Wand2, group: 'Intelligence', blurb: 'Simulated, costed recoveries for operator approval' },
  { path: 'outcome-learning', title: 'Outcome Learning', short: 'Outcomes', icon: Crosshair, group: 'Intelligence', blurb: 'Expected vs observed results; recalibration signal' },
  { path: 'reports', title: 'Reports & History', short: 'Reports', icon: History, group: 'System', blurb: 'Saved runs, snapshots and exports' },
  { path: 'settings', title: 'Settings', short: 'Settings', icon: Settings, group: 'System', blurb: 'Queues, counters and preferences' },
]
