import { FileText, ListPlus, Plus, Upload, X } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent, type KeyboardEvent } from 'react'

import {
  ChunkManifestImportError, CollectionImportError, createCollection, fetchCollection, fetchCollectionVersions, fetchCollections,
  importChunkManifest, type ChunkImportIssue, type CollectionDetail, type CollectionSummary, type DocumentIssue,
} from '../api/documentCollections'
import { uiError } from '../ui/text'

const nameKey = (name: string) => name.trim().toLocaleLowerCase()

function matchedCollection(collections: CollectionSummary[], name: string, chosen: CollectionSummary | null) {
  const matches = collections.filter((item) => nameKey(item.name) === nameKey(name))
  return {
    target: chosen && matches.some((item) => item.group_id === chosen.group_id) ? chosen : matches.length === 1 ? matches[0] : null,
    ambiguous: matches.length > 1 && !chosen,
  }
}

function CollectionNamePicker({ id, collections, name, setName, chosen, setChosen }: {
  id: string; collections: CollectionSummary[]; name: string; setName: (name: string) => void
  chosen: CollectionSummary | null; setChosen: (item: CollectionSummary | null) => void
}) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const matches = collections.filter((item) => item.name.toLocaleLowerCase().includes(nameKey(name)))
  function choose(item: CollectionSummary) {
    setName(item.name)
    setChosen(item)
    setOpen(false)
  }
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') { setOpen(false); return }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setOpen(true)
      setActive((current) => event.key === 'ArrowDown'
        ? Math.min(matches.length - 1, current + 1)
        : current < 0 ? matches.length - 1 : Math.max(0, current - 1))
    }
    if (event.key === 'Enter' && open && active >= 0 && matches.length) {
      event.preventDefault()
      choose(matches[active] ?? matches[0])
    }
  }
  return <div className="collection-name-picker" onBlur={(event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false)
  }}>
    <label className="form-group"><span className="form-label">Collection Name（集合名称）</span>
      <input required maxLength={120} role="combobox" aria-autocomplete="list" aria-expanded={open && matches.length > 0}
        aria-controls={`${id}-options`} aria-activedescendant={open && active >= 0 && matches.length ? `${id}-option-${active}` : undefined}
        value={name} onFocus={() => setOpen(true)} onKeyDown={onKeyDown}
        onChange={(event) => { setName(event.target.value); setChosen(null); setActive(-1); setOpen(true) }} />
    </label>
    {open && matches.length > 0 && <div id={`${id}-options`} className="collection-name-options" role="listbox">
      {matches.map((item, index) => <button id={`${id}-option-${index}`} role="option" aria-selected={chosen?.group_id === item.group_id}
        type="button" className={index === active ? 'active' : ''} key={item.group_id}
        onMouseDown={(event) => event.preventDefault()} onClick={() => choose(item)}>
        <strong>{item.name}</strong><span>{item.source_kind === 'chunks_only' ? 'Chunk Manifest（chunk 清单）' : 'Source Files（原文）'} · v{item.version ?? 1} · {item.group_id.slice(0, 8)}</span>
      </button>)}
    </div>}
  </div>
}

