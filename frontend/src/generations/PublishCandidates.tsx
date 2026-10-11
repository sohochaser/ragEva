import { ArrowRight, Upload } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'

import { fetchDatasets, type DatasetSummary, type VersionSummary } from '../api/datasets'
import {
  CandidatePublicationError, publishCandidates, type GeneratedCandidate,
} from '../api/generations'
import { uiError } from '../ui/text'

export function PublishCandidates({ candidates, onOpenDatasets }: {
  candidates: GeneratedCandidate[]
  onOpenDatasets?: (version: VersionSummary) => void
}) {
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [mode, setMode] = useState<'new' | 'existing'>('new')
  const [name, setName] = useState('')
  const [datasetId, setDatasetId] = useState('')
  const [published, setPublished] = useState<VersionSummary | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void fetchDatasets().then((items) => {
      setDatasets(items)
      setDatasetId((current) => current || items[0]?.id || '')
    }).catch((cause: unknown) => setError(uiError(cause, 'Unable to load datasets', '数据集加载失败')))
  }, [])

  const approved = candidates.filter((candidate) => candidate.status === 'approved')
  const selected = selectedIds.filter((id) => approved.some((candidate) => candidate.id === id))
  const target = datasets.find((dataset) => dataset.id === datasetId)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selected.length) return
    setBusy(true)
    setError('')
    setPublished(null)
    try {
      const result = await publishCandidates(mode === 'new' ? {
        candidate_ids: selected, dataset_name: name.trim(), dataset_id: null, expected_version: null,
      } : {
        candidate_ids: selected, dataset_name: null, dataset_id: datasetId,
        expected_version: target?.latest_version ?? null,
      })
      setPublished(result)
      setSelectedIds([])
      setDatasets(await fetchDatasets())
    } catch (cause) {
      if (cause instanceof CandidatePublicationError) {
        setError(`Publication failed（发布失败）: ${cause.issues.map((issue) => issue.message).join('；')}`)
      } else {
        setError(uiError(cause, 'Publication failed', '发布失败'))
      }
    } finally { setBusy(false) }
  }

  return <section className="candidate-publish" aria-label="Publish Candidates（发布候选）">
    <div className="candidate-publish-heading"><h3>Publish Candidates（发布候选）</h3><span>Approved（已批准） {approved.length} · Selected（已选） {selected.length}</span></div>
    {approved.length > 0 && <form onSubmit={(event) => void submit(event)}>
      <div className="candidate-publish-list">{approved.map((candidate) => <label key={candidate.id}><input type="checkbox" checked={selected.includes(candidate.id)} onChange={(event) => setSelectedIds((items) => event.target.checked ? [...items, candidate.id] : items.filter((id) => id !== candidate.id))} /><span>{candidate.question}</span></label>)}</div>
      <div className="candidate-publish-target"><div className="segmented-control" role="group" aria-label="Publish Destination（发布目标）"><button type="button" className={mode === 'new' ? 'selected' : ''} onClick={() => setMode('new')}>New Dataset（新数据集）</button><button type="button" className={mode === 'existing' ? 'selected' : ''} disabled={!datasets.length} onClick={() => setMode('existing')}>Existing Dataset（已有数据集）</button></div>
        {mode === 'new' ? <label className="form-group"><span className="form-label">Dataset Name（数据集名称）</span><input value={name} onChange={(event) => setName(event.target.value)} required maxLength={120} /></label> : <label className="form-group"><span className="form-label">Datasets（数据集）</span><select value={datasetId} required onChange={(event) => setDatasetId(event.target.value)}>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name} · v{dataset.latest_version}</option>)}</select></label>}
      </div>
      <div className="candidate-publish-actions"><button type="submit" className="primary-button" disabled={busy || !selected.length || (mode === 'new' ? !name.trim() : !target)}><Upload size={14} />{busy ? 'Publishing（发布中）' : 'Publish as Dataset Version（发布为数据集版本）'}</button></div>
    </form>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {published && <div className="candidate-publish-success" role="status"><span>Published（已发布） v{published.version} · {published.case_count} cases（{published.case_count} 条样本）</span>{onOpenDatasets && <button type="button" onClick={() => onOpenDatasets(published)}>View Dataset（查看数据集） <ArrowRight size={14} /></button>}</div>}
  </section>
}
