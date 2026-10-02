import { Ban, Link2, Play, Plus, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { TraceLink } from '../trace/TraceLink'

import { fetchDatasets, fetchVersions, type DatasetSummary, type VersionSummary } from '../api/datasets'
import { addTarget, cancelTargetJob, fetchTargetJob, fetchTargetJobCases, fetchTargetJobs, fetchTargets, startTargetJob, testTarget, type Target, type TargetJob, type TargetJobCase, type TargetTest } from '../api/targets'
import { uiError } from '../ui/text'

type EvaluationType = 'answer' | 'retrieval' | 'both'
const jobStatus: Record<string, string> = { queued: 'Queued（排队中）', running: 'Running（运行中）', completed: 'Completed（已完成）', failed: 'Failed（失败）', cancelled: 'Cancelled（已取消）', pending: 'Pending（待处理）', success: 'Succeeded（成功）' }

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
    } catch (cause) { setError(uiError(cause, 'Unable to load targets', '无法读取目标')) }
  }, [])

  useEffect(() => { void reload() }, [reload])
  useEffect(() => {
    if (!datasetId) return
    let active = true
    void fetchVersions(datasetId).then((items) => {
      if (active) { setVersions(items); setDatasetVersion(items[0]?.version ?? 1) }
    }).catch((cause: unknown) => { if (active) setError(uiError(cause, 'Unable to load versions', '无法读取版本')) })
    return () => { active = false }
  }, [datasetId])
  useEffect(() => {
    if (!selectedJobId) return
    let active = true
    const refresh = async () => {
      try {
        const [job, cases] = await Promise.all([fetchTargetJob(selectedJobId), fetchTargetJobCases(selectedJobId)])
        if (active) { setJobs((items) => items.map((item) => item.id === job.id ? job : item)); setJobCases(cases) }
      } catch (cause) { if (active) setError(uiError(cause, 'Unable to load collection job', '无法读取采集任务')) }
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
    } catch (cause) { setError(uiError(cause, 'Unable to save target', '保存目标失败')) }
    finally { setBusy(false) }
  }

  async function probe(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(''); setTestResult(null)
    try { setTestResult(await testTarget(targetId, caseId, question, evaluationType)) }
    catch (cause) { setError(uiError(cause, 'Connection test failed', '连接测试失败')) }
    finally { setBusy(false) }
  }

  async function collect() {
    setBusy(true); setError('')
    try {
      const job = await startTargetJob({ target_id: targetId, dataset_id: datasetId, dataset_version: datasetVersion, evaluation_type: evaluationType })
      setJobs((items) => [job, ...items]); setSelectedJobId(job.id)
    } catch (cause) { setError(uiError(cause, 'Unable to start collection', '启动采集失败')) }
    finally { setBusy(false) }
  }

  async function cancelCollection() {
    if (!selectedJobId) return
    setBusy(true); setError('')
    try {
      const job = await cancelTargetJob(selectedJobId)
      setJobs((items) => items.map((item) => item.id === job.id ? job : item))
    } catch (cause) { setError(uiError(cause, 'Unable to cancel collection', '取消采集失败')) }
    finally { setBusy(false) }
  }

  const selectedTarget = targets.find((item) => item.id === targetId)
  const selectedJob = jobs.find((item) => item.id === selectedJobId)
  return <>
    <header className="page-header"><div><p className="eyebrow">Workspace（工作台）</p><h1>HTTP Targets（HTTP 目标）</h1></div><button type="button" className="refresh-button" title="Refresh Targets（刷新目标）" aria-label="Refresh Targets（刷新目标）" onClick={() => void reload()}><RefreshCw size={17} /></button></header>
    <form className="target-create" onSubmit={(event) => void create(event)}>
      <label className="form-group"><span className="form-label">Name（名称）</span><input value={name} required onChange={(event) => setName(event.target.value)} /></label>
      <label className="form-group"><span className="form-label">Endpoint URL（接口 URL）</span><input type="url" value={url} required placeholder="https://..." onChange={(event) => setUrl(event.target.value)} /></label>
      <label className="form-group"><span className="form-label">Bearer Token（访问令牌）</span><input type="password" value={token} autoComplete="off" onChange={(event) => setToken(event.target.value)} /></label>
      <label className="form-group"><span className="form-label">Response Protocol（响应协议）</span><select value={protocol} onChange={(event) => setProtocol(event.target.value as 'json' | 'sse')}><option value="json">JSON</option><option value="sse">SSE</option></select></label>
      <label className="form-group"><span className="form-label">Timeout (seconds)（超时，秒）</span><input type="number" min="1" max="120" value={timeout} onChange={(event) => setTimeoutValue(Number(event.target.value))} /></label>
      <label className="form-group"><span className="form-label">Retry Attempts（重试次数）</span><input type="number" min="0" max="3" value={retries} onChange={(event) => setRetries(Number(event.target.value))} /></label>
      <label className="form-group"><span className="form-label">Concurrent Requests（并发请求）</span><input type="number" min="1" max="8" value={maxConcurrency} onChange={(event) => setMaxConcurrency(Number(event.target.value))} /></label>
      <button type="submit" className="primary-button" disabled={busy}><Plus size={15} />Save（保存）</button>
    </form>
    {error && <p className="page-error" role="alert">{error}</p>}
    <div className="dataset-layout target-layout"><aside className="dataset-list" aria-label="HTTP Target List（HTTP 目标列表）"><div className="pane-heading"><h2>Targets（目标）</h2><span>{targets.length}</span></div>{targets.map((item) => <button type="button" className={`dataset-row ${targetId === item.id ? 'active' : ''}`} key={item.id} onClick={() => { setTargetId(item.id); setTestResult(null) }}><strong>{item.name}</strong><span>{item.url}</span></button>)}</aside><section className="dataset-workspace" aria-label="Target Details（目标详情）">{selectedTarget ? <>
      <div className="dataset-toolbar"><div><h2>{selectedTarget.name}</h2><span>{selectedTarget.url} · {selectedTarget.protocol.toUpperCase()}</span></div><span className="target-auth">{selectedTarget.has_token ? 'Bearer Configured（已配置 Bearer）' : 'No Authentication（无认证）'}</span></div>
      <div className="target-config"><span>Timeout（超时） {selectedTarget.timeout_seconds} seconds（秒）</span><span>Retry Attempts（重试次数） {selectedTarget.retries}</span><span>Concurrent Requests（并发请求） {selectedTarget.max_concurrency ?? 'Unknown（未知）'}</span></div>
      <form className="target-probe" onSubmit={(event) => void probe(event)}><div className="section-heading"><h2>Connection Test（连接测试）</h2></div><div className="target-probe-fields"><label className="form-group"><span className="form-label">Case ID（样本 ID）</span><input value={caseId} required onChange={(event) => setCaseId(event.target.value)} /></label><label className="form-group"><span className="form-label">Question（问题）</span><input value={question} required onChange={(event) => setQuestion(event.target.value)} /></label><button type="submit" className="secondary-button" disabled={busy}><Link2 size={15} />Test（测试）</button></div>{testResult && <p className={testResult.success ? 'target-success' : 'form-error'} role="status">{testResult.success ? 'Connection succeeded（连接成功）' : `Connection failed（连接失败）：${testResult.error}`}{testResult.attempts.length > 1 ? ` · ${testResult.attempts.length} attempts（${testResult.attempts.length} 次尝试）` : ''}</p>}</form>
      <section className="target-collection"><div className="section-heading"><h2>Batch Collection（批量采集）</h2></div><div className="target-collection-fields"><label className="form-group"><span className="form-label">Datasets（数据集）</span><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>{datasets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="form-group"><span className="form-label">Version（版本）</span><select value={datasetVersion} onChange={(event) => setDatasetVersion(Number(event.target.value))}>{versions.map((item) => <option key={item.id} value={item.version}>v{item.version}</option>)}</select></label><label className="form-group"><span className="form-label">Evaluation Type（评测类型）</span><select value={evaluationType} onChange={(event) => setEvaluationType(event.target.value as EvaluationType)}><option value="both">Answer + Retrieval（答案 + 检索）</option><option value="retrieval">Retrieval（检索）</option><option value="answer">Answer（答案）</option></select></label><button type="button" className="primary-button" disabled={busy || !datasetId || !versions.length} onClick={() => void collect()}><Play size={15} />Collect Predictions（采集预测）</button></div></section>
    </> : <div className="empty-state">No Targets Yet（暂无目标）</div>}</section></div>
    <section className="target-jobs" aria-label="Collection Jobs（采集任务）"><div className="section-heading"><h2>Collection Jobs（采集任务）</h2><span>{jobs.length}</span></div><div className="target-job-list">{jobs.map((job) => <button type="button" key={job.id} className={`target-job-row ${selectedJobId === job.id ? 'active' : ''}`} onClick={() => setSelectedJobId(job.id)}><strong>{targets.find((item) => item.id === job.target_id)?.name ?? job.target_id}</strong><span>{jobStatus[job.status] ?? job.status} · {job.processed_count}/{job.total_count} cases（题）</span></button>)}</div>{selectedJob && <div className="target-job-detail"><div className="section-heading"><h2>Task（任务） {selectedJob.id.slice(0, 8)}</h2><span>Succeeded（成功） {selectedJob.success_count} cases（题） · Failed（失败） {selectedJob.failed_count} cases（题） · Cancelled（取消） {typeof selectedJob.cancelled_count !== 'number' ? 'Unknown（未知）' : `${selectedJob.cancelled_count} cases（题）`}</span></div><div className="target-job-controls"><span>Up to（预计最多） {typeof selectedJob.estimated_external_calls !== 'number' ? 'Unknown（未知）' : `${selectedJob.estimated_external_calls} requests（次请求）`}</span>{['queued', 'running'].includes(selectedJob.status) && <button type="button" className="secondary-button" disabled={busy || selectedJob.cancel_requested} onClick={() => void cancelCollection()}><Ban size={15} />{selectedJob.cancel_requested ? 'Cancelling（取消中）' : 'Cancel Collection（取消采集）'}</button>}</div><TraceLink trace={selectedJob.trace} />{selectedJob.batch_id && <p>Prediction Batch（预测批次） <code>{selectedJob.batch_id}</code></p>}{jobCases.map((item) => <div className="target-job-case" key={item.case_id}><code>{item.case_id}</code><span>{jobStatus[item.status] ?? item.status}</span><span>{item.error ?? ''}</span><small>{item.attempts?.length ?? 0} attempts（{item.attempts?.length ?? 0} 次尝试）</small><TraceLink trace={item.trace} label="Call Trace（调用 trace）" /></div>)}</div>}</section>
  </>
}
