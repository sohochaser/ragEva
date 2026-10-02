import { ChevronLeft, ChevronRight, FileInput, Plus, Upload, X } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { fetchDatasets, fetchVersions, DatasetImportError, type DatasetSummary, type ImportIssue, type VersionSummary } from '../api/datasets'
import {
  fetchPredictionBatch, fetchPredictionBatches, importPredictionBatch, predictionFields,
  type EvaluationType, type Prediction, type PredictionBatchDetail, type PredictionBatchSummary,
  type PredictionMapping,
} from '../api/predictions'
import { MatchingPreview } from './MatchingPreview'

const fieldLabels = {
  case_id: '样本 ID', question: '问题', reference_answer: '标准答案',
  reference_chunks: '参考 chunk', answer: '预测答案', contexts: '预测 chunk', latency_ms: '耗时 (ms)',
}

const typeLabels: Record<EvaluationType, string> = {
  answer: '答案', retrieval: '检索', both: '答案 + 检索',
}

function ImportDialog({ datasets, onClose, onImported }: {
  datasets: DatasetSummary[]
  onClose: () => void
  onImported: (batch: PredictionBatchSummary) => void
}) {
  const [target, setTarget] = useState<'existing' | 'new'>(datasets.length ? 'existing' : 'new')
  const [datasetId, setDatasetId] = useState(datasets[0]?.id ?? '')
  const [datasetName, setDatasetName] = useState('')
  const [versions, setVersions] = useState<VersionSummary[]>([])
  const [datasetVersion, setDatasetVersion] = useState<number | null>(null)
  const [evaluationType, setEvaluationType] = useState<EvaluationType>('both')
  const [file, setFile] = useState<File | null>(null)
  const [mapping, setMapping] = useState<PredictionMapping>({})
  const [issues, setIssues] = useState<ImportIssue[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!datasetId) return
    let active = true
    void fetchVersions(datasetId).then((items) => {
      if (!active) return
      setVersions(items)
      setDatasetVersion(items[0]?.version ?? null)
    }).catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '无法读取版本') })
    return () => { active = false }
  }, [datasetId])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) return
    setBusy(true)
    setIssues([])
    setError('')
    try {
      const batch = await importPredictionBatch({
        file, evaluationType, mapping,
        datasetId: target === 'existing' ? datasetId : undefined,
        datasetVersion: target === 'existing' ? datasetVersion ?? undefined : undefined,
        datasetName: target === 'new' ? datasetName.trim() : undefined,
      })
      onImported(batch)
    } catch (cause) {
      if (cause instanceof DatasetImportError) setIssues(cause.issues)
      else setError(cause instanceof Error ? cause.message : '导入失败')
    } finally { setBusy(false) }
  }

  const visibleFields = predictionFields.filter((field) => target === 'new' || !['question', 'reference_answer', 'reference_chunks'].includes(field))

  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="import-dialog" role="dialog" aria-modal="true" aria-labelledby="prediction-import-title">
      <div className="dialog-heading"><div><p className="eyebrow">PREDICTIONS</p><h2 id="prediction-import-title">导入预测</h2></div><button type="button" className="icon-button" aria-label="关闭" title="关闭" onClick={onClose}><X size={18} /></button></div>
      <form onSubmit={(event) => void submit(event)}>
        <div className="form-group"><span className="form-label">数据集来源</span><div className="segmented-control" role="group" aria-label="数据集来源"><button type="button" className={target === 'existing' ? 'selected' : ''} disabled={!datasets.length} onClick={() => setTarget('existing')}>已有数据集</button><button type="button" className={target === 'new' ? 'selected' : ''} onClick={() => setTarget('new')}>同文件新建</button></div></div>
        {target === 'existing' ? <div className="form-pair"><label className="form-group"><span className="form-label">数据集</span><select value={datasetId} required onChange={(event) => setDatasetId(event.target.value)}>{datasets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="form-group"><span className="form-label">版本</span><select value={datasetVersion ?? ''} required onChange={(event) => setDatasetVersion(Number(event.target.value))}>{versions.map((item) => <option key={item.id} value={item.version}>v{item.version}</option>)}</select></label></div> : <label className="form-group"><span className="form-label">新数据集名称</span><input value={datasetName} required maxLength={120} onChange={(event) => setDatasetName(event.target.value)} /></label>}
        <div className="form-group"><span className="form-label">评测类型</span><div className="segmented-control" role="group" aria-label="评测类型">{(['answer', 'retrieval', 'both'] as const).map((kind) => <button key={kind} type="button" className={evaluationType === kind ? 'selected' : ''} onClick={() => setEvaluationType(kind)}>{typeLabels[kind]}</button>)}</div></div>
        <label className="form-group"><span className="form-label">预测文件</span><input type="file" accept=".csv,.jsonl" required onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
        <fieldset className="mapping-fields"><legend>字段映射</legend><p>文件列名不同时填写；未填写的字段使用标准列名。</p><div className="mapping-grid">{visibleFields.map((field) => <label className="form-group" key={field}><span className="form-label">{fieldLabels[field]}</span><input placeholder={field} value={mapping[field] ?? ''} onChange={(event) => setMapping((current) => ({ ...current, [field]: event.target.value }))} /></label>)}</div></fieldset>
        {error && <p className="form-error" role="alert">{error}</p>}
        {issues.length > 0 && <div className="import-issues" role="alert"><strong>导入失败，共 {issues.length} 处错误</strong><ul>{issues.map((issue, index) => <li key={`${issue.line}-${issue.field}-${index}`}>{issue.line ? `第 ${issue.line} 行` : '文件'}{issue.field ? ` · ${issue.field}` : ''}：{issue.message}</li>)}</ul></div>}
        <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={busy || !file || (target === 'existing' ? !datasetVersion : !datasetName.trim())}><Upload size={16} />{busy ? '导入中' : '导入'}</button></div>
      </form>
    </section>
  </div>
}

