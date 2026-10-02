import { ChevronLeft, ChevronRight, FileText, Plus, Upload, X } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'

import {
  DatasetImportError,
  fetchDatasets,
  fetchVersion,
  fetchVersions,
  fieldNames,
  importDataset,
  type DatasetSummary,
  type EvaluationCase,
  type FieldMapping,
  type ImportIssue,
  type VersionDetail,
  type VersionSummary,
} from '../api/datasets'

const fieldLabels = {
  case_id: '样本 ID',
  question: '问题',
  reference_answer: '标准答案',
  reference_chunks: '参考 chunk',
}

type ImportDialogProps = {
  datasets: DatasetSummary[]
  selectedDatasetId: string | null
  onClose: () => void
  onImported: (summary: VersionSummary) => void
}

function ImportDialog({ datasets, selectedDatasetId, onClose, onImported }: ImportDialogProps) {
  const [mode, setMode] = useState<'new' | 'existing'>(selectedDatasetId ? 'existing' : 'new')
  const [datasetId, setDatasetId] = useState(selectedDatasetId ?? datasets[0]?.id ?? '')
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [mapping, setMapping] = useState<FieldMapping>({})
  const [issues, setIssues] = useState<ImportIssue[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) return
    setBusy(true)
    setIssues([])
    setError('')
    try {
      const summary = await importDataset({
        file,
        datasetId: mode === 'existing' ? datasetId : undefined,
        datasetName: mode === 'new' ? name.trim() : undefined,
        mapping,
      })
      onImported(summary)
    } catch (cause) {
      if (cause instanceof DatasetImportError) setIssues(cause.issues)
      else setError(cause instanceof Error ? cause.message : '导入失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <section className="import-dialog" role="dialog" aria-modal="true" aria-labelledby="import-title">
        <div className="dialog-heading">
          <div><p className="eyebrow">DATASET</p><h2 id="import-title">导入样本</h2></div>
          <button type="button" className="icon-button" onClick={onClose} title="关闭" aria-label="关闭"><X size={18} /></button>
        </div>
        <form onSubmit={(event) => void submit(event)}>
          <div className="form-group">
            <span className="form-label">目标</span>
            <div className="segmented-control" role="group" aria-label="导入目标">
              <button type="button" className={mode === 'new' ? 'selected' : ''} onClick={() => setMode('new')}>新数据集</button>
              <button type="button" className={mode === 'existing' ? 'selected' : ''} disabled={!datasets.length} onClick={() => setMode('existing')}>已有数据集</button>
            </div>
          </div>
          {mode === 'new' ? (
            <label className="form-group"><span className="form-label">数据集名称</span><input value={name} onChange={(event) => setName(event.target.value)} required maxLength={120} placeholder="例如：客服问答金标准" /></label>
          ) : (
            <label className="form-group"><span className="form-label">数据集</span><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)} required>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}</select></label>
          )}
          <label className="form-group"><span className="form-label">文件</span><input type="file" accept=".csv,.jsonl" required onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
          <fieldset className="mapping-fields">
            <legend>字段映射</legend>
            <p>文件列名不同时填写；未填写的字段使用标准列名。</p>
            <div className="mapping-grid">
              {fieldNames.map((field) => <label className="form-group" key={field}><span className="form-label">{fieldLabels[field]}</span><input value={mapping[field] ?? ''} placeholder={field} onChange={(event) => setMapping((current) => ({ ...current, [field]: event.target.value }))} /></label>)}
            </div>
          </fieldset>
          {error && <p className="form-error" role="alert">{error}</p>}
          {issues.length > 0 && <div className="import-issues" role="alert"><strong>导入失败，共 {issues.length} 处错误</strong><ul>{issues.map((issue, index) => <li key={`${issue.line}-${issue.field}-${index}`}>{issue.line ? `第 ${issue.line} 行` : '文件'}{issue.field ? ` · ${issue.field}` : ''}：{issue.message}</li>)}</ul></div>}
          <div className="dialog-actions">
            <button type="button" className="secondary-button" onClick={onClose}>取消</button>
            <button type="submit" className="primary-button" disabled={busy || !file || (mode === 'new' ? !name.trim() : !datasetId)}><Upload size={16} />{busy ? '导入中' : '导入'}</button>
          </div>
        </form>
      </section>
    </div>
  )
}

