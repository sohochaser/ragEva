import { ArrowRight, Plus, RefreshCw, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { fetchCollections, type CollectionSummary } from '../api/documentCollections'
import { addModel, fetchModels, type OnlineModel } from '../api/scenarios'
import { fetchCandidates, fetchGeneration, fetchGenerations, startGeneration, type GeneratedCandidate, type GenerationRun } from '../api/generations'
import { fetchGenerationUsage, type UsageSummary } from '../api/usage'
import { UsagePanel } from '../usage/UsagePanel'
import { CandidateReview } from './CandidateReview'

const reasonLabels: Record<string, string> = {
  insufficient_source_chunks: '集合中没有足够的 chunk 组成多 chunk 题目',
  call_limit_reached: '已达到模型调用上限',
  model_or_validation_errors: '部分模型响应或候选内容无效',
  insufficient_candidates: '合格候选不足',
  missing_generation_dependency: '集合或模型配置不可用',
  generation_worker_error: '生成任务执行失败',
}

const statusLabels: Record<string, string> = {
  queued: '排队中', running: '生成中', completed: '已完成', partial: '部分完成', failed: '失败',
}

export function GenerationPage({ onOpenCollections }: { onOpenCollections?: () => void }) {
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
    }).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '加载失败'))
  }, [])

  const selected = runs.find((run) => run.id === selectedId)
  const selectedCount = selected?.actual_count
  const attemptedCount = selected?.attempted_count
  useEffect(() => {
    if (!selectedId) { setUsage(null); return }
    let active = true
    void fetchGenerationUsage(selectedId).then((result) => { if (active) setUsage(result) }).catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '用量读取失败') })
    return () => { active = false }
  }, [selectedId, attemptedCount])
  useEffect(() => {
    if (!selectedId) { setCandidates([]); return }
    fetchCandidates(selectedId).then(setCandidates).catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : '候选读取失败')
    })
  }, [selectedId, selectedCount])

  useEffect(() => {
    if (selected?.status !== 'queued' && selected?.status !== 'running') return
    const timer = window.setInterval(() => {
      void fetchGeneration(selected.id).then((updated) => {
        setRuns((items) => items.map((item) => item.id === updated.id ? updated : item))
      }).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '进度更新失败'))
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
      setError(cause instanceof Error ? cause.message : '创建生成任务失败')
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
      setError(cause instanceof Error ? cause.message : '模型保存失败')
    } finally {
      setBusy(false)
    }
  }

  return <>
    <header className="page-header generation-header"><div><p className="eyebrow">GENERATION</p><h1>候选生成</h1></div><div className="page-actions"><button type="button" className="secondary-button" onClick={() => setShowModelForm((value) => !value)}><Plus size={15} />添加生成模型</button><button type="button" className="refresh-button" title="刷新任务" aria-label="刷新任务" onClick={() => void refreshRuns().catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '刷新失败'))}><RefreshCw size={17} /></button></div></header>
    {error && <div className="page-error" role="alert">{error}<button type="button" onClick={() => setError('')}>关闭</button></div>}
    {loaded && !collections.length && <div className="generation-notice" role="status"><span>暂无文档集合</span>{onOpenCollections && <button type="button" onClick={onOpenCollections}>打开文档集合 <ArrowRight size={14} /></button>}</div>}
    {loaded && !models.length && <div className="generation-notice" role="status"><span>暂无生成模型</span><button type="button" onClick={() => setShowModelForm(true)}>添加生成模型 <ArrowRight size={14} /></button></div>}
    {showModelForm && <form className="generation-model-form" onSubmit={(event) => void saveModel(event)}><label className="form-group"><span className="form-label">配置名称</span><input required value={newModelName} onChange={(event) => setNewModelName(event.target.value)} /></label><label className="form-group"><span className="form-label">OpenAI 兼容 API 地址</span><input type="url" required value={newModelApi} onChange={(event) => setNewModelApi(event.target.value)} /></label><label className="form-group"><span className="form-label">模型标识</span><input required value={newModelId} onChange={(event) => setNewModelId(event.target.value)} /></label><label className="form-group"><span className="form-label">Bearer Token</span><input type="password" autoComplete="off" value={newModelToken} onChange={(event) => setNewModelToken(event.target.value)} /></label><button className="primary-button" type="submit" disabled={busy}>保存模型</button></form>}
    <form className="generation-form" onSubmit={(event) => void submit(event)}>
      <label className="form-group"><span className="form-label">文档集合</span><select aria-label="文档集合" value={collectionId} onChange={(event) => setCollectionId(event.target.value)} required>{collections.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.source_kind === 'chunks_only' ? 'chunk 清单' : '原文'}</option>)}</select></label>
      <label className="form-group"><span className="form-label">生成模型</span><select aria-label="生成模型" value={modelId} onChange={(event) => setModelId(event.target.value)} required>{models.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.model_name}</option>)}</select></label>
      <label className="form-group"><span className="form-label">目标条数</span><input type="number" min="1" max="1000" required value={targetCount} onChange={(event) => setTargetCount(Number(event.target.value))} /></label>
      <label className="form-group"><span className="form-label">多 chunk 比例 · {multiPercent}%</span><input type="range" min="0" max="100" step="5" value={multiPercent} onChange={(event) => setMultiPercent(Number(event.target.value))} /></label>
      <label className="form-group"><span className="form-label">语言</span><select value={language} onChange={(event) => setLanguage(event.target.value)}><option>中文</option><option>English</option></select></label>
      <label className="form-group"><span className="form-label">题型</span><select value={questionType} onChange={(event) => setQuestionType(event.target.value)}><option>事实问答</option><option>比较分析</option><option>推理归纳</option></select></label>
      <label className="form-group"><span className="form-label">最大调用次数</span><input type="number" min={targetCount} max="3000" placeholder="自动" value={maxCalls} onChange={(event) => setMaxCalls(event.target.value)} /></label>
      <label className="form-group"><span className="form-label">并发调用</span><select value={maxConcurrency} onChange={(event) => setMaxConcurrency(Number(event.target.value))}>{[1, 2, 3, 4].map((count) => <option key={count} value={count}>{count}</option>)}</select></label>
      <label className="form-group generation-instructions"><span className="form-label">补充要求</span><textarea value={instructions} maxLength={2000} onChange={(event) => setInstructions(event.target.value)} /></label>
      <button type="submit" className="primary-button generation-submit" disabled={busy || !collectionId || !modelId}><Sparkles size={15} />{busy ? '提交中' : '开始生成'}</button>
    </form>
    <div className="generation-layout">
      <aside className="generation-list"><div className="pane-heading"><h2>生成任务</h2><span>{runs.length}</span></div>{runs.map((run) => <button type="button" key={run.id} className={`dataset-row ${selectedId === run.id ? 'active' : ''}`} onClick={() => setSelectedId(run.id)}><strong>{collections.find((item) => item.id === run.collection_id)?.name || run.collection_id}</strong><span>{statusLabels[run.status] || run.status} · {run.actual_count}/{run.target_count}</span></button>)}</aside>
      <section className="generation-results" aria-label="候选结果">{selected ? <>
        <div className="dataset-toolbar"><div><h2>{collections.find((item) => item.id === selected.collection_id)?.name || '生成任务'}</h2><span>{statusLabels[selected.status] || selected.status} · 已调用 {selected.attempted_count}/{selected.max_calls}</span></div><span className="generation-count">候选 {selected.actual_count}/{selected.target_count} · 多 chunk {selected.actual_multi_count}/{selected.target_multi_count}</span></div>
        {selected.shortfall_reasons.length > 0 && <div className="generation-shortfall" role="status">{selected.shortfall_reasons.map((reason) => <span key={reason}>{reasonLabels[reason] || reason}</span>)}{Object.entries(selected.attempt_errors).map(([reason, count]) => <span key={reason}>{reason} · {count} 次</span>)}</div>}
        <UsagePanel usage={usage} />
        {candidates.length ? <ol className="generation-candidates">{candidates.map((item) => <li key={item.id} className="generation-candidate"><div className="generation-candidate-heading"><span>{item.multi_chunk ? '多 chunk' : '单 chunk'}</span><span>{item.model_name}</span></div><h3>{item.question}</h3><p className="generation-answer"><ArrowRight size={15} />{item.reference_answer}</p><div className="generation-evidence"><strong>支撑 chunk</strong>{item.reference_chunks.map((chunk, index) => <div key={`${item.id}-${index}`}><code>{chunk.document_id}</code><p>{chunk.text}</p></div>)}</div><CandidateReview candidate={item} onUpdated={(updated) => setCandidates((items) => items.map((current) => current.id === updated.id ? updated : current))} /></li>)}</ol> : <div className="empty-state"><Sparkles size={28} /><h2>{selected.status === 'queued' || selected.status === 'running' ? '正在等待候选' : '暂无合格候选'}</h2></div>}
      </> : <div className="empty-state"><Sparkles size={28} /><h2>暂无生成任务</h2></div>}</section>
    </div>
  </>
}