function UploadDialog({ collections, onClose, onCreated }: { collections: CollectionSummary[]; onClose: () => void; onCreated: (detail: CollectionDetail) => void }) {
  const [name, setName] = useState('')
  const [chosen, setChosen] = useState<CollectionSummary | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [ids, setIds] = useState<string[]>([])
  const [chunkSize, setChunkSize] = useState(1000)
  const [chunkOverlap, setChunkOverlap] = useState(100)
  const [issues, setIssues] = useState<DocumentIssue[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { target, ambiguous } = matchedCollection(collections, name, chosen)
  const conflict = target?.source_kind !== undefined && target.source_kind !== 'original_files'
  const size = target?.chunk_size ?? chunkSize
  const overlap = target?.chunk_overlap ?? chunkOverlap

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setIssues([])
    setError('')
    try {
      const detail = await createCollection({
        name: name.trim(), files, documentIds: ids.map((id) => id.trim() || null), chunkSize: size, chunkOverlap: overlap,
        groupId: target?.group_id, expectedVersion: target?.version,
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
        <CollectionNamePicker id="upload-collection" collections={collections} name={name} setName={setName} chosen={chosen} setChosen={setChosen} />
        {name.trim() && <p className="collection-target" role="status">{ambiguous ? 'Choose one matching collection（请选择一个同名集合）' : conflict ? 'Name belongs to a chunk collection（名称属于 chunk 集合）' : target ? `Append to ${target.name}（追加至现有集合） · v${target.version ?? 1}` : 'Create new collection（创建新集合）'}</p>}
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
          <label className="form-group"><span className="form-label">Chunk Size (characters)（切块大小，字符）</span><input type="number" min={1} max={10000} required disabled={Boolean(target)} value={size} onChange={(event) => setChunkSize(Number(event.target.value))} /></label>
          <label className="form-group"><span className="form-label">Chunk Overlap (characters)（重叠量，字符）</span><input type="number" min={0} max={Math.max(0, size - 1)} required disabled={Boolean(target)} value={overlap} onChange={(event) => setChunkOverlap(Number(event.target.value))} /></label>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        {issues.length > 0 && <div className="import-issues" role="alert"><strong>Upload failed, {issues.length} errors（上传失败，共 {issues.length} 处错误）</strong><ul>{issues.map((issue, index) =>
          <li key={index}>{issue.filename ?? 'Collection（集合）'}{issue.file_index !== null ? ` · File ${issue.file_index + 1}（文件 ${issue.file_index + 1}）` : ''} · {issue.field}: {issue.message}</li>,
        )}</ul></div>}
        <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>Cancel（取消）</button><button type="submit" className="primary-button" disabled={busy || !name.trim() || !files.length || overlap >= size || ambiguous || conflict}><Upload size={16} />{busy ? 'Uploading（上传中）' : 'Upload（上传）'}</button></div>
      </form>
    </section>
  </div>
}

function ChunkImportDialog({ collections, onClose, onCreated }: { collections: CollectionSummary[]; onClose: () => void; onCreated: (detail: CollectionDetail) => void }) {
  const [name, setName] = useState('')
  const [chosen, setChosen] = useState<CollectionSummary | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [issues, setIssues] = useState<ChunkImportIssue[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { target, ambiguous } = matchedCollection(collections, name, chosen)
  const conflict = target?.source_kind !== undefined && target.source_kind !== 'chunks_only'

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) return
    setBusy(true)
    setIssues([])
    setError('')
    try { onCreated(await importChunkManifest(name.trim(), file, target?.group_id, target?.version)) }
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
        <CollectionNamePicker id="chunk-collection" collections={collections} name={name} setName={setName} chosen={chosen} setChosen={setChosen} />
        {name.trim() && <p className="collection-target" role="status">{ambiguous ? 'Choose one matching collection（请选择一个同名集合）' : conflict ? 'Name belongs to a source-file collection（名称属于原文集合）' : target ? `Append to ${target.name}（追加至现有集合） · v${target.version ?? 1}` : 'Create new collection（创建新集合）'}</p>}
        <label className="form-group"><span className="form-label">Manifest File（清单文件）</span><input type="file" accept=".csv,.jsonl" title="CSV/JSONL：position、document_id、text" required onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        {issues.length > 0 && <div className="import-issues" role="alert"><strong>Import failed, {issues.length} errors（导入失败，共 {issues.length} 处错误）</strong><ul>{issues.map((issue, index) =>
          <li key={`${issue.line}-${issue.field}-${index}`}>{issue.line ? `Line ${issue.line}（第 ${issue.line} 行）` : 'File（文件）'}{issue.field ? ` · ${issue.field}` : ''}: {issue.message}</li>,
        )}</ul></div>}
        <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>Cancel（取消）</button>
          <button type="submit" className="primary-button" disabled={busy || !name.trim() || !file || ambiguous || conflict}><Upload size={16} />{busy ? 'Importing（导入中）' : 'Import（导入）'}</button></div>
      </form>
    </section>
  </div>
}

export function DocumentCollectionPage() {
  const [collections, setCollections] = useState<CollectionSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<CollectionDetail | null>(null)
  const [versions, setVersions] = useState<CollectionSummary[]>([])
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
    void fetchCollectionVersions(selectedId).then(setVersions).catch((cause: unknown) => setError(uiError(cause, 'Unable to load versions', '加载版本失败')))
  }, [selectedId])

  function created(collection: CollectionDetail) {
    setUploadOpen(false)
    setChunkImportOpen(false)
    setCollections((current) => [collection, ...current.filter((item) => (item.group_id ?? item.id) !== collection.group_id)])
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
        {collections.map((item) => <button key={item.id} type="button" className={`dataset-row ${detail?.group_id === item.group_id ? 'active' : ''}`} onClick={() => setSelectedId(item.id)}><strong>{item.name}</strong><span>{item.source_kind === 'chunks_only' ? 'Chunk Manifest（chunk 清单）' : 'Source Files（原文）'} · v{item.version ?? 1} · {item.document_count} document IDs（{item.document_count} 个文档 ID）</span></button>)}
        {!collections.length && <div className="empty-state"><FileText size={25} /><span>No Document Collections Yet（暂无文档集合）</span></div>}
      </aside>
      <div className="dataset-workspace">{detail && selectedId === detail.id ? <>
        <div className="dataset-toolbar"><div><h2>{detail.name} · v{detail.version ?? 1}</h2><span>{detail.source_kind === 'chunks_only' ? 'No Source Files（无原文文件）' : `Chunk Size（切块大小） ${detail.chunk_size} characters（字符） · Overlap（重叠量） ${detail.chunk_overlap} characters（字符）`}</span></div><div className="batch-counts"><span>Added（新增） {detail.added_document_count ?? detail.document_count} document IDs（文档 ID） · {detail.added_chunk_count ?? detail.chunks.length} chunks（切块）</span><span>Total（累计） {detail.document_count} document IDs（文档 ID） · {detail.chunks.length} chunks（切块）</span></div></div>
        {versions.length > 1 && <label className="form-group collection-versions"><span className="form-label">Snapshot Version（快照版本）</span><select value={detail.id} onChange={(event) => setSelectedId(event.target.value)}>{versions.map((item) => <option key={item.id} value={item.id}>v{item.version} · {item.document_count} document IDs（{item.document_count} 个文档 ID）</option>)}</select></label>}
        {detail.source_kind === 'chunks_only' ? <div className="document-detail-list"><section className="document-detail" aria-label="Chunk Manifest（chunk 清单）">
          <ol className="chunk-list">{detail.chunks.map((chunk) => <li key={chunk.position}><div className="chunk-meta"><span>#{chunk.position + 1}</span><code>{chunk.document_id}</code><span>{Array.from(chunk.text).length} characters（字符）</span></div><p>{chunk.text}</p></li>)}</ol>
        </section></div> : <div className="document-detail-list">{detail.documents.map((document) => <section key={document.document_id} className="document-detail" aria-label={document.filename ?? document.document_id}>
          <div className="document-detail-header"><FileText size={18} /><strong>{document.filename}</strong><code>{document.document_id}</code></div>
          <div className="document-meta"><span>{document.byte_count === null ? 'Unknown Size（大小未知）' : `${document.byte_count} bytes（字节）`}</span><span>SHA-256 <code>{document.checksum}</code></span><span>{document.chunks.length} chunks（{document.chunks.length} 个切块）</span></div>
          <ol className="chunk-list">{document.chunks.map((chunk) => <li key={chunk.position}><div className="chunk-meta"><span>#{chunk.position + 1}</span><span>{Array.from(chunk.text).length} characters（字符）</span></div><p>{chunk.text}</p></li>)}</ol>
        </section>)}</div>}
      </> : <div className="empty-state"><FileText size={25} /><span>Select Document Collection（选择文档集合）</span></div>}</div>
    </div>
    {uploadOpen && <UploadDialog collections={collections} onClose={() => setUploadOpen(false)} onCreated={created} />}
    {chunkImportOpen && <ChunkImportDialog collections={collections} onClose={() => setChunkImportOpen(false)} onCreated={created} />}
  </>
}
