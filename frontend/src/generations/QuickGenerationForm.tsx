import { RotateCcw, Sparkles, Upload } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { CollectionImportError, createCollection, type CollectionDetail, type DocumentIssue } from '../api/documentCollections'
import { startGeneration, type GenerationRun } from '../api/generations'
import type { OnlineModel } from '../api/scenarios'
import { uiError } from '../ui/text'

export function QuickGenerationForm({ models, modelId, onModelChange, onCollectionCreated, onGenerationCreated }: {
  models: OnlineModel[]
  modelId: string
  onModelChange: (id: string) => void
  onCollectionCreated: (collection: CollectionDetail) => void
  onGenerationCreated: (run: GenerationRun) => void
}) {
  const [name, setName] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [uploadKey, setUploadKey] = useState(0)
  const [targetCount, setTargetCount] = useState(10)
  const [savedCollection, setSavedCollection] = useState<CollectionDetail | null>(null)
  const [issues, setIssues] = useState<DocumentIssue[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!modelId || (!savedCollection && (!name.trim() || !files.length))) return
    setBusy(true)
    setIssues([])
    setError('')
    let collection = savedCollection
    try {
      if (!collection) {
        collection = await createCollection({
          name: name.trim(), files, documentIds: files.map(() => null), chunkSize: 1000, chunkOverlap: 100,
        })
        setSavedCollection(collection)
        onCollectionCreated(collection)
      }
      const run = await startGeneration(collection.id, {
        model_id: modelId,
        target_count: targetCount,
        multi_chunk_ratio: 0,
        language: '中文',
        question_type: '事实问答',
        instructions: '',
        max_calls: null,
        max_concurrency: 4,
      })
      onGenerationCreated(run)
      setSavedCollection(null)
      setFiles([])
      setUploadKey((value) => value + 1)
      setName('')
    } catch (cause) {
      if (cause instanceof CollectionImportError) setIssues(cause.issues)
      else setError(uiError(cause, collection ? 'Generation could not start; documents were saved' : 'Upload failed', collection ? '生成未启动；文档已保存' : '上传失败'))
    } finally {
      setBusy(false)
    }
  }

  return <section className="quick-generation" aria-label="Upload and Generate（上传并生成）">
    <div className="section-heading"><h2>Upload and Generate（上传并生成）</h2></div>
    <form className="quick-generation-form" onSubmit={(event) => void submit(event)}>
      {savedCollection ? <div className="quick-generation-saved" role="status"><strong>{savedCollection.name}</strong><span>Documents Saved · Generation Pending（文档已保存，等待生成）</span><button type="button" className="secondary-button" onClick={() => { setSavedCollection(null); setUploadKey((value) => value + 1); setError('') }}><RotateCcw size={14} />New Upload（重新上传）</button></div> : <>
        <label className="form-group"><span className="form-label">Source Documents（来源文档）</span><input key={uploadKey} type="file" accept=".txt,.md,.markdown,.docx,.pdf" multiple onChange={(event) => {
          const selected = Array.from(event.target.files ?? [])
          setFiles(selected)
          setName((current) => current || selected[0]?.name.replace(/\.[^.]+$/, '') || '')
        }} /></label>
        <label className="form-group"><span className="form-label">Collection Name（集合名称）</span><input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} /></label>
      </>}
      <label className="form-group"><span className="form-label">Generation Model（生成模型）</span><select required value={modelId} onChange={(event) => onModelChange(event.target.value)}><option value="">Select Model（选择模型）</option>{models.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.model_name}</option>)}</select></label>
      <label className="form-group"><span className="form-label">Question Count（题目数量）</span><input type="number" min="1" max="1000" required value={targetCount} onChange={(event) => setTargetCount(Number(event.target.value))} /></label>
      <button type="submit" className="primary-button" disabled={busy || !modelId || (!savedCollection && (!name.trim() || !files.length))}>{savedCollection ? <Sparkles size={15} /> : <Upload size={15} />}{busy ? 'Working（处理中）' : savedCollection ? 'Retry Generation（重试生成）' : 'Upload and Generate（上传并生成）'}</button>
    </form>
    {error && <p className="form-error" role="alert">{error}</p>}
    {issues.length > 0 && <ul className="import-issues" role="alert">{issues.map((issue, index) => <li key={`${issue.file_index}-${issue.field}-${index}`}>{issue.filename ?? 'Collection（集合）'} · {issue.field}: {issue.message}</li>)}</ul>}
  </section>
}
