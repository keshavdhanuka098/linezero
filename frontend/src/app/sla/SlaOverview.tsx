import { Bar, CartesianGrid, ComposedChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, BarChart } from 'recharts'
import { Activity, CheckCircle2, Clock, Hourglass, Users, XCircle } from 'lucide-react'
import type { SlaMonitor, SlaPerformance, Score } from '../../api/slaTypes'
import { num } from '../../lib/adaptive'
import { SLA_ORDER, SLA_STATUS, scoreText, scoreTone, trendRows } from '../../lib/sla'
import { Card, Chip, Kpi, Skeleton } from '../ui/kit'
import { C, ChartBox, ChartTooltip, Legend, axisProps, gridProps, useAnimate } from '../charts/theme'
import { KindTag, Note } from '../intelligence/shared'

const TONE_COLOR: Record<string, string> = { ok: '#20D6C5', warn: '#F5B84B', hot: '#FF8A4C', crit: '#FF5C6C' }

function Ring({ score, tone }: { score: number | null; tone: string | undefined }) {
  const r = 34, c = 2 * Math.PI * r
  const frac = score == null ? 0 : Math.max(0, Math.min(1, score / 100))
  return (
    <svg width="84" height="84" viewBox="0 0 84 84" role="img" aria-label={score == null ? 'No score' : `Score ${scoreText(score)} out of 100`}>
      <circle cx="42" cy="42" r={r} fill="none" stroke={C.grid} strokeWidth="8" />
      <circle cx="42" cy="42" r={r} fill="none" stroke={TONE_COLOR[tone ?? ''] ?? C.axis} strokeWidth="8" strokeLinecap="round"
        strokeDasharray={`${c * frac} ${c}`} transform="rotate(-90 42 42)" />
      <text x="42" y="47" textAnchor="middle" fill="currentColor" style={{ fontFamily: 'var(--font-h)', fontSize: 20, fontWeight: 700 }}>{scoreText(score)}</text>
    </svg>
  )
}

function ScoreCard({ title, score, n, kind, interval, sub }: { title: string; score: number | null; n: number; kind: 'observed' | 'predicted' | 'synthetic'; interval?: [number, number] | null; sub: string }) {
  const tone = scoreTone(score)
  return (
    <div className="sla-score" data-testid={`score-${title.split(' ')[0].toLowerCase()}`}>
      <Ring score={score} tone={tone} />
      <div>
        <div className="sla-score-h"><b>{title}</b><KindTag kind={kind} /></div>
        <div className="twin-note">{score == null ? 'No customers yet, so no score' : `${n} customer${n === 1 ? '' : 's'}`}{interval ? ` · 95% range ${interval[0].toFixed(0)}–${interval[1].toFixed(0)}` : ''}</div>
        <div className="twin-note">{sub}</div>
      </div>
    </div>
  )
}

const asKind = (_s: Score, synthetic: boolean): 'observed' | 'synthetic' => (synthetic ? 'synthetic' : 'observed')

