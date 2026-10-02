import { ArrowRight, Plus, RefreshCw, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { fetchCollections, type CollectionSummary } from '../api/documentCollections'
import type { VersionSummary } from '../api/datasets'
import { addModel, fetchModels, type OnlineModel } from '../api/scenarios'
import { fetchCandidates, fetchGeneration, fetchGenerations, startGeneration, type GeneratedCandidate, type GenerationRun } from '../api/generations'
import { fetchGenerationUsage, type UsageSummary } from '../api/usage'
import { UsagePanel } from '../usage/UsagePanel'
import { TraceLink } from '../trace/TraceLink'
import { uiError } from '../ui/text'
import { CandidateReview } from './CandidateReview'
import { PublishCandidates } from './PublishCandidates'

const reasonLabels: Record<string, string> = {
  insufficient_source_chunks: 'Not enough chunks in the collection for a multi-chunk question（集合中没有足够的切块组成多切块题目）',
  call_limit_reached: 'Model call limit reached（已达到模型调用上限）',
  model_or_validation_errors: 'Some model responses or candidates were invalid（部分模型响应或候选内容无效）',
  insufficient_candidates: 'Not enough eligible candidates（合格候选不足）',
  missing_generation_dependency: 'Collection or model configuration unavailable（集合或模型配置不可用）',
  generation_worker_error: 'Generation task failed（生成任务执行失败）',
}

const statusLabels: Record<string, string> = {
  queued: 'Queued（排队中）', running: 'Generating（生成中）', completed: 'Completed（已完成）', partial: 'Partially Completed（部分完成）', failed: 'Failed（失败）',
}

export function GenerationPage({ onOpenCollections, onOpenDatasets }: {
  onOpenCollections?: () => void
  onOpenDatasets?: (version: VersionSummary) => void
}) {
  const [collections, setCollections] = useState<CollectionSummary[]>([])
  const [models, setModels] = useState<OnlineModel[]>([])
  const [runs, setRuns] = useState<GenerationRun[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [candidates, setCandidates] = useState<GeneratedCandidate[]>([])
  const [usage, setUsage] = useState<UsageSummary | null>(null)
  const [collectionId, setCollectionId] = useState('')
  const [modelId, setModelId] = useState('')
  const [targetCount, setTargetCount] = useState(20)
  const [multiPercent, setMultiPercent] = useState(30)
  const [language, setLanguage] = useState('中文')
  const [questionType, setQuestionType] = useState('事实问答')
  const [instructions, setInstructions] = useState('')
  const [maxCalls, setMaxCalls] = useState('')
  const [maxConcurrency, setMaxConcurrency] = useState(4)
  const [showModelForm, setShowModelForm] = useState(false)
  const [newModelName, setNewModelName] = useState('')
  const [newModelApi, setNewModelApi] = useState('')
  const [newModelId, setNewModelId] = useState('')
  const [newModelToken, setNewModelToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState(false)

  const refreshRuns = useCallback(async () => {
    const items = await fetchGenerations()
    setRuns(items)
    setSelectedId((id) => id || items[0]?.id || '')
  }, [])

  useEffect(() => {
    Promise.all([fetchCollections(), fetchModels(), fetchGenerations()]).then(([sourceItems, modelItems, runItems]) => {
      setCollections(sourceItems)
      setModels(modelItems)
      setRuns(runItems)
      setCollectionId((id) => id || sourceItems[0]?.id || '')
      setModelId((id) => id || modelItems[0]?.id || '')
      setSelectedId((id) => id || runItems[0]?.id || '')
      setLoaded(true)
    }).catch((cause: unknown) => setError(uiError(cause, 'Unable to load generation data', '加载失败')))
  }, [])

  const selected = runs.find((run) => run.id === selectedId)
  const selectedCount = selected?.actual_count
  const attemptedCount = selected?.attempted_count
  useEffect(() => {
    if (!selectedId) { setUsage(null); return }
    let active = true
    void fetchGenerationUsage(selectedId).then((result) => { if (active) setUsage(result) }).catch((cause: unknown) => { if (active) setError(uiError(cause, 'Unable to load usage', '用量读取失败')) })
    return () => { active = false }
  }, [selectedId, attemptedCount])
  useEffect(() => {
    if (!selectedId) { setCandidates([]); return }
    fetchCandidates(selectedId).then(setCandidates).catch((cause: unknown) => {
      setError(uiError(cause, 'Unable to load candidates', '候选读取失败'))
    })
  }, [selectedId, selectedCount])

  useEffect(() => {
    if (selected?.status !== 'queued' && selected?.status !== 'running') return
    const timer = window.setInterval(() => {
      void fetchGeneration(selected.id).then((updated) => {
        setRuns((items) => items.map((item) => item.id === updated.id ? updated : item))
      }).catch((cause: unknown) => setError(uiError(cause, 'Progress update failed', '进度更新失败')))
    }, 2000)
    return () => window.clearInterval(timer)
  }, [selected?.id, selected?.status])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!collectionId || !modelId) return
    setBusy(true)
    setError('')
    try {
      const created = await startGeneration(collectionId, {
        model_id: modelId,
        target_count: targetCount,
        multi_chunk_ratio: multiPercent / 100,
        language,
        question_type: questionType,
        instructions: instructions.trim(),
        max_calls: maxCalls ? Number(maxCalls) : null,
        max_concurrency: maxConcurrency,
      })
      setRuns((items) => [created, ...items])
      setSelectedId(created.id)
      setCandidates([])
    } catch (cause) {
      setError(uiError(cause, 'Unable to create generation task', '创建生成任务失败'))
    } finally {
      setBusy(false)
    }
  }

  async function saveModel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const created = await addModel({
        name: newModelName.trim(), base_url: newModelApi.trim(), model_name: newModelId.trim(),
        bearer_token: newModelToken || null, timeout_seconds: 60,
      })
      setModels((items) => [created, ...items])
      setModelId(created.id)
      setNewModelName(''); setNewModelApi(''); setNewModelId(''); setNewModelToken('')
      setShowModelForm(false)
    } catch (cause) {
      setError(uiError(cause, 'Unable to save model', '模型保存失败'))
    } finally {
      setBusy(false)
    }
  }

  return <>
    <header className="page-header generation-header"><div><p className="eyebrow">Generation（生成）</p><h1>Candidate Generation（候选生成）</h1></div><div className="page-actions"><button type="button" className="secondary-button" onClick={() => setShowModelForm((value) => !value)}><Plus size={15} />Add Generation Model（添加生成模型）</button><button type="button" className="refresh-button" title="Refresh Tasks（刷新任务）" aria-label="Refresh Tasks（刷新任务）" onClick={() => void refreshRuns().catch((cause: unknown) => setError(uiError(cause, 'Refresh failed', '刷新失败')))}><RefreshCw size={17} /></button></div></header>
    {error && <div className="page-error" role="alert">{error}<button type="button" onClick={() => setError('')}>Close（关闭）</button></div>}
    {loaded && !collections.length && <div className="generation-notice" role="status"><span>No Document Collections Yet（暂无文档集合）</span>{onOpenCollections && <button type="button" onClick={onOpenCollections}>Open Document Collections（打开文档集合） <ArrowRight size={14} /></button>}</div>}
    {loaded && !models.length && <div className="generation-notice" role="status"><span>No Generation Models Yet（暂无生成模型）</span><button type="button" onClick={() => setShowModelForm(true)}>Add Generation Model（添加生成模型） <ArrowRight size={14} /></button></div>}
    {showModelForm && <form className="generation-model-form" onSubmit={(event) => void saveModel(event)}><label className="form-group"><span className="form-label">Configuration Name（配置名称）</span><input required value={newModelName} onChange={(event) => setNewModelName(event.target.value)} /></label><label className="form-group"><span className="form-label">OpenAI-Compatible API URL（OpenAI 兼容 API 地址）</span><input type="url" required value={newModelApi} onChange={(event) => setNewModelApi(event.target.value)} /></label><label className="form-group"><span className="form-label">Model ID（模型标识）</span><input required value={newModelId} onChange={(event) => setNewModelId(event.target.value)} /></label><label className="form-group"><span className="form-label">Bearer Token（访问令牌）</span><input type="password" autoComplete="off" value={newModelToken} onChange={(event) => setNewModelToken(event.target.value)} /></label><button className="primary-button" type="submit" disabled={busy}>Save Model（保存模型）</button></form>}
    <form className="generation-form" onSubmit={(event) => void submit(event)}>
      <label className="form-group"><span className="form-label">Document Collections（文档集合）</span><select aria-label="Document Collections（文档集合）" value={collectionId} onChange={(event) => setCollectionId(event.target.value)} required>{collections.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.source_kind === 'chunks_only' ? 'Chunk Manifest（chunk 清单）' : 'Source Files（原文）'}</option>)}</select></label>
      <label className="form-group"><span className="form-label">Generation Model（生成模型）</span><select aria-label="Generation Model（生成模型）" value={modelId} onChange={(event) => setModelId(event.target.value)} required>{models.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.model_name}</option>)}</select></label>
      <label className="form-group"><span className="form-label">Target Case Count（目标条数）</span><input type="number" min="1" max="1000" required value={targetCount} onChange={(event) => setTargetCount(Number(event.target.value))} /></label>
      <label className="form-group"><span className="form-label">Multi-Chunk Ratio（多切块比例） · {multiPercent}%（百分比）</span><input type="range" min="0" max="100" step="5" value={multiPercent} onChange={(event) => setMultiPercent(Number(event.target.value))} /></label>
      <label className="form-group"><span className="form-label">Language（语言）</span><select value={language} onChange={(event) => setLanguage(event.target.value)}><option value="中文">Chinese（中文）</option><option value="English">English（英语）</option></select></label>
      <label className="form-group"><span className="form-label">Question Type（题型）</span><select value={questionType} onChange={(event) => setQuestionType(event.target.value)}><option value="事实问答">Factual Q&A（事实问答）</option><option value="比较分析">Comparison（比较分析）</option><option value="推理归纳">Reasoning and Synthesis（推理归纳）</option></select></label>
      <label className="form-group"><span className="form-label">Maximum Calls（最大调用次数）</span><input type="number" min={targetCount} max="3000" placeholder="Automatic（自动）" value={maxCalls} onChange={(event) => setMaxCalls(event.target.value)} /></label>
      <label className="form-group"><span className="form-label">Concurrent Calls（并发调用）</span><select value={maxConcurrency} onChange={(event) => setMaxConcurrency(Number(event.target.value))}>{[1, 2, 3, 4].map((count) => <option key={count} value={count}>{count}</option>)}</select></label>
      <label className="form-group generation-instructions"><span className="form-label">Additional Requirements（补充要求）</span><textarea value={instructions} maxLength={2000} onChange={(event) => setInstructions(event.target.value)} /></label>
      <button type="submit" className="primary-button generation-submit" disabled={busy || !collectionId || !modelId}><Sparkles size={15} />{busy ? 'Submitting（提交中）' : 'Start Generation（开始生成）'}</button>
    </form>
    <div className="generation-layout">
      <aside className="generation-list"><div className="pane-heading"><h2>Generation Tasks（生成任务）</h2><span>{runs.length}</span></div>{runs.map((run) => <button type="button" key={run.id} className={`dataset-row ${selectedId === run.id ? 'active' : ''}`} onClick={() => setSelectedId(run.id)}><strong>{collections.find((item) => item.id === run.collection_id)?.name || run.collection_id}</strong><span>{statusLabels[run.status] || run.status} · {run.actual_count}/{run.target_count}</span></button>)}</aside>
      <section className="generation-results" aria-label="Candidate Results（候选结果）">{selected ? <>
        <div className="dataset-toolbar"><div><h2>{collections.find((item) => item.id === selected.collection_id)?.name || 'Generation Task（生成任务）'}</h2><span>{statusLabels[selected.status] || selected.status} · Calls（已调用） {selected.attempted_count}/{selected.max_calls}</span></div><span className="generation-count">Candidates（候选） {selected.actual_count}/{selected.target_count} · Multi-Chunk（多切块） {selected.actual_multi_count}/{selected.target_multi_count}</span></div>
        <div className="trace-links"><TraceLink trace={selected.trace} label="Generation Trace（生成 trace）" /><TraceLink trace={selected.collection_trace} label="Source Collection Trace（来源集合 trace）" /></div>
        {selected.shortfall_reasons.length > 0 && <div className="generation-shortfall" role="status">{selected.shortfall_reasons.map((reason) => <span key={reason}>{reasonLabels[reason] || reason}</span>)}{Object.entries(selected.attempt_errors).map(([reason, count]) => <span key={reason}>{reason} · {count} calls（{count} 次调用）</span>)}</div>}
        <UsagePanel usage={usage} />
        {candidates.length > 0 && <PublishCandidates key={selected.id} candidates={candidates} onOpenDatasets={onOpenDatasets} />}
        {candidates.length ? <ol className="generation-candidates">{candidates.map((item) => <li key={item.id} className="generation-candidate"><div className="generation-candidate-heading"><span>{item.multi_chunk ? 'Multi-Chunk（多切块）' : 'Single-Chunk（单切块）'}</span><span>{item.model_name}</span></div><h3>{item.question}</h3><p className="generation-answer"><ArrowRight size={15} />{item.reference_answer}</p><div className="generation-evidence"><strong>Supporting Chunks（支撑 chunk）</strong>{item.reference_chunks.map((chunk, index) => <div key={`${item.id}-${index}`}><code>{chunk.document_id}</code><p>{chunk.text}</p></div>)}</div><CandidateReview candidate={item} onUpdated={(updated) => setCandidates((items) => items.map((current) => current.id === updated.id ? updated : current))} /></li>)}</ol> : <div className="empty-state"><Sparkles size={28} /><h2>{selected.status === 'queued' || selected.status === 'running' ? 'Waiting for Candidates（正在等待候选）' : 'No Eligible Candidates（暂无合格候选）'}</h2></div>}
      </> : <div className="empty-state"><Sparkles size={28} /><h2>No Generation Tasks Yet（暂无生成任务）</h2></div>}</section>
    </div>
  </>
}