function CaseDetail({ item }: { item: EvaluationCase }) {
  return (
    <section className="case-detail" aria-labelledby="case-title">
      <div className="detail-heading"><span className="eyebrow">CASE DETAIL</span><code>{item.case_id}</code></div>
      <h2 id="case-title">{item.question}</h2>
      <div className="detail-block"><h3>标准答案</h3><p>{item.reference_answer ?? '未标注'}</p></div>
      <div className="detail-block"><h3>参考 chunk <span>{item.reference_chunks?.length ?? 0}</span></h3>
        {item.reference_chunks?.length ? <ol className="chunk-list">{item.reference_chunks.map((chunk, index) => <li key={index}><div className="chunk-meta"><span>#{index + 1}</span><code>{chunk.document_id}</code></div><p>{chunk.text}</p></li>)}</ol> : <p>未标注</p>}
      </div>
    </section>
  )
}

export function DatasetPage({ active = true, focusVersion }: {
  active?: boolean
  focusVersion?: { datasetId: string; version: number } | null
}) {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [versions, setVersions] = useState<VersionSummary[]>([])
  const [version, setVersion] = useState<number | null>(null)
  const [detail, setDetail] = useState<VersionDetail | null>(null)
  const [offset, setOffset] = useState(0)
  const [caseId, setCaseId] = useState<string | null>(null)
  const [showImport, setShowImport] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    try {
      const result = await fetchDatasets()
      setDatasets(result)
      setDatasetId((current) => current && result.some((item) => item.id === current) ? current : result[0]?.id ?? null)
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法读取数据集')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (active) void reload() }, [active, reload])
  useEffect(() => {
    if (!active || !focusVersion) return
    setDatasetId(focusVersion.datasetId)
    setVersion(focusVersion.version)
    setOffset(0)
    setDetail(null)
  }, [active, focusVersion])
  useEffect(() => {
    if (!active) return
    if (!datasetId) { setVersions([]); setVersion(null); setDetail(null); return }
    let alive = true
    void fetchVersions(datasetId).then((items) => {
      if (!alive) return
      setVersions(items)
      setVersion((current) => current && items.some((item) => item.version === current) ? current : items[0]?.version ?? null)
    }).catch((cause: unknown) => { if (alive) setError(cause instanceof Error ? cause.message : '无法读取版本') })
    return () => { alive = false }
  }, [active, datasetId])
  useEffect(() => {
    if (!active) return
    if (!datasetId || version === null) { setDetail(null); return }
    let alive = true
    void fetchVersion(datasetId, version, offset).then((result) => {
      if (!alive) return
      setDetail(result)
      setCaseId((current) => current && result.cases.some((item) => item.case_id === current) ? current : result.cases[0]?.case_id ?? null)
      setError('')
    }).catch((cause: unknown) => { if (alive) setError(cause instanceof Error ? cause.message : '无法读取样本') })
    return () => { alive = false }
  }, [active, datasetId, version, offset])

  const selectedDataset = datasets.find((item) => item.id === datasetId)
  const selectedCase = detail?.cases.find((item) => item.case_id === caseId)

  async function imported(summary: VersionSummary) {
    setShowImport(false)
    setDatasetId(summary.dataset_id)
    setVersion(summary.version)
    setOffset(0)
    await reload()
    try { setVersions(await fetchVersions(summary.dataset_id)) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '无法读取版本') }
  }

  return (
    <>
      <header className="page-header">
        <div><p className="eyebrow">WORKSPACE</p><h1>数据集</h1></div>
        <button className="primary-button" type="button" onClick={() => setShowImport(true)}><Plus size={16} />导入样本</button>
      </header>
      {error && <div className="page-error" role="alert">{error}<button type="button" onClick={() => void reload()}>重试</button></div>}
      {loading ? <p className="empty-state">加载中</p> : datasets.length === 0 ? (
        <div className="empty-state"><FileText size={30} aria-hidden="true" /><h2>暂无数据集</h2><p>导入 CSV 或 JSONL 样本开始评测。</p></div>
      ) : (
        <div className="dataset-layout">
          <aside className="dataset-list" aria-label="数据集列表">
            <div className="pane-heading"><h2>数据集</h2><span>{datasets.length}</span></div>
            {datasets.map((dataset) => <button className={`dataset-row ${dataset.id === datasetId ? 'active' : ''}`} type="button" key={dataset.id} onClick={() => { setDatasetId(dataset.id); setVersion(null); setOffset(0); setDetail(null) }}><strong>{dataset.name}</strong><span>{dataset.latest_case_count} 条样本 · {dataset.version_count} 个版本</span></button>)}
          </aside>
          <div className="dataset-workspace">
            <div className="dataset-toolbar"><div><h2>{selectedDataset?.name}</h2><span>{detail?.case_count ?? selectedDataset?.latest_case_count ?? 0} 条样本</span>{detail && (detail.source_collection_ids ?? []).length > 0 && <p className="dataset-source-ids">来源集合 {(detail.source_collection_ids ?? []).map((id) => <code key={id}>{id}</code>)}</p>}</div><label className="version-picker">版本<select aria-label="版本" value={version ?? ''} onChange={(event) => { setVersion(Number(event.target.value)); setOffset(0); setDetail(null) }}>{versions.map((item) => <option key={item.id} value={item.version}>v{item.version}</option>)}</select></label></div>
            <div className="case-workspace">
              <section className="case-list" aria-label="样本列表">
                <div className="pane-heading"><h3>样本</h3><span>{detail?.total ?? 0}</span></div>
                {detail?.cases.map((item) => <button className={`case-row ${caseId === item.case_id ? 'active' : ''}`} type="button" key={item.case_id} onClick={() => setCaseId(item.case_id)}><code>{item.case_id}</code><strong>{item.question}</strong><span>{item.reference_answer ? '答案' : ''}{item.reference_answer && item.reference_chunks ? ' · ' : ''}{item.reference_chunks ? `${item.reference_chunks.length} 个 chunk` : ''}</span></button>)}
                {detail && detail.total > detail.limit && <div className="pagination"><button type="button" title="上一页" aria-label="上一页" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - detail.limit))}><ChevronLeft size={16} /></button><span>{Math.floor(offset / detail.limit) + 1} / {Math.ceil(detail.total / detail.limit)}</span><button type="button" title="下一页" aria-label="下一页" disabled={offset + detail.limit >= detail.total} onClick={() => setOffset(offset + detail.limit)}><ChevronRight size={16} /></button></div>}
              </section>
              {selectedCase ? <CaseDetail item={selectedCase} /> : <div className="case-detail empty-detail">加载样本中</div>}
            </div>
          </div>
        </div>
      )}
      {showImport && <ImportDialog datasets={datasets} selectedDatasetId={datasetId} onClose={() => setShowImport(false)} onImported={(summary) => void imported(summary)} />}
    </>
  )
}
