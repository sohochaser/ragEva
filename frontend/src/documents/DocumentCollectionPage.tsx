import { FileText, ListPlus, Plus, Upload, X } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'

import {
  ChunkManifestImportError, CollectionImportError, createCollection, fetchCollection, fetchCollections,
  importChunkManifest, type ChunkImportIssue, type CollectionDetail, type CollectionSummary, type DocumentIssue,
} from '../api/documentCollections'
import { uiError } from '../ui/text'

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
      else setError(uiError(cause, 'Upload failed', '上传失败'))
    } finally {
      setBusy(false)
    }
  }

  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose()
  }}>
    <section className="import-dialog" role="dialog" aria-modal="true" aria-labelledby="document-upload-title">
      <div className="dialog-heading">
        <div><p className="eyebrow">Documents（文档）</p><h2 id="document-upload-title">Upload Documents（上传原文）</h2></div>
        <button type="button" className="icon-button" onClick={onClose} title="Close（关闭）" aria-label="Close（关闭）"><X size={18} /></button>
      </div>
      <form onSubmit={(event) => void submit(event)}>
        <label className="form-group"><span className="form-label">Collection Name（集合名称）</span><input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label className="form-group"><span className="form-label">Source Files（原文文件）</span><input type="file" accept=".txt,.md,.markdown,.docx,.pdf" multiple required onChange={(event) => {
          const selected = Array.from(event.target.files ?? [])
          setFiles(selected)
          setIds(selected.map(() => ''))
        }} /></label>
        {files.length > 0 && <div className="document-file-ids">{files.map((file, index) =>
          <label className="form-group" key={`${file.name}-${index}`}><span className="form-label">{file.name} · {file.size} bytes（字节） · Document ID（文档 ID）</span>
            <input value={ids[index] ?? ''} placeholder="Auto Generate（自动生成）" onChange={(event) => setIds((current) => current.map((id, position) => position === index ? event.target.value : id))} />
          </label>,
        )}</div>}
        <div className="document-settings">
          <label className="form-group"><span className="form-label">Chunk Size (characters)（切块大小，字符）</span><input type="number" min={1} max={10000} required value={chunkSize} onChange={(event) => setChunkSize(Number(event.target.value))} /></label>
          <label className="form-group"><span className="form-label">Chunk Overlap (characters)（重叠量，字符）</span><input type="number" min={0} max={Math.max(0, chunkSize - 1)} required value={chunkOverlap} onChange={(event) => setChunkOverlap(Number(event.target.value))} /></label>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        {issues.length > 0 && <div className="import-issues" role="alert"><strong>Upload failed, {issues.length} errors（上传失败，共 {issues.length} 处错误）</strong><ul>{issues.map((issue, index) =>
          <li key={index}>{issue.filename ?? 'Collection（集合）'}{issue.file_index !== null ? ` · File ${issue.file_index + 1}（文件 ${issue.file_index + 1}）` : ''} · {issue.field}: {issue.message}</li>,
        )}</ul></div>}
        <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>Cancel（取消）</button><button type="submit" className="primary-button" disabled={busy || !name.trim() || !files.length || chunkOverlap >= chunkSize}><Upload size={16} />{busy ? 'Uploading（上传中）' : 'Upload（上传）'}</button></div>
      </form>
    </section>
  </div>
}

function ChunkImportDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (detail: CollectionDetail) => void }) {
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [issues, setIssues] = useState<ChunkImportIssue[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) return
    setBusy(true)
    setIssues([])
    setError('')
    try { onCreated(await importChunkManifest(name.trim(), file)) }
    catch (cause) {
      if (cause instanceof ChunkManifestImportError) setIssues(cause.issues)
      else setError(uiError(cause, 'Import failed', '导入失败'))
    } finally { setBusy(false) }
  }

  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose()
  }}>
    <section className="import-dialog" role="dialog" aria-modal="true" aria-labelledby="chunk-import-title">
      <div className="dialog-heading"><div><p className="eyebrow">Chunks（切块）</p><h2 id="chunk-import-title">Import Chunk Manifest（导入 chunk 清单）</h2></div>
        <button type="button" className="icon-button" onClick={onClose} title="Close（关闭）" aria-label="Close（关闭）"><X size={18} /></button></div>
      <form onSubmit={(event) => void submit(event)}>
        <label className="form-group"><span className="form-label">Collection Name（集合名称）</span><input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label className="form-group"><span className="form-label">Manifest File（清单文件）</span><input type="file" accept=".csv,.jsonl" title="CSV/JSONL：position、document_id、text" required onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        {issues.length > 0 && <div className="import-issues" role="alert"><strong>Import failed, {issues.length} errors（导入失败，共 {issues.length} 处错误）</strong><ul>{issues.map((issue, index) =>
          <li key={`${issue.line}-${issue.field}-${index}`}>{issue.line ? `Line ${issue.line}（第 ${issue.line} 行）` : 'File（文件）'}{issue.field ? ` · ${issue.field}` : ''}: {issue.message}</li>,
        )}</ul></div>}
        <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>Cancel（取消）</button>
          <button type="submit" className="primary-button" disabled={busy || !name.trim() || !file}><Upload size={16} />{busy ? 'Importing（导入中）' : 'Import（导入）'}</button></div>
      </form>
    </section>
  </div>
}