function PredictionDetail({ prediction }: { prediction: Prediction }) {
  return <section className="case-detail" aria-labelledby="prediction-title">
    <div className="detail-heading"><span className="eyebrow">PREDICTION DETAIL</span><code>{prediction.case_id}</code></div>
    <h2 id="prediction-title">预测内容</h2>
    <div className="detail-block"><h3>答案</h3><p>{prediction.answer ?? '未提供'}</p></div>
    <div className="detail-block"><h3>检索 chunk <span>{prediction.contexts?.length ?? 0}</span></h3>{prediction.contexts?.length ? <ol className="chunk-list">{prediction.contexts.map((chunk, index) => <li key={index}><div className="chunk-meta"><span>#{index + 1}</span><code>{chunk.document_id}</code></div><p>{chunk.text}</p></li>)}</ol> : <p>未提供</p>}</div>
    {prediction.latency_ms !== null && <div className="detail-block"><h3>耗时</h3><p>{prediction.latency_ms} ms</p></div>}
  </section>
}

export function PredictionPage() {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [batches, setBatches] = useState<PredictionBatchSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<PredictionBatchDetail | null>(null)
  const [caseId, setCaseId] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [showImport, setShowImport] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    try {
      const [datasetItems, batchItems] = await Promise.all([fetchDatasets(), fetchPredictionBatches()])
      setDatasets(datasetItems)
      setBatches(batchItems)
      setSelectedId((current) => current && batchItems.some((item) => item.id === current) ? current : batchItems[0]?.id ?? null)
      setError('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '无法读取预测批次') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { void reload() }, [reload])
  useEffect(() => {
    if (!selectedId) { setDetail(null); return }
    let active = true
    void fetchPredictionBatch(selectedId, offset).then((batch) => {
      if (!active) return
      setDetail(batch)
      setCaseId((current) => current && batch.predictions.some((item) => item.case_id === current) ? current : batch.predictions[0]?.case_id ?? null)
    }).catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '无法读取批次') })
    return () => { active = false }
  }, [selectedId, offset])

  const selected = batches.find((item) => item.id === selectedId)
  const prediction = detail?.predictions.find((item) => item.case_id === caseId)
  const datasetName = (id: string) => datasets.find((item) => item.id === id)?.name ?? id

  async function imported(batch: PredictionBatchSummary) {
    setShowImport(false)
    setSelectedId(batch.id)
    setOffset(0)
    await reload()
  }

  return <>
    <header className="page-header"><div><p className="eyebrow">WORKSPACE</p><h1>预测批次</h1></div><button type="button" className="primary-button" onClick={() => setShowImport(true)}><Plus size={16} />导入预测</button></header>
    {error && <div className="page-error" role="alert">{error}<button type="button" onClick={() => void reload()}>重试</button></div>}
    {loading ? <p className="empty-state">加载中</p> : batches.length === 0 ? <div className="empty-state"><FileInput size={30} aria-hidden="true" /><h2>暂无预测批次</h2><p>导入 CSV 或 JSONL 预测文件。</p></div> : <div className="dataset-layout">
      <aside className="dataset-list" aria-label="预测批次列表"><div className="pane-heading"><h2>批次</h2><span>{batches.length}</span></div>{batches.map((batch) => <button key={batch.id} type="button" className={`dataset-row ${selectedId === batch.id ? 'active' : ''}`} onClick={() => { setSelectedId(batch.id); setOffset(0); setDetail(null) }}><strong>{batch.source_filename}</strong><span>{datasetName(batch.dataset_id)} · v{batch.dataset_version}</span></button>)}</aside>
      <div className="dataset-workspace"><div className="dataset-toolbar"><div><h2>{selected?.source_filename}</h2><span>{selected && `${datasetName(selected.dataset_id)} · v${selected.dataset_version} · ${typeLabels[selected.evaluation_type]}`}</span></div><div className="batch-counts"><span>匹配 {selected?.matched_count ?? 0}</span><span>未匹配 {selected?.missing_case_count ?? 0}</span></div></div>
        <div className="case-workspace"><section className="case-list" aria-label="预测列表"><div className="pane-heading"><h3>预测</h3><span>{detail?.record_count ?? 0}</span></div>{detail?.predictions.map((item) => <button key={item.case_id} type="button" className={`case-row ${caseId === item.case_id ? 'active' : ''}`} onClick={() => setCaseId(item.case_id)}><code>{item.case_id}</code><strong>{item.answer ?? `${item.contexts?.length ?? 0} 个 chunk`}</strong></button>)}{detail && detail.record_count > detail.limit && <div className="pagination"><button type="button" title="上一页" aria-label="上一页" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - detail.limit))}><ChevronLeft size={16} /></button><span>{Math.floor(offset / detail.limit) + 1} / {Math.ceil(detail.record_count / detail.limit)}</span><button type="button" title="下一页" aria-label="下一页" disabled={offset + detail.limit >= detail.record_count} onClick={() => setOffset(offset + detail.limit)}><ChevronRight size={16} /></button></div>}</section>{prediction ? <PredictionDetail prediction={prediction} /> : <div className="case-detail empty-detail">加载预测中</div>}</div>
        {selected && prediction && <MatchingPreview key={`${selected.id}-${prediction.case_id}`} datasetId={selected.dataset_id} version={selected.dataset_version} prediction={prediction} />}
      </div>
    </div>}
    {showImport && <ImportDialog datasets={datasets} onClose={() => setShowImport(false)} onImported={(batch) => void imported(batch)} />}
  </>
}
