import { BarChart3, Gauge, GitFork, History, LayoutDashboard, Radio, Settings, SlidersHorizontal, type LucideIcon } from 'lucide-react'

export interface RouteDef { path: string; title: string; short: string; icon: LucideIcon; group: 'Operate' | 'Analyze' | 'Optimize' | 'System'; blurb: string }
export const ROUTES: RouteDef[] = [
  { path: 'dashboard', title: 'Dashboard', short: 'Dashboard', icon: LayoutDashboard, group: 'Operate', blurb: 'Queue intelligence overview' },
  { path: 'monitor', title: 'Live Queue Monitor', short: 'Live Monitor', icon: Radio, group: 'Operate', blurb: 'Manage queues, counters and customers' },
  { path: 'analytics', title: 'Queue Analytics', short: 'Analytics', icon: BarChart3, group: 'Analyze', blurb: 'Demand, waiting and service patterns' },
  { path: 'simulator', title: 'Queue Simulator', short: 'Simulator', icon: Gauge, group: 'Analyze', blurb: 'What-if queue simulation workspace' },
  { path: 'bottlenecks', title: 'Bottleneck Investigator', short: 'Bottlenecks', icon: GitFork, group: 'Analyze', blurb: 'Find where congestion originates' },
  { path: 'optimizer', title: 'Resource Optimizer', short: 'Optimizer', icon: SlidersHorizontal, group: 'Optimize', blurb: 'Compare current vs proposed allocation' },
  { path: 'reports', title: 'Reports & History', short: 'Reports', icon: History, group: 'System', blurb: 'Saved runs, snapshots and exports' },
  { path: 'settings', title: 'Settings', short: 'Settings', icon: Settings, group: 'System', blurb: 'Queues, counters and preferences' },
]