export default function SlaOverview({ perf, mon, busy }: { perf: SlaPerformance | null; mon: SlaMonitor | null; busy: boolean }) {
  const animate = useAnimate()
  if (!perf) return <Skeleton h={320} />
  if (!perf.configured || !perf.scores || !perf.summary) return null
  const synth = perf.provenance.is_synthetic
  const sc = perf.scores, s = perf.summary
  const label = (sec: number) => new Date(sec * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const trend = trendRows(perf.trend ?? [], label)
  const classes = (perf.per_class ?? []).filter(c => c.n > 0 || c.target_min != null)
  const classBars = classes.map(c => ({ name: c.service_class, 'Average wait': c.avg_wait_min == null ? null : Number(c.avg_wait_min.toFixed(2)), 'P95 wait': c.p95_wait_min == null ? null : Number(c.p95_wait_min.toFixed(2)), Target: c.target_min }))
  const counts = mon?.counts

  return (
    <div className="iq-stack">
      <Card title="SLA compliance score" sub={sc.definition} right={busy ? <span className="twin-note">updating…</span> : undefined}>
        <div className="sla-scores">
          <ScoreCard title="Current compliance" score={sc.current.score} n={sc.current.n} kind={asKind(sc.current, synth)} interval={sc.current.interval95} sub={sc.current.label} />
          <ScoreCard title="Historical compliance" score={sc.historical.score} n={sc.historical.n} kind={asKind(sc.historical, synth)} interval={sc.historical.interval95} sub={sc.historical.label} />
          <ScoreCard title="Predicted compliance" score={sc.predicted?.score ?? null} n={sc.predicted?.n ?? 0} kind="predicted" sub={sc.predicted?.label ?? 'Customers waiting now'} />
        </div>
        <Note>Current and historical scores are measured from completed customers. The predicted score is a model estimate for the customers waiting now; it is not a measurement.</Note>
      </Card>

      <div className="grid g4 kp">
        <Kpi label="Overall compliance" icon={Activity} value={scoreText(sc.overall.score)} unit={sc.overall.score == null ? '' : '%'} tone={scoreTone(sc.overall.score) === 'crit' ? 'crit' : scoreTone(sc.overall.score) === 'hot' ? 'hot' : undefined} sub={sc.overall.label} />
        <Kpi label="Customers served" icon={Users} value={s.served} sub={`${s.abandoned} abandoned (not scored) · ${s.waiting_now ?? 0} waiting now`} />
        <Kpi label="Meeting SLA" icon={CheckCircle2} value={s.met_sla} sub={s.served ? `${((100 * s.met_sla) / s.served).toFixed(1)}% of served` : 'none served yet'} />
        <Kpi label="Breaching SLA" icon={XCircle} value={s.breached_sla} tone={s.breached_sla ? 'hot' : undefined} sub={s.avg_over_target_min ? `${num(s.avg_over_target_min, 1)} min over target on average` : 'none over target'} />
        <Kpi label="Average wait" icon={Clock} value={num(s.avg_wait_min, 1)} unit="min" sub={`P95 ${num(s.p95_wait_min, 1)} min`} />
        <Kpi label="Average target" icon={Hourglass} value={num(s.avg_target_min, 1)} unit="min" tone={s.avg_wait_min != null && s.avg_target_min != null && s.avg_wait_min > s.avg_target_min ? 'hot' : undefined}
          sub={s.avg_wait_min != null && s.avg_target_min != null ? (s.avg_wait_min <= s.avg_target_min ? `average wait is ${num(s.avg_target_min - s.avg_wait_min, 1)} min under target` : `average wait is ${num(s.avg_wait_min - s.avg_target_min, 1)} min over target`) : 'no data'} />
      </div>

      <div className="iq-two">
        <Card title="SLA breach trend" sub={`Per ${perf.window?.bucket_minutes} min, by when customers started service`} right={<KindTag kind={asKind(sc.overall, synth)} />}>
          {trend.every(b => b.served === 0) ? <Note>No completed customers in this period.</Note> : (
            <>
              <ChartBox h={250}><ResponsiveContainer><ComposedChart data={trend} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
                <CartesianGrid {...gridProps} /><XAxis dataKey="t" {...axisProps} interval="preserveStartEnd" />
                <YAxis yAxisId="l" domain={[0, 100]} {...axisProps} unit="%" /><YAxis yAxisId="r" orientation="right" allowDecimals={false} {...axisProps} />
                <Tooltip content={<ChartTooltip fmt={(v, n) => (n === 'Compliance' ? `${v.toFixed(1)}%` : `${v}`)} />} />
                <Bar yAxisId="r" dataKey="breached" name="Breaches" fill="#FF5C6C" opacity={0.55} isAnimationActive={animate} />
                <Line yAxisId="l" type="monotone" dataKey="score" name="Compliance" stroke={C.teal} strokeWidth={2} dot={{ r: 2 }} connectNulls={false} isAnimationActive={animate} />
              </ComposedChart></ResponsiveContainer></ChartBox>
              <Legend items={[{ label: 'Compliance % (line)', color: C.teal }, { label: 'Breaches (bars)', color: '#FF5C6C' }]} />
              <Note>Gaps mean no customer finished waiting in that period; they are not filled in.</Note>
            </>)}
        </Card>

        <Card title="Actual vs target waiting time" sub="Average wait of customers served, against the SLA target" right={<KindTag kind={asKind(sc.overall, synth)} />}>
          {trend.every(b => b.served === 0) ? <Note>No completed customers in this period.</Note> : (
            <>
              <ChartBox h={250}><ResponsiveContainer><LineChart data={trend} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
                <CartesianGrid {...gridProps} /><XAxis dataKey="t" {...axisProps} interval="preserveStartEnd" /><YAxis {...axisProps} unit=" m" />
                <Tooltip content={<ChartTooltip fmt={v => `${v.toFixed(1)} min`} />} />
                <Line type="monotone" dataKey="avgWait" name="Average wait" stroke={C.violet} strokeWidth={2} dot={{ r: 2 }} connectNulls={false} isAnimationActive={animate} />
                <Line type="stepAfter" dataKey="target" name="SLA target" stroke="#F5B84B" strokeDasharray="5 4" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={animate} />
              </LineChart></ResponsiveContainer></ChartBox>
              <Legend items={[{ label: 'Average wait', color: C.violet }, { label: 'SLA target', color: '#F5B84B', dashed: true }]} />
            </>)}
        </Card>
      </div>

      <div className="iq-two">
        <Card title="By service class" sub="Each customer is judged against the target of their own class">
          {classes.length === 0 ? <Note>No data.</Note> : (
            <>
              <ChartBox h={220}><ResponsiveContainer><BarChart data={classBars} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
                <CartesianGrid {...gridProps} /><XAxis dataKey="name" {...axisProps} /><YAxis {...axisProps} unit=" m" />
                <Tooltip content={<ChartTooltip fmt={v => `${v} min`} />} />
                <Bar dataKey="Average wait" fill={C.violet} isAnimationActive={animate} /><Bar dataKey="P95 wait" fill={C.teal} isAnimationActive={animate} />
                <Bar dataKey="Target" fill="#F5B84B" isAnimationActive={animate} />
              </BarChart></ResponsiveContainer></ChartBox>
              <div className="tw"><table className="tbl"><thead><tr><th>Class</th><th>Target</th><th>Served</th><th>Met</th><th>Breached</th><th>Score</th></tr></thead>
                <tbody>{classes.map(c => <tr key={c.service_class}><td>{c.service_class}</td><td className="mono">{c.target_min != null ? `${c.target_min} min` : '—'}</td><td className="mono">{c.n}</td><td className="mono">{c.met}</td><td className="mono">{c.breached}</td>
                  <td><Chip tone={scoreTone(c.score)}>{c.score == null ? 'no data' : `${scoreText(c.score)}%`}</Chip></td></tr>)}</tbody></table></div>
            </>)}
        </Card>
        <Card title="Waiting right now" sub="Prediction for customers still in line" right={<KindTag kind="predicted" />}>
          {!counts ? <Skeleton h={120} /> : (
            <>
              <div className="sla-dist" role="img" aria-label="Waiting customers by status">
                {SLA_ORDER.map(k => counts[k] > 0 && <div key={k} className={`sd ${k}`} style={{ flex: counts[k] }} title={`${SLA_STATUS[k].label}: ${counts[k]}`}>{counts[k]}</div>)}
                {SLA_ORDER.every(k => counts[k] === 0) && <div className="sd none">No customers waiting</div>}
              </div>
              <div className="iq-actions" style={{ marginTop: 8 }}>{SLA_ORDER.map(k => <Chip key={k} tone={SLA_STATUS[k].tone}>{SLA_STATUS[k].label}: {counts[k]}</Chip>)}</div>
              <Note>Statuses come from each customer’s breach probability against the thresholds set in Targets.</Note>
            </>)}
        </Card>
      </div>
      <Note>{perf.targets_note}</Note>
    </div>
  )
}
