import { FileText, Plus, Upload, X } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'

import {
  CollectionImportError, createCollection, fetchCollection, fetchCollections,
  type CollectionDetail, type CollectionSummary, type DocumentIssue,
} from '../api/documentCollections'

function UploadDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (detail: CollectionDetail) => void }) {
  const [name, setName] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [ids, setIds] = useState<string[]>([])
  const [chunkSize, setChunkSize] = useState(1000)
  const [chunkOverlap, setChunkOverlap] = useState(100)
  const [issues, setIssues] = useState<DocumentIssue[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setIssues([])
    setError('')
    try {
      const detail = await createCollection({
        name: name.trim(), files, documentIds: ids.map((id) => id.trim() || null), chunkSize, chunkOverlap,
      })
      onCreated(detail)
    } catch (cause) {
      if (cause instanceof CollectionImportError) setIssues(cause.issues)
      else setError(cause instanceof Error ? cause.message : '上传失败')
    } finally {
      setBusy(false)
    }
  }

  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose()
  }}>
    <section className="import-dialog" role="dialog" aria-modal="true" aria-labelledby="document-upload-title">
      <div className="dialog-heading">
        <div><p className="eyebrow">DOCUMENTS</p><h2 id="document-upload-title">上传原文</h2></div>
        <button type="button" className="icon-button" onClick={onClose} title="关闭" aria-label="关闭"><X size={18} /></button>
      </div>
      <form onSubmit={(event) => void submit(event)}>
        <label className="form-group"><span className="form-label">集合名称</span><input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label className="form-group"><span className="form-label">原文文件</span><input type="file" accept=".txt,.md,.markdown" multiple required onChange={(event) => {
          const selected = Array.from(event.target.files ?? [])
          setFiles(selected)
          setIds(selected.map(() => ''))
        }} /></label>
        {files.length > 0 && <div className="document-file-ids">{files.map((file, index) =>
          <label className="form-group" key={`${file.name}-${index}`}><span className="form-label">{file.name} · 文档 ID</span>
            <input value={ids[index] ?? ''} placeholder="自动生成" onChange={(event) => setIds((current) => current.map((id, position) => position === index ? event.target.value : id))} />
          </label>,
        )}</div>}
        <div className="document-settings">
          <label className="form-group"><span className="form-label">切块大小</span><input type="number" min={1} max={10000} required value={chunkSize} onChange={(event) => setChunkSize(Number(event.target.value))} /></label>
          <label className="form-group"><span className="form-label">重叠量</span><input type="number" min={0} max={Math.max(0, chunkSize - 1)} required value={chunkOverlap} onChange={(event) => setChunkOverlap(Number(event.target.value))} /></label>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        {issues.length > 0 && <div className="import-issues" role="alert"><strong>上传失败，共 {issues.length} 处错误</strong><ul>{issues.map((issue, index) =>
          <li key={index}>{issue.filename ?? '集合'}{issue.file_index !== null ? `（文件 ${issue.file_index + 1}）` : ''} · {issue.field}：{issue.message}</li>,
        )}</ul></div>}
        <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={busy || !name.trim() || !files.length || chunkOverlap >= chunkSize}><Upload size={16} />{busy ? '上传中' : '上传'}</button></div>
      </form>
    </section>
  </div>
}

export function DocumentCollectionPage() {
  const [collections, setCollections] = useState<CollectionSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<CollectionDetail | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const items = await fetchCollections()
      setCollections(items)
      setSelectedId((current) => current ?? items[0]?.id ?? null)
      setError('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '加载失败') }
  }, [])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    if (!selectedId) { setDetail(null); return }
    void fetchCollection(selectedId).then(setDetail).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '加载失败'))
  }, [selectedId])

  return <>
    <header className="page-header"><div><p className="eyebrow">SOURCE LIBRARY</p><h1>文档集合</h1></div>
      <button type="button" className="primary-button" onClick={() => setUploadOpen(true)}><Plus size={16} />上传原文</button>
    </header>
    {error && <div className="page-error" role="alert">{error}<button type="button" onClick={() => void refresh()}>重试</button></div>}
    <div className="dataset-layout">
      <aside className="dataset-list"><div className="pane-heading"><h2>集合</h2><span>{collections.length}</span></div>
        {collections.map((item) => <button key={item.id} type="button" className={`dataset-row ${selectedId === item.id ? 'active' : ''}`} onClick={() => setSelectedId(item.id)}><strong>{item.name}</strong><span>{item.document_count} 份文档</span></button>)}
        {!collections.length && <div className="empty-state"><FileText size={25} /><span>暂无文档集合</span></div>}
      </aside>
      <div className="dataset-workspace">{detail && selectedId === detail.id ? <>
        <div className="dataset-toolbar"><div><h2>{detail.name}</h2><span>切块 {detail.chunk_size} 字符 · 重叠 {detail.chunk_overlap} 字符</span></div><div className="batch-counts"><span>{detail.document_count} 份文档</span></div></div>
        <div className="document-detail-list">{detail.documents.map((document) => <section key={document.document_id} className="document-detail" aria-label={document.filename}>
          <div className="document-detail-header"><FileText size={18} /><strong>{document.filename}</strong><code>{document.document_id}</code></div>
          <div className="document-meta"><span>{document.byte_count} 字节</span><span>SHA-256 <code>{document.checksum}</code></span><span>{document.chunks.length} 个切块</span></div>
          <ol className="chunk-list">{document.chunks.map((chunk) => <li key={chunk.position}><div className="chunk-meta"><span>#{chunk.position + 1}</span></div><p>{chunk.text}</p></li>)}</ol>
        </section>)}</div>
      </> : <div className="empty-state"><FileText size={25} /><span>选择文档集合</span></div>}</div>
    </div>
    {uploadOpen && <UploadDialog onClose={() => setUploadOpen(false)} onCreated={(created) => {
      setUploadOpen(false)
      setCollections((current) => [created, ...current])
      setSelectedId(created.id)
      setDetail(created)
    }} />}
  </>
}
