import { useMemo, useState } from 'react'
import { Archive, Download, Eye, FileText, FileDown, Plus, Search, Trash2 } from 'lucide-react'
import { useStore } from '../../store/store'
import type { Report, ReportStatus, ReportType } from '../../store/types'
import { downloadCsv, downloadPdf } from '../../lib/exporters'
import { demoTimeLabel, fmtMin, pct, systemMetrics, queueMetrics, queueRisk } from '../../lib/metrics'
import { Card, Chip, Confirm, DemoBadge, EmptyState, Modal, PageHeader, Seg, Spinner, toast } from '../ui/kit'
import ServerReports from '../server/ServerReports'
import { useServerMode } from '../../api/serverStore'

const TYPES: Record<ReportType, string> = { simulation: 'Simulation run', metrics: 'Queue metrics', bottleneck: 'Bottleneck report', optimization: 'Optimization comparison' }
const STATUS_TONE: Record<ReportStatus, 'ok' | 'vio' | undefined> = { Completed: 'ok', Reviewed: 'vio', Archived: undefined }
const fmtDate = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
const fileBase = (r: Report) => `linezero-${r.type}-${r.createdAt.slice(0, 10)}-${r.id.slice(-4)}`

function ReportsLocal() {
  const s = useStore()
  const [q, setQ] = useState(''), [type, setType] = useState<'all' | ReportType>('all'), [status, setStatus] = useState<'all' | ReportStatus>('all'), [sort, setSort] = useState<'new' | 'old'>('new')
  const [view, setView] = useState<Report | null>(null), [del, setDel] = useState<Report | null>(null), [busy, setBusy] = useState<string | null>(null)
  const list = useMemo(() => {
    const t = q.trim().toLowerCase()
    return s.reports.filter(r => (type === 'all' || r.type === type) && (status === 'all' || r.status === status) && (!t || (r.title + ' ' + TYPES[r.type]).toLowerCase().includes(t)))
      .sort((a, b) => (sort === 'new' ? b.createdAt.localeCompare(a.createdAt) : a.createdAt.localeCompare(b.createdAt)))
  }, [s.reports, q, type, status, sort])

  const flat = (r: Report) => (r.rows.length ? r.rows : Object.entries(r.summary).map(([k, v]) => ({ Metric: k, Value: v })))
  const csv = (r: Report) => downloadCsv(`${fileBase(r)}.csv`, [...Object.entries(r.summary).map(([k, v]) => ({ Section: 'Summary', Field: k, Value: v })), ...flat(r).filter(() => r.rows.length).map(x => ({ Section: 'Detail', ...x }))])
  const pdf = async (r: Report) => {
    setBusy(r.id)
    try { await downloadPdf(`${fileBase(r)}.pdf`, r.title, `${TYPES[r.type]} · ${fmtDate(r.createdAt)} · ${r.synthetic ? 'synthetic demo data' : 'live data'}`, [{ heading: 'Summary', rows: Object.entries(r.summary).map(([k, v]) => [k, v] as [string, string | number]) }, ...(r.rows.length ? [{ heading: 'Detail', table: r.rows.slice(0, 60) }] : [])]); toast('PDF downloaded') }
    catch (e) { console.error(e); toast('Could not generate the PDF', true) } finally { setBusy(null) }
  }
  const snapshot = () => {
    const sys = systemMetrics(s)
    s.addReport({ type: 'metrics', title: `Metrics snapshot ${demoTimeLabel(s.clock, s.settings.timeFormat)}`, status: 'Completed', synthetic: true,
      summary: { 'People waiting': sys.waiting, 'Avg wait (min)': +sys.avgWait.toFixed(2), 'Avg service (min)': +sys.avgService.toFixed(2), Utilization: pct(sys.util), 'Risk score': sys.risk },
      rows: s.queues.map(qu => { const m = queueMetrics(qu, s.counters); return { Queue: qu.name, Waiting: m.waiting, 'Est wait': fmtMin(m.estWait), Utilization: pct(m.util), Risk: queueRisk(qu, s.counters, s.history, s.settings.thresholds) } }) })
    toast('Metrics snapshot saved')
  }

  return (
    <div className="page">
      <PageHeader title="Reports & History" sub="Saved simulation runs, metrics snapshots, bottleneck reports and optimization comparisons.">
        <button className="btn" onClick={() => downloadCsv('linezero-reports-index.csv', list.map(r => ({ ID: r.id, Title: r.title, Type: TYPES[r.type], 'Date & time': fmtDate(r.createdAt), Status: r.status, Source: r.synthetic ? 'Synthetic demo' : 'Live' })))} disabled={!list.length}><Download size={16} />Export list (CSV)</button>
        <button className="btn p" onClick={snapshot}><Plus size={16} />New metrics snapshot</button>
      </PageHeader>
      <Card>
        <div className="toolbar" style={{ justifyContent: 'space-between' }}>
          <div className="toolbar" style={{ minWidth: 0, maxWidth: '100%' }}>
            <label className="search" style={{ cursor: 'text', minWidth: 0, width: 'min(260px, 100%)', justifyContent: 'flex-start' }}><Search size={16} /><input className="in" style={{ border: 0, background: 'none', height: 36, padding: 0, boxShadow: 'none' }} placeholder="Search reports…" aria-label="Search reports" value={q} onChange={e => setQ(e.target.value)} /></label>
            <Seg<'all' | ReportType> value={type} onChange={setType} label="Report type" options={[{ v: 'all', l: 'All' }, { v: 'simulation', l: 'Simulations' }, { v: 'metrics', l: 'Metrics' }, { v: 'bottleneck', l: 'Bottlenecks' }, { v: 'optimization', l: 'Optimization' }]} />
          </div>
          <div className="toolbar">
            <select className="sel" style={{ width: 150 }} aria-label="Status" value={status} onChange={e => setStatus(e.target.value as 'all' | ReportStatus)}><option value="all">All statuses</option><option>Completed</option><option>Reviewed</option><option>Archived</option></select>
            <select className="sel" style={{ width: 150 }} aria-label="Sort" value={sort} onChange={e => setSort(e.target.value as 'new' | 'old')}><option value="new">Newest first</option><option value="old">Oldest first</option></select>
          </div>
        </div>
      </Card>
      <Card>
        {s.reports.length === 0 ? <EmptyState icon={FileText} title="No reports yet" text="Save a simulation run, bottleneck review or optimization comparison — or take a metrics snapshot — and it will appear here." action={<button className="btn p" onClick={snapshot}><Plus size={16} />Create metrics snapshot</button>} />
          : list.length === 0 ? <EmptyState icon={Search} title="No reports match" text="Adjust the search or filters." action={<button className="btn" onClick={() => { setQ(''); setType('all'); setStatus('all') }}>Clear filters</button>} />
          : <div className="tw"><table className="tbl"><thead><tr><th>Report</th><th>Type</th><th>Date & time</th><th>Status</th><th>Source</th><th style={{ textAlign: 'right' }}>Actions</th></tr></thead><tbody>
            {list.map(r => (
              <tr key={r.id}>
                <td style={{ maxWidth: 320 }}><b style={{ fontWeight: 500 }}>{r.title}</b></td>
                <td><Chip tone="vio">{TYPES[r.type]}</Chip></td>
                <td style={{ whiteSpace: 'nowrap', color: 'var(--muted)' }}>{fmtDate(r.createdAt)}</td>
                <td><select className="sel" style={{ width: 116, height: 30, fontSize: 12 }} aria-label={`Status of ${r.title}`} value={r.status} onChange={e => { s.updateReport(r.id, { status: e.target.value as ReportStatus }); toast('Status updated') }}><option>Completed</option><option>Reviewed</option><option>Archived</option></select><span style={{ display: 'none' }}>{STATUS_TONE[r.status]}</span></td>
                <td>{r.synthetic ? <DemoBadge label="Synthetic" /> : <Chip tone="ok">Live</Chip>}</td>
                <td><div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
                  <button className="btn sm g ic" title="View" aria-label={`View ${r.title}`} onClick={() => setView(r)}><Eye size={15} /></button>
                  <button className="btn sm g ic" title="Export CSV" aria-label={`Export ${r.title} as CSV`} onClick={() => csv(r)}><FileDown size={15} /></button>
                  <button className="btn sm g" title="Export PDF" aria-label={`Export ${r.title} as PDF`} onClick={() => pdf(r)} disabled={busy === r.id}>{busy === r.id ? <Spinner size={14} /> : <Download size={15} />}PDF</button>
                  <button className="btn sm g ic" title="Archive" aria-label={`Archive ${r.title}`} onClick={() => { s.updateReport(r.id, { status: 'Archived' }); toast('Report archived') }} disabled={r.status === 'Archived'}><Archive size={15} /></button>
                  <button className="btn sm g ic" title="Delete" aria-label={`Delete ${r.title}`} onClick={() => setDel(r)}><Trash2 size={15} /></button>
                </div></td>
              </tr>))}
          </tbody></table></div>}
      </Card>
      {view && (
        <Modal large title={view.title} sub={`${TYPES[view.type]} · ${fmtDate(view.createdAt)} · ${view.status}${view.synthetic ? ' · synthetic demo data' : ''}`} onClose={() => setView(null)}
          footer={<><button className="btn" onClick={() => csv(view)}><FileDown size={16} />CSV</button><button className="btn p" onClick={() => pdf(view)} disabled={busy === view.id}>{busy === view.id ? <Spinner size={14} /> : <Download size={16} />}PDF</button></>}>
          <div className="kv">{Object.entries(view.summary).map(([k, v]) => <div key={k}><small>{k}</small><b>{String(v)}</b></div>)}</div>
          {view.rows.length > 0 ? <div className="tw" style={{ maxHeight: 320 }}><table className="tbl"><thead><tr>{Object.keys(view.rows[0]).map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>{view.rows.slice(0, 50).map((r, i) => <tr key={i}>{Object.keys(view.rows[0]).map(c => <td key={c}>{String(r[c] ?? '')}</td>)}</tr>)}</tbody></table></div> : <div className="hint">This report has a summary only.</div>}
          {view.rows.length > 50 && <div className="hint">Showing the first 50 of {view.rows.length} rows — export for the full set.</div>}
        </Modal>
      )}
      {del && <Confirm title="Delete report?" text={`“${del.title}” will be permanently removed.`} onClose={() => setDel(null)} onConfirm={() => { s.deleteReport(del.id); toast('Report deleted') }} />}
    </div>
  )
}

export default function Reports() {
  return useServerMode() ? <ServerReports /> : <ReportsLocal />
}
