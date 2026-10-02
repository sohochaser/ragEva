import { Ban, Link2, Play, Plus, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { fetchDatasets, fetchVersions, type DatasetSummary, type VersionSummary } from '../api/datasets'
import { addTarget, cancelTargetJob, fetchTargetJob, fetchTargetJobCases, fetchTargetJobs, fetchTargets, startTargetJob, testTarget, type Target, type TargetJob, type TargetJobCase, type TargetTest } from '../api/targets'

type EvaluationType = 'answer' | 'retrieval' | 'both'

export function TargetPage() {
  const [targets, setTargets] = useState<Target[]>([])
  const [jobs, setJobs] = useState<TargetJob[]>([])
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [versions, setVersions] = useState<VersionSummary[]>([])
  const [targetId, setTargetId] = useState('')
  const [datasetId, setDatasetId] = useState('')
  const [datasetVersion, setDatasetVersion] = useState(1)
  const [evaluationType, setEvaluationType] = useState<EvaluationType>('both')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [timeout, setTimeoutValue] = useState(30)
  const [retries, setRetries] = useState(1)
  const [maxConcurrency, setMaxConcurrency] = useState(4)
  const [protocol, setProtocol] = useState<'json' | 'sse'>('json')
  const [caseId, setCaseId] = useState('probe')
  const [question, setQuestion] = useState('')
  const [testResult, setTestResult] = useState<TargetTest | null>(null)
  const [selectedJobId, setSelectedJobId] = useState('')
  const [jobCases, setJobCases] = useState<TargetJobCase[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    try {
      const [targetItems, jobItems, datasetItems] = await Promise.all([fetchTargets(), fetchTargetJobs(), fetchDatasets()])
      setTargets(targetItems); setJobs(jobItems); setDatasets(datasetItems)
      setTargetId((current) => current || targetItems[0]?.id || '')
      setDatasetId((current) => current || datasetItems[0]?.id || '')
      setSelectedJobId((current) => current || jobItems[0]?.id || '')
      setError('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '无法读取目标') }
  }, [])

  useEffect(() => { void reload() }, [reload])
  useEffect(() => {
    if (!datasetId) return
    let active = true
    void fetchVersions(datasetId).then((items) => {
      if (active) { setVersions(items); setDatasetVersion(items[0]?.version ?? 1) }
    }).catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '无法读取版本') })
    return () => { active = false }
  }, [datasetId])
  useEffect(() => {
    if (!selectedJobId) return
    let active = true
    const refresh = async () => {
      try {
        const [job, cases] = await Promise.all([fetchTargetJob(selectedJobId), fetchTargetJobCases(selectedJobId)])
        if (active) { setJobs((items) => items.map((item) => item.id === job.id ? job : item)); setJobCases(cases) }
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : '无法读取采集任务') }
    }
    void refresh()
    const interval = window.setInterval(() => void refresh(), 2000)
    return () => { active = false; window.clearInterval(interval) }
  }, [selectedJobId])

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const target = await addTarget({ name: name.trim(), url: url.trim(), bearer_token: token || null, timeout_seconds: timeout, retries, max_concurrency: maxConcurrency, protocol })
      setTargets((items) => [target, ...items]); setTargetId(target.id)
      setName(''); setUrl(''); setToken('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '保存目标失败') }
    finally { setBusy(false) }
  }

  async function probe(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(''); setTestResult(null)
    try { setTestResult(await testTarget(targetId, caseId, question, evaluationType)) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '连接测试失败') }
    finally { setBusy(false) }
  }

  async function collect() {
    setBusy(true); setError('')
    try {
      const job = await startTargetJob({ target_id: targetId, dataset_id: datasetId, dataset_version: datasetVersion, evaluation_type: evaluationType })
      setJobs((items) => [job, ...items]); setSelectedJobId(job.id)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '启动采集失败') }
    finally { setBusy(false) }
  }

  async function cancelCollection() {
    if (!selectedJobId) return
    setBusy(true); setError('')
    try {
      const job = await cancelTargetJob(selectedJobId)
      setJobs((items) => items.map((item) => item.id === job.id ? job : item))
    } catch (cause) { setError(cause instanceof Error ? cause.message : '取消采集失败') }
    finally { setBusy(false) }
  }

  const selectedTarget = targets.find((item) => item.id === targetId)
  const selectedJob = jobs.find((item) => item.id === selectedJobId)
  return <>
    <header className="page-header"><div><p className="eyebrow">WORKSPACE</p><h1>HTTP 目标</h1></div><button type="button" className="refresh-button" title="刷新目标" aria-label="刷新目标" onClick={() => void reload()}><RefreshCw size={17} /></button></header>
    <form className="target-create" onSubmit={(event) => void create(event)}>
      <label className="form-group"><span className="form-label">名称</span><input value={name} required onChange={(event) => setName(event.target.value)} /></label>
      <label className="form-group"><span className="form-label">接口 URL</span><input type="url" value={url} required placeholder="https://..." onChange={(event) => setUrl(event.target.value)} /></label>
      <label className="form-group"><span className="form-label">Bearer Token</span><input type="password" value={token} autoComplete="off" onChange={(event) => setToken(event.target.value)} /></label>
      <label className="form-group"><span className="form-label">响应协议</span><select value={protocol} onChange={(event) => setProtocol(event.target.value as 'json' | 'sse')}><option value="json">JSON</option><option value="sse">SSE</option></select></label>
      <label className="form-group"><span className="form-label">超时 / 秒</span><input type="number" min="1" max="120" value={timeout} onChange={(event) => setTimeoutValue(Number(event.target.value))} /></label>
      <label className="form-group"><span className="form-label">重试</span><input type="number" min="0" max="3" value={retries} onChange={(event) => setRetries(Number(event.target.value))} /></label>
      <label className="form-group"><span className="form-label">并发请求</span><input type="number" min="1" max="8" value={maxConcurrency} onChange={(event) => setMaxConcurrency(Number(event.target.value))} /></label>
      <button type="submit" className="primary-button" disabled={busy}><Plus size={15} />保存</button>
    </form>
    {error && <p className="page-error" role="alert">{error}</p>}
    <div className="dataset-layout target-layout"><aside className="dataset-list" aria-label="HTTP 目标列表"><div className="pane-heading"><h2>目标</h2><span>{targets.length}</span></div>{targets.map((item) => <button type="button" className={`dataset-row ${targetId === item.id ? 'active' : ''}`} key={item.id} onClick={() => { setTargetId(item.id); setTestResult(null) }}><strong>{item.name}</strong><span>{item.url}</span></button>)}</aside><section className="dataset-workspace" aria-label="目标详情">{selectedTarget ? <>
      <div className="dataset-toolbar"><div><h2>{selectedTarget.name}</h2><span>{selectedTarget.url} · {selectedTarget.protocol.toUpperCase()}</span></div><span className="target-auth">{selectedTarget.has_token ? 'Bearer 已配置' : '无认证'}</span></div>
      <form className="target-probe" onSubmit={(event) => void probe(event)}><div className="section-heading"><h2>连接测试</h2></div><div className="target-probe-fields"><label className="form-group"><span className="form-label">case_id</span><input value={caseId} required onChange={(event) => setCaseId(event.target.value)} /></label><label className="form-group"><span className="form-label">问题</span><input value={question} required onChange={(event) => setQuestion(event.target.value)} /></label><button type="submit" className="secondary-button" disabled={busy}><Link2 size={15} />测试</button></div>{testResult && <p className={testResult.success ? 'target-success' : 'form-error'} role="status">{testResult.success ? '连接成功' : `连接失败：${testResult.error}`}{testResult.attempts.length > 1 ? ` · ${testResult.attempts.length} 次尝试` : ''}</p>}</form>
      <section className="target-collection"><div className="section-heading"><h2>批量采集</h2></div><div className="target-collection-fields"><label className="form-group"><span className="form-label">数据集</span><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>{datasets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="form-group"><span className="form-label">版本</span><select value={datasetVersion} onChange={(event) => setDatasetVersion(Number(event.target.value))}>{versions.map((item) => <option key={item.id} value={item.version}>v{item.version}</option>)}</select></label><label className="form-group"><span className="form-label">评测类型</span><select value={evaluationType} onChange={(event) => setEvaluationType(event.target.value as EvaluationType)}><option value="both">答案 + 检索</option><option value="retrieval">检索</option><option value="answer">答案</option></select></label><button type="button" className="primary-button" disabled={busy || !datasetId || !versions.length} onClick={() => void collect()}><Play size={15} />采集预测</button></div></section>
    </> : <div className="empty-state">暂无目标</div>}</section></div>
    <section className="target-jobs" aria-label="采集任务"><div className="section-heading"><h2>采集任务</h2><span>{jobs.length}</span></div><div className="target-job-list">{jobs.map((job) => <button type="button" key={job.id} className={`target-job-row ${selectedJobId === job.id ? 'active' : ''}`} onClick={() => setSelectedJobId(job.id)}><strong>{targets.find((item) => item.id === job.target_id)?.name ?? job.target_id}</strong><span>{job.status} · {job.processed_count}/{job.total_count}</span></button>)}</div>{selectedJob && <div className="target-job-detail"><div className="section-heading"><h2>任务 {selectedJob.id.slice(0, 8)}</h2><span>成功 {selectedJob.success_count} · 失败 {selectedJob.failed_count} · 取消 {selectedJob.cancelled_count ?? 0}</span></div><div className="target-job-controls"><span>预计最多 {selectedJob.estimated_external_calls ?? 0} 次请求</span>{['queued', 'running'].includes(selectedJob.status) && <button type="button" className="secondary-button" disabled={busy || selectedJob.cancel_requested} onClick={() => void cancelCollection()}><Ban size={15} />{selectedJob.cancel_requested ? '取消中' : '取消采集'}</button>}</div>{selectedJob.batch_id && <p>预测批次 <code>{selectedJob.batch_id}</code></p>}{jobCases.map((item) => <div className="target-job-case" key={item.case_id}><code>{item.case_id}</code><span>{item.status}</span><span>{item.error ?? ''}</span><small>{item.attempts?.length ?? 0} 次尝试</small></div>)}</div>}</section>
  </>
}