export function DocumentCollectionPage() {
  const [collections, setCollections] = useState<CollectionSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<CollectionDetail | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [chunkImportOpen, setChunkImportOpen] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const items = await fetchCollections()
      setCollections(items)
      setSelectedId((current) => current ?? items[0]?.id ?? null)
      setError('')
    } catch (cause) { setError(uiError(cause, 'Unable to load collections', '加载失败')) }
  }, [])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    if (!selectedId) { setDetail(null); return }
    void fetchCollection(selectedId).then(setDetail).catch((cause: unknown) => setError(uiError(cause, 'Unable to load collection', '加载失败')))
  }, [selectedId])

  function created(collection: CollectionDetail) {
    setUploadOpen(false)
    setChunkImportOpen(false)
    setCollections((current) => [collection, ...current])
    setSelectedId(collection.id)
    setDetail(collection)
  }

  return <>
    <header className="page-header document-page-header"><div><p className="eyebrow">Source Library（来源库）</p><h1>Document Collections（文档集合）</h1></div>
      <div className="page-actions"><button type="button" className="secondary-button" onClick={() => setChunkImportOpen(true)}><ListPlus size={16} />Import Chunk Manifest（导入 chunk 清单）</button>
        <button type="button" className="primary-button" onClick={() => setUploadOpen(true)}><Plus size={16} />Upload Documents（上传原文）</button></div>
    </header>
    {error && <div className="page-error" role="alert">{error}<button type="button" onClick={() => void refresh()}>Retry（重试）</button></div>}
    <div className="dataset-layout">
      <aside className="dataset-list"><div className="pane-heading"><h2>Collections（集合）</h2><span>{collections.length}</span></div>
        {collections.map((item) => <button key={item.id} type="button" className={`dataset-row ${selectedId === item.id ? 'active' : ''}`} onClick={() => setSelectedId(item.id)}><strong>{item.name}</strong><span>{item.source_kind === 'chunks_only' ? 'Chunk Manifest（chunk 清单）' : 'Source Files（原文）'} · {item.document_count} document IDs（{item.document_count} 个文档 ID）</span></button>)}
        {!collections.length && <div className="empty-state"><FileText size={25} /><span>No Document Collections Yet（暂无文档集合）</span></div>}
      </aside>
      <div className="dataset-workspace">{detail && selectedId === detail.id ? <>
        <div className="dataset-toolbar"><div><h2>{detail.name}</h2><span>{detail.source_kind === 'chunks_only' ? 'No Source Files（无原文文件）' : `Chunk Size（切块大小） ${detail.chunk_size} characters（字符） · Overlap（重叠量） ${detail.chunk_overlap} characters（字符）`}</span></div><div className="batch-counts"><span>{detail.chunks.length} chunks（{detail.chunks.length} 个切块）</span></div></div>
        {detail.source_kind === 'chunks_only' ? <div className="document-detail-list"><section className="document-detail" aria-label="Chunk Manifest（chunk 清单）">
          <ol className="chunk-list">{detail.chunks.map((chunk) => <li key={chunk.position}><div className="chunk-meta"><span>#{chunk.position + 1}</span><code>{chunk.document_id}</code><span>{Array.from(chunk.text).length} characters（字符）</span></div><p>{chunk.text}</p></li>)}</ol>
        </section></div> : <div className="document-detail-list">{detail.documents.map((document) => <section key={document.document_id} className="document-detail" aria-label={document.filename ?? document.document_id}>
          <div className="document-detail-header"><FileText size={18} /><strong>{document.filename}</strong><code>{document.document_id}</code></div>
          <div className="document-meta"><span>{document.byte_count === null ? 'Unknown Size（大小未知）' : `${document.byte_count} bytes（字节）`}</span><span>SHA-256 <code>{document.checksum}</code></span><span>{document.chunks.length} chunks（{document.chunks.length} 个切块）</span></div>
          <ol className="chunk-list">{document.chunks.map((chunk) => <li key={chunk.position}><div className="chunk-meta"><span>#{chunk.position + 1}</span><span>{Array.from(chunk.text).length} characters（字符）</span></div><p>{chunk.text}</p></li>)}</ol>
        </section>)}</div>}
      </> : <div className="empty-state"><FileText size={25} /><span>Select Document Collection（选择文档集合）</span></div>}</div>
    </div>
    {uploadOpen && <UploadDialog onClose={() => setUploadOpen(false)} onCreated={created} />}
    {chunkImportOpen && <ChunkImportDialog onClose={() => setChunkImportOpen(false)} onCreated={created} />}
  </>
}
