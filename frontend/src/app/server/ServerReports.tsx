import { useState } from 'react'
import { Download, Eye, FilePlus } from 'lucide-react'
import { api, apiBlob, errMsg } from '../../api/client'
import type { ReportFull, ReportSummary } from '../../api/types'
import { useServer } from '../../api/serverStore'
import { Card, Chip, EmptyState, Field, Modal, PageHeader, Spinner, toast } from '../ui/kit'
import { Async, download, useAsync } from './shared'

const TYPES: Record<string, string> = { queue_performance: 'Queue performance', bottleneck_analysis: 'Bottleneck analysis', prediction_evaluation: 'Prediction evaluation', simulation_results: 'Simulation results', optimization_comparison: 'Optimization comparison' }
const NEEDS_QUEUE = new Set(['queue_performance', 'bottleneck_analysis', 'prediction_evaluation'])
const fmtDate = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

export default function ServerReports() {
  const queueId = useServer(s => s.queueId), queues = useServer(s => s.queues), setQueueId = useServer(s => s.setQueueId)
  const [type, setType] = useState('queue_performance')
  const [busy, setBusy] = useState(false)
  const [view, setView] = useState<ReportFull | null>(null)
  const list = useAsync(() => api<ReportSummary[]>('/reports', { params: { limit: 100 } }), [])

  const generate = async () => {
    setBusy(true)
    try {
      const body: Record<string, unknown> = { report_type: type }
      if (NEEDS_QUEUE.has(type)) body.queue_id = queueId
      if (type === 'simulation_results') {
        const runs = await api<{ id: number }[]>('/simulations', { params: { limit: 1 } })
        if (!runs.length) throw new Error('Run a simulation first.')
        body.simulation_id = runs[0].id
      }
      await api('/reports/generate', { method: 'POST', body })
      toast('Report generated'); void list.reload()
    } catch (e) { toast(errMsg(e), true) } finally { setBusy(false) }
  }
  const open = async (id: number) => { try { setView(await api<ReportFull>(`/reports/${id}`)) } catch (e) { toast(errMsg(e), true) } }
  const exp = async (id: number, format: 'csv' | 'json' | 'pdf') => {
    try { const { blob, name } = await apiBlob(`/reports/${id}/export`, { format }); download(blob, name ?? `linezero-report-${id}.${format}`) } catch (e) { toast(errMsg(e), true) }
  }

  return (
    <div className="page">
      <PageHeader title="Reports & History" sub="Reports generated and stored by the LineZero API, exportable as CSV, JSON or PDF." demo={false} />
      <Card>
        <div className="toolbar" style={{ alignItems: 'flex-end', gap: 18 }}>
          <Field label="Report type"><select className="sel" value={type} onChange={e => setType(e.target.value)}>{Object.entries(TYPES).filter(([k]) => k !== 'optimization_comparison').map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          {NEEDS_QUEUE.has(type) && <Field label="Queue"><select className="sel" style={{ minWidth: 240 }} value={queueId ?? ''} onChange={e => setQueueId(Number(e.target.value))}>{queues.map(q => <option key={q.id} value={q.id}>{q.name}</option>)}</select></Field>}
          <button className="btn p" onClick={generate} disabled={busy || (NEEDS_QUEUE.has(type) && queueId === null)}>{busy ? <Spinner /> : <FilePlus size={16} />}Generate report</button>
        </div>
      </Card>
      <Card title="Stored reports">
        <Async loading={list.loading} error={list.error} onRetry={list.reload} hasData={!!list.data}>
          {list.data && list.data.length === 0 ? <EmptyState title="No reports yet" text="Generate one above." /> : (
            <div className="tw"><table className="tbl"><thead><tr><th>#</th><th>Title</th><th>Type</th><th>Created</th><th>Data</th><th /></tr></thead><tbody>
              {list.data?.map(r => (
                <tr key={r.report_id}><td className="mono">{r.report_id}</td><td>{r.title ?? '—'}</td><td>{TYPES[r.report_type] ?? r.report_type}</td><td>{fmtDate(r.created_at)}</td>
                  <td>{r.contains_synthetic_data ? <Chip tone="demo">SYNTHETIC</Chip> : <Chip tone="ok">RECORDED</Chip>}</td>
                  <td><div className="toolbar" style={{ gap: 4 }}>
                    <button className="btn sm" onClick={() => open(r.report_id)}><Eye size={14} />View</button>
                    {(['csv', 'json', 'pdf'] as const).map(f => <button key={f} className="btn sm g" onClick={() => exp(r.report_id, f)} aria-label={`Export ${f.toUpperCase()}`}><Download size={13} />{f.toUpperCase()}</button>)}
                  </div></td></tr>
              ))}
            </tbody></table></div>
          )}
        </Async>
      </Card>
      {view && (
        <Modal large title={view.title ?? `Report #${view.report_id}`} sub={`${TYPES[view.report_type] ?? view.report_type} · ${fmtDate(view.created_at)}`} onClose={() => setView(null)}>
          {view.report_data.meta.data_notice && <div className="banner"><span>{view.report_data.meta.data_notice}</span></div>}
          <div className="tw"><table className="tbl"><tbody>
            {Object.entries(view.report_data.summary).filter(([, v]) => typeof v !== 'object' || v === null).map(([k, v]) => <tr key={k}><td>{k.replace(/_/g, ' ')}</td><td className="mono">{typeof v === 'number' ? Math.round(v * 100) / 100 : String(v ?? '—')}</td></tr>)}
          </tbody></table></div>
          {Object.entries(view.report_data.tables).map(([name, t]) => (
            <div key={name} style={{ marginTop: 14 }}>
              <h4 className="hd">{name.replace(/_/g, ' ')}</h4>
              <div className="tw"><table className="tbl"><thead><tr>{t.columns.map(c => <th key={c}>{c.replace(/_/g, ' ')}</th>)}</tr></thead><tbody>
                {t.rows.slice(0, 40).map((row, i) => <tr key={i}>{row.map((c, j) => <td key={j} className="mono">{typeof c === 'number' ? Math.round(c * 100) / 100 : String(c ?? '—')}</td>)}</tr>)}
              </tbody></table></div>
            </div>
          ))}
        </Modal>
      )}
    </div>
  )
}
