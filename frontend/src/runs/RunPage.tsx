import { Ban, ChevronLeft, ChevronRight, Download, Play, RefreshCw, RotateCcw, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'

import { fetchPredictionBatches, type PredictionBatchSummary } from '../api/predictions'
import { cancelRun, createRun, exportRunUrl, fetchRun, fetchRunCases, fetchRuns, rescoreRun, type CaseStatus, type RunCasesPage, type RunSummary } from '../api/runs'
import { fetchModels, fetchScenarios, fetchScenarioVersions, type OnlineModel, type Scenario } from '../api/scenarios'
import { fetchRunUsage, type UsageSummary } from '../api/usage'
import { UsagePanel } from '../usage/UsagePanel'
import { TraceLink } from '../trace/TraceLink'
import { uiError } from '../ui/text'
import { RunAggregateView, RunCaseDetail } from './RunResults'

const statusLabels: Record<string, string> = {
  queued: 'Queued（排队中）', running: 'Running（运行中）', completed: 'Completed（已完成）', failed: 'Failed（失败）', cancelled: 'Cancelled（已取消）',
  pending: 'Pending（待处理）', success: 'Succeeded（成功）', not_applicable: 'Not Applicable（不适用）',
}
const modeLabels: Record<string, string> = { retrieval: 'Retrieval（检索）', answer: 'Answer（回答）', both: 'Retrieval + Answer（检索 + 回答）' }

export function RunPage() {
  const formRef = useRef<HTMLFormElement>(null)
  const [batches, setBatches] = useState<PredictionBatchSummary[]>([])
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [scenarioVersions, setScenarioVersions] = useState<Scenario[]>([])
  const [judgeModels, setJudgeModels] = useState<OnlineModel[]>([])
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selected, setSelected] = useState<RunSummary | null>(null)
  const [rescoreSource, setRescoreSource] = useState<RunSummary | null>(null)
  const [cases, setCases] = useState<RunCasesPage | null>(null)
  const [usage, setUsage] = useState<UsageSummary | null>(null)
  const [offset, setOffset] = useState(0)
  const [caseStatus, setCaseStatus] = useState<CaseStatus | ''>('')
  const [caseId, setCaseId] = useState<string | null>(null)
  const [batchId, setBatchId] = useState('')
  const [mode, setMode] = useState<'retrieval' | 'answer' | 'both'>('retrieval')
  const [scenarioId, setScenarioId] = useState('')
  const [scenarioVersion, setScenarioVersion] = useState(1)
  const [judgeModelId, setJudgeModelId] = useState('')
  const [modelName, setModelName] = useState('BAAI/bge-small-zh-v1.5')
  const [modelPath, setModelPath] = useState('')
  const [threshold, setThreshold] = useState(0.8)
  const [offline, setOffline] = useState(false)
  const [metrics, setMetrics] = useState<Array<'precision' | 'map' | 'ndcg'>>(['precision', 'map', 'ndcg'])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    try {
      const [runItems, batchItems, scenarioItems, modelItems] = await Promise.all([fetchRuns(), fetchPredictionBatches(), fetchScenarios(), fetchModels()])
      setRuns(runItems)
      setBatches(batchItems)
      setScenarios(scenarioItems); setJudgeModels(modelItems)
      setScenarioId((current) => current || scenarioItems[0]?.scenario_id || '')
      setJudgeModelId((current) => current || modelItems[0]?.id || '')
      setBatchId((current) => current || batchItems.find((item) => item.evaluation_type !== 'answer')?.id || '')
      setSelectedId((current) => current && runItems.some((item) => item.id === current) ? current : runItems[0]?.id ?? null)
      setError('')
    } catch (cause) { setError(uiError(cause, 'Unable to load runs', '无法读取运行')) }
  }, [])

  useEffect(() => { void reload() }, [reload])
  useEffect(() => {
    const matching = batches.filter((item) => item.evaluation_type === 'both' || item.evaluation_type === mode)
    setBatchId((current) => matching.some((item) => item.id === current) ? current : matching[0]?.id || '')
  }, [batches, mode])
  useEffect(() => {
    if (!scenarioId) { setScenarioVersions([]); return }
    let active = true
    void fetchScenarioVersions(scenarioId).then((items) => {
      if (active) {
        setScenarioVersions(items)
        const sourceAnswer = rescoreSource?.config.answer as { scenario_id?: string; scenario_version?: number } | null | undefined
        const sourceVersion = sourceAnswer?.scenario_id === scenarioId ? sourceAnswer.scenario_version : undefined
        setScenarioVersion(sourceVersion && items.some((item) => item.version === sourceVersion) ? sourceVersion : items[0]?.version ?? 1)
      }
    }).catch((cause: unknown) => { if (active) setError(uiError(cause, 'Unable to load scenario versions', '无法读取场景版本')) })
    return () => { active = false }
  }, [scenarioId, rescoreSource])
  useEffect(() => {
    if (!selectedId) { setSelected(null); setCases(null); setUsage(null); return }
    let active = true
    const refresh = async () => {
      try {
        const [run, page, tokenUsage] = await Promise.all([fetchRun(selectedId), fetchRunCases(selectedId, offset, caseStatus), fetchRunUsage(selectedId)])
        if (active) { setSelected(run); setCases(page); setUsage(tokenUsage); setCaseId((current) => current && page.cases.some((item) => item.case_id === current) ? current : page.cases[0]?.case_id ?? null); setRuns((items) => items.map((item) => item.id === run.id ? run : item)) }
      } catch (cause) { if (active) setError(uiError(cause, 'Unable to load run', '无法读取运行')) }
    }
    void refresh()
    const interval = window.setInterval(() => void refresh(), 2000)
    return () => { active = false; window.clearInterval(interval) }
  }, [selectedId, offset, caseStatus])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true); setError('')
    try {
      const config = { mode, scenario_id: mode === 'retrieval' ? null : scenarioId, scenario_version: mode === 'retrieval' ? null : scenarioVersion, judge_model_id: mode === 'retrieval' ? null : judgeModelId, model_name: modelName.trim(), model_path: modelPath.trim() || null, threshold, offline, metrics }
      const run = rescoreSource
        ? await rescoreRun(rescoreSource.id, config)
        : await createRun({ prediction_batch_id: batchId, ...config, match_rule_version: 'one-to-one-v1', gain_rule_version: 'ordered-linear-v1' })
      setRescoreSource(null)
      setRuns((items) => [run, ...items]); setSelectedId(run.id); setSelected(run); setOffset(0)
    } catch (cause) { setError(uiError(cause, 'Unable to start evaluation', '无法启动评测')) }
    finally { setBusy(false) }
  }

  async function cancel() {
    if (!selected) return
    try { setSelected(await cancelRun(selected.id)); setError('') }
    catch (cause) { setError(uiError(cause, 'Cancellation failed', '取消失败')) }
  }

  function prepareRescore(source: RunSummary) {
    const config = source.config
    const answer = config.answer as { scenario_id?: string; scenario_version?: number; judge_model_id?: string } | null | undefined
    setRescoreSource(source)
    setBatchId(source.prediction_batch_id)
    setMode((config.mode as typeof mode) || 'retrieval')
    setScenarioId(answer?.scenario_id || '')
    setScenarioVersion(answer?.scenario_version || 1)
    setJudgeModelId(answer?.judge_model_id || '')
    setModelName(String(config.model_name || 'BAAI/bge-small-zh-v1.5'))
    setModelPath(String(config.model_path || ''))
    setThreshold(Number(config.threshold ?? 0.8))
    setOffline(Boolean(config.offline))
    setMetrics((config.metrics as typeof metrics) || ['precision', 'map', 'ndcg'])
    setError('')
    formRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }

  const selectedCase = cases?.cases.find((item) => item.case_id === caseId)
  const availableBatches = batches.filter((item) => item.evaluation_type === 'both' || item.evaluation_type === mode)
  const selectedConfig = selected?.config
  const selectedAnswer = selectedConfig?.answer as { scenario_version?: number; model_name?: string } | null | undefined

  return <>
    <header className="page-header"><div><p className="eyebrow">Workspace（工作台）</p><h1>Evaluation Runs（评测运行）</h1></div><button type="button" className="refresh-button" title="Refresh Runs（刷新运行）" aria-label="Refresh Runs（刷新运行）" onClick={() => void reload()}><RefreshCw size={17} /></button></header>
    <form ref={formRef} className="run-form" onSubmit={(event) => void submit(event)}>
      {rescoreSource && <div className="rescore-context"><span>Rescore Run（复评运行） {rescoreSource.id.slice(0, 8)}</span><button type="button" className="icon-button" title="Exit Rescore（退出复评）" aria-label="Exit Rescore（退出复评）" onClick={() => setRescoreSource(null)}><X size={16} /></button></div>}
      <label className="form-group"><span className="form-label">Evaluation Mode（评测模式）</span><select value={mode} disabled={!!rescoreSource} onChange={(event) => setMode(event.target.value as typeof mode)}><option value="retrieval">Retrieval（检索）</option><option value="answer">Answer（回答）</option><option value="both">Retrieval + Answer（检索 + 回答）</option></select></label>
      <label className="form-group"><span className="form-label">Prediction Batches（预测批次）</span><select value={batchId} required disabled={!!rescoreSource} onChange={(event) => setBatchId(event.target.value)}>{availableBatches.map((batch) => <option key={batch.id} value={batch.id}>{batch.source_filename} · v{batch.dataset_version}</option>)}</select></label>
      {mode !== 'answer' && <><label className="form-group"><span className="form-label">Embedding Model（向量模型）</span><input value={modelName} required onChange={(event) => setModelName(event.target.value)} /></label><label className="form-group"><span className="form-label">Model Directory（模型目录）</span><input value={modelPath} placeholder="Default Download Cache（默认下载缓存）" onChange={(event) => setModelPath(event.target.value)} /></label><label className="form-group"><span className="form-label">Similarity Threshold（相似度阈值）</span><input type="number" min="-1" max="1" step="0.01" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} /></label><label className="offline-option"><input type="checkbox" checked={offline} onChange={(event) => setOffline(event.target.checked)} />Local Models Only（仅本地模型）</label><fieldset className="run-metrics"><legend>Retrieval Metrics（检索指标）</legend>{(['precision', 'map', 'ndcg'] as const).map((metric) => <label key={metric}><input type="checkbox" checked={metrics.includes(metric)} onChange={(event) => setMetrics((current) => event.target.checked ? [...current, metric] : current.filter((item) => item !== metric))} />{metric === 'precision' ? 'Precision（精确率）' : metric === 'map' ? 'MAP（平均精确率均值）' : 'NDCG（归一化折损累计增益）'}</label>)}</fieldset></>}
      {mode !== 'retrieval' && <><label className="form-group"><span className="form-label">Evaluation Scenarios（评价场景）</span><select value={scenarioId} required onChange={(event) => setScenarioId(event.target.value)}>{scenarios.map((item) => <option key={item.scenario_id} value={item.scenario_id}>{item.name}</option>)}</select></label><label className="form-group"><span className="form-label">Scenario Version（场景版本）</span><select value={scenarioVersion} onChange={(event) => setScenarioVersion(Number(event.target.value))}>{scenarioVersions.map((item) => <option key={item.id} value={item.version}>v{item.version}</option>)}</select></label><label className="form-group"><span className="form-label">Judge Model（评分模型）</span><select value={judgeModelId} required onChange={(event) => setJudgeModelId(event.target.value)}>{judgeModels.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.model_name}</option>)}</select></label></>}
      <button type="submit" className="primary-button" disabled={!batchId || (mode !== 'answer' && !metrics.length) || (mode !== 'retrieval' && (!scenarioId || !judgeModelId)) || busy}>{rescoreSource ? <RotateCcw size={15} /> : <Play size={15} />}{busy ? 'Submitting（提交中）' : rescoreSource ? 'Rescore（重新评分）' : 'Run Evaluation（运行评测）'}</button>
    </form>
    {error && <p className="page-error" role="alert">{error}</p>}
    <div className="dataset-layout run-layout">
      <aside className="dataset-list" aria-label="Run List（运行列表）"><div className="pane-heading"><h2>Previous Runs（历史运行）</h2><span>{runs.length}</span></div>{runs.map((run) => <button key={run.id} type="button" className={`dataset-row ${selectedId === run.id ? 'active' : ''}`} onClick={() => { setSelectedId(run.id); setOffset(0) }}><strong>{batches.find((item) => item.id === run.prediction_batch_id)?.source_filename ?? run.id.slice(0, 8)}</strong><span>{statusLabels[run.status] ?? run.status} · {run.processed_count}/{run.total_count}</span></button>)}</aside>
      <section className="dataset-workspace" aria-label="Run Details（运行详情）">{selected ? <>
        <div className="dataset-toolbar"><div><h2>Run（运行） {selected.id.slice(0, 8)}</h2><span>{statusLabels[selected.status] ?? selected.status} · {selected.processed_count}/{selected.total_count} cases（题）</span></div><div className="run-actions"><a className="secondary-button" href={exportRunUrl(selected.id, 'csv', caseStatus)} download>CSV <Download size={15} />Export（导出）</a><a className="secondary-button" href={exportRunUrl(selected.id, 'json', caseStatus)} download>JSON <Download size={15} />Export（导出）</a>{['completed', 'failed', 'cancelled'].includes(selected.status) && <button type="button" className="secondary-button" onClick={() => prepareRescore(selected)}><RotateCcw size={15} />Rescore（复评）</button>}{['queued', 'running'].includes(selected.status) && <button type="button" className="secondary-button" onClick={() => void cancel()}><Ban size={15} />Cancel（取消）</button>}</div></div>
        <div className="run-config"><span>{modeLabels[String(selectedConfig?.mode || 'retrieval')]} · {selected.prediction_batch_id.slice(0, 8)}</span>{selectedConfig?.mode !== 'answer' && <span>{String(selectedConfig?.model_name || '')} · Threshold（阈值） {String(selectedConfig?.threshold ?? '')} · {String(selectedConfig?.match_rule_version || '')}</span>}{selectedAnswer && <span>Scenario（场景） v{selectedAnswer.scenario_version} · {selectedAnswer.model_name}</span>}{typeof selectedConfig?.rescore_of_run_id === 'string' && <button type="button" onClick={() => setSelectedId(selectedConfig.rescore_of_run_id as string)}>Source Run（源运行） {selectedConfig.rescore_of_run_id.slice(0, 8)}</button>}{Boolean(selectedConfig?.reuse_retrieval_from_run_id) && <span>Reuse Existing Retrieval Decisions（复用已有检索判定）</span>}</div>
        <div className="run-summary"><span>Succeeded（成功） {selected.success_count}</span><span>Failed（失败） {selected.failed_count}</span><span>Not Applicable（不适用） {selected.not_applicable_count}</span><span>Cancel（取消） {selected.cancelled_count}</span><span>Estimated Judge Calls（预计评分调用） {selected.estimated_external_calls ?? 0}</span></div>
        <div className="trace-links"><TraceLink trace={selected.trace} label="Evaluation Trace（评测 trace）" /><TraceLink trace={selected.prediction_trace} label="Prediction Batch Trace（预测批次 trace）" /><TraceLink trace={selected.dataset_trace} label="Dataset Version Trace（数据集版本 trace）" /></div>
        <RunAggregateView run={selected} />
        <UsagePanel usage={usage} />
        <div className="run-case-workspace"><div className="run-case-list"><div className="pane-heading"><h3>Per-Case Results（逐题结果）</h3><select aria-label="Filter Status（筛选状态）" value={caseStatus} onChange={(event) => { setCaseStatus(event.target.value as CaseStatus | ''); setOffset(0) }}><option value="">All（全部） · {selected.total_count}</option>{(['success', 'failed', 'not_applicable', 'pending', 'cancelled'] as const).map((status) => <option key={status} value={status}>{statusLabels[status]}</option>)}</select></div>{cases?.cases.map((item) => <button type="button" className={`run-case-row ${item.case_id === caseId ? 'active' : ''}`} key={item.case_id} onClick={() => setCaseId(item.case_id)}><code>{item.case_id}</code><span>{statusLabels[item.status] ?? item.status}</span>{item.error && <small>{item.error}</small>}</button>)}{cases?.total === 0 && <p className="preview-empty">No Matches（无匹配结果）</p>}</div>{selectedCase ? <RunCaseDetail key={selectedCase.case_id} item={selectedCase} /> : <div className="empty-detail">Select Case（选择样本）</div>}</div>
        {cases && cases.total > cases.limit && <div className="pagination"><button type="button" title="Previous Page（上一页）" aria-label="Previous Page（上一页）" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - cases.limit))}><ChevronLeft size={16} /></button><span>{Math.floor(offset / cases.limit) + 1} / {Math.ceil(cases.total / cases.limit)}</span><button type="button" title="Next Page（下一页）" aria-label="Next Page（下一页）" disabled={offset + cases.limit >= cases.total} onClick={() => setOffset(offset + cases.limit)}><ChevronRight size={16} /></button></div>}
      </> : <div className="empty-state">No Runs Yet（暂无运行）</div>}</section>
    </div>
  </>
}
