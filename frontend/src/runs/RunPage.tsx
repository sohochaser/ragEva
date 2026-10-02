import { Ban, ChevronLeft, ChevronRight, Play, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { fetchPredictionBatches, type PredictionBatchSummary } from '../api/predictions'
import { cancelRun, createRun, fetchRun, fetchRunCases, fetchRuns, type RunCasesPage, type RunSummary } from '../api/runs'

const statusLabels: Record<string, string> = {
  queued: '排队中', running: '运行中', completed: '已完成', failed: '部分失败', cancelled: '已取消',
  pending: '待处理', success: '成功', not_applicable: '不适用',
}

export function RunPage() {
  const [batches, setBatches] = useState<PredictionBatchSummary[]>([])
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selected, setSelected] = useState<RunSummary | null>(null)
  const [cases, setCases] = useState<RunCasesPage | null>(null)
  const [offset, setOffset] = useState(0)
  const [batchId, setBatchId] = useState('')
  const [modelName, setModelName] = useState('BAAI/bge-small-zh-v1.5')
  const [modelPath, setModelPath] = useState('')
  const [threshold, setThreshold] = useState(0.8)
  const [offline, setOffline] = useState(false)
  const [metrics, setMetrics] = useState<Array<'precision' | 'map' | 'ndcg'>>(['precision', 'map', 'ndcg'])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    try {
      const [runItems, batchItems] = await Promise.all([fetchRuns(), fetchPredictionBatches()])
      setRuns(runItems)
      setBatches(batchItems.filter((item) => item.evaluation_type !== 'answer'))
      setBatchId((current) => current || batchItems.find((item) => item.evaluation_type !== 'answer')?.id || '')
      setSelectedId((current) => current && runItems.some((item) => item.id === current) ? current : runItems[0]?.id ?? null)
      setError('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '无法读取运行') }
  }, [])

  useEffect(() => { void reload() }, [reload])
  useEffect(() => {
    if (!selectedId) { setSelected(null); setCases(null); return }
    let active = true
    const refresh = async () => {
      try {
        const [run, page] = await Promise.all([fetchRun(selectedId), fetchRunCases(selectedId, offset)])
        if (active) { setSelected(run); setCases(page); setRuns((items) => items.map((item) => item.id === run.id ? run : item)) }
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : '无法读取运行') }
    }
    void refresh()
    const interval = window.setInterval(() => void refresh(), 2000)
    return () => { active = false; window.clearInterval(interval) }
  }, [selectedId, offset])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true); setError('')
    try {
      const run = await createRun({ prediction_batch_id: batchId, model_name: modelName.trim(), model_path: modelPath.trim() || null, threshold, offline, metrics })
      setRuns((items) => [run, ...items]); setSelectedId(run.id); setSelected(run); setOffset(0)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '无法启动评测') }
    finally { setBusy(false) }
  }

  async function cancel() {
    if (!selected) return
    try { setSelected(await cancelRun(selected.id)); setError('') }
    catch (cause) { setError(cause instanceof Error ? cause.message : '取消失败') }
  }

  return <>
    <header className="page-header"><div><p className="eyebrow">WORKSPACE</p><h1>评测运行</h1></div><button type="button" className="refresh-button" title="刷新运行" aria-label="刷新运行" onClick={() => void reload()}><RefreshCw size={17} /></button></header>
    <form className="run-form" onSubmit={(event) => void submit(event)}>
      <label className="form-group"><span className="form-label">预测批次</span><select value={batchId} required onChange={(event) => setBatchId(event.target.value)}>{batches.map((batch) => <option key={batch.id} value={batch.id}>{batch.source_filename} · v{batch.dataset_version}</option>)}</select></label>
      <label className="form-group"><span className="form-label">向量模型</span><input value={modelName} required onChange={(event) => setModelName(event.target.value)} /></label>
      <label className="form-group"><span className="form-label">模型目录</span><input value={modelPath} placeholder="默认下载缓存" onChange={(event) => setModelPath(event.target.value)} /></label>
      <label className="form-group"><span className="form-label">相似度阈值</span><input type="number" min="-1" max="1" step="0.01" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} /></label>
      <label className="offline-option"><input type="checkbox" checked={offline} onChange={(event) => setOffline(event.target.checked)} />仅本地模型</label>
      <fieldset className="run-metrics"><legend>指标</legend>{(['precision', 'map', 'ndcg'] as const).map((metric) => <label key={metric}><input type="checkbox" checked={metrics.includes(metric)} onChange={(event) => setMetrics((current) => event.target.checked ? [...current, metric] : current.filter((item) => item !== metric))} />{metric === 'precision' ? 'Precision' : metric === 'map' ? 'MAP' : 'NDCG'}</label>)}</fieldset>
      <button type="submit" className="primary-button" disabled={!batchId || !metrics.length || busy}><Play size={15} />{busy ? '提交中' : '运行评测'}</button>
    </form>
    {error && <p className="page-error" role="alert">{error}</p>}
    <div className="dataset-layout run-layout">
      <aside className="dataset-list" aria-label="运行列表"><div className="pane-heading"><h2>历史运行</h2><span>{runs.length}</span></div>{runs.map((run) => <button key={run.id} type="button" className={`dataset-row ${selectedId === run.id ? 'active' : ''}`} onClick={() => { setSelectedId(run.id); setOffset(0) }}><strong>{batches.find((item) => item.id === run.prediction_batch_id)?.source_filename ?? run.id.slice(0, 8)}</strong><span>{statusLabels[run.status] ?? run.status} · {run.processed_count}/{run.total_count}</span></button>)}</aside>
      <section className="dataset-workspace" aria-label="运行详情">{selected ? <>
        <div className="dataset-toolbar"><div><h2>运行 {selected.id.slice(0, 8)}</h2><span>{statusLabels[selected.status] ?? selected.status} · {selected.processed_count}/{selected.total_count} 题</span></div>{['queued', 'running'].includes(selected.status) && <button type="button" className="secondary-button" onClick={() => void cancel()}><Ban size={15} />取消</button>}</div>
        <div className="run-summary"><span>成功 {selected.success_count}</span><span>失败 {selected.failed_count}</span><span>不适用 {selected.not_applicable_count}</span><span>取消 {selected.cancelled_count}</span></div>
        <div className="run-case-list"><div className="pane-heading"><h3>逐题状态</h3><span>{cases?.total ?? 0}</span></div>{cases?.cases.map((item) => <div className="run-case-row" key={String(item.case_id)}><code>{String(item.case_id)}</code><span>{statusLabels[String(item.status)] ?? String(item.status)}</span>{Boolean(item.error) && <small>{String(item.error)}</small>}</div>)}</div>
        {cases && cases.total > cases.limit && <div className="pagination"><button type="button" title="上一页" aria-label="上一页" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - cases.limit))}><ChevronLeft size={16} /></button><span>{Math.floor(offset / cases.limit) + 1} / {Math.ceil(cases.total / cases.limit)}</span><button type="button" title="下一页" aria-label="下一页" disabled={offset + cases.limit >= cases.total} onClick={() => setOffset(offset + cases.limit)}><ChevronRight size={16} /></button></div>}
      </> : <div className="empty-state">暂无运行</div>}</section>
    </div>
  </>
}
