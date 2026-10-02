import { ScanSearch } from 'lucide-react'
import { useEffect, useState } from 'react'

import { fetchCase, type EvaluationCase } from '../api/datasets'
import { previewMatching, type PreviewResponse } from '../api/matching'
import type { Prediction } from '../api/predictions'
import { uiError } from '../ui/text'

const reasons: Record<string, string> = {
  candidate: 'Above Threshold（达到阈值）',
  below_threshold: 'Below Threshold（低于阈值）',
  document_mismatch: 'Different Document（文档不同）',
}

export function MatchingPreview({ datasetId, version, prediction }: {
  datasetId: string
  version: number
  prediction: Prediction
}) {
  const [gold, setGold] = useState<EvaluationCase | null>(null)
  const [modelName, setModelName] = useState('BAAI/bge-small-zh-v1.5')
  const [modelPath, setModelPath] = useState('')
  const [offline, setOffline] = useState(false)
  const [thresholdValue, setThresholdValue] = useState('0.8')
  const [result, setResult] = useState<PreviewResponse | null>(null)
  const [showAll, setShowAll] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setGold(null)
    setResult(null)
    void fetchCase(datasetId, version, prediction.case_id).then((item) => {
      if (active) { setGold(item); setError('') }
    }).catch((cause: unknown) => { if (active) setError(uiError(cause, 'Unable to load reference case', '无法读取参考样本')) })
    return () => { active = false }
  }, [datasetId, version, prediction.case_id])

  async function preview() {
    if (!gold?.reference_chunks || !prediction.contexts) return
    setBusy(true)
    setError('')
    setResult(null)
    try {
      setResult(await previewMatching({
        referenceChunks: gold.reference_chunks,
        predictedChunks: prediction.contexts,
        modelName: modelName.trim(), modelPath: modelPath.trim(), offline,
        threshold: Number(thresholdValue),
      }))
    } catch (cause) { setError(uiError(cause, 'Match preview failed', '匹配预览失败')) }
    finally { setBusy(false) }
  }

  const applicable = !!gold?.reference_chunks?.length && !!prediction.contexts?.length
  const threshold = Number(thresholdValue)
  const thresholdValid = thresholdValue.trim() !== '' && Number.isFinite(threshold) && threshold >= -1 && threshold <= 1
  const pairs = result?.pairs.filter((pair) => showAll || pair.reason !== 'document_mismatch') ?? []

  return <section className="matching-preview" aria-labelledby="matching-preview-title">
    <div className="section-heading"><h2 id="matching-preview-title">Match Preview（匹配预览）</h2>{result && <span>{result.pairs.filter((pair) => pair.candidate).length} candidate edges（{result.pairs.filter((pair) => pair.candidate).length} 条候选边）</span>}</div>
    <div className="matching-controls">
      <label className="form-group"><span className="form-label">Local Model（本地模型）</span><input list="embedding-models" value={modelName} onChange={(event) => { setModelName(event.target.value); setThresholdValue(''); setResult(null) }} /><datalist id="embedding-models"><option value="BAAI/bge-small-zh-v1.5" /><option value="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" /></datalist></label>
      <label className="form-group threshold-input"><span className="form-label">Similarity Threshold (-1 to 1, unitless)（相似度阈值，-1 至 1，无单位）</span><input type="number" min="-1" max="1" step="0.01" value={thresholdValue} onChange={(event) => setThresholdValue(event.target.value)} /></label>
      <label className="form-group"><span className="form-label">Local Model Directory（本地模型目录）</span><input value={modelPath} onChange={(event) => { setModelPath(event.target.value); setThresholdValue(''); setResult(null) }} placeholder="Optional（可选）" /></label>
      <label className="offline-option"><input type="checkbox" checked={offline} onChange={(event) => setOffline(event.target.checked)} />Use Local Files Only（仅使用本地文件）</label>
      <button className="primary-button" type="button" disabled={!applicable || busy || !modelName.trim() || !thresholdValid} onClick={() => void preview()}><ScanSearch size={16} />{busy ? 'Matching（匹配中）' : 'Preview（预览）'}</button>
    </div>
    {!applicable && <p className="preview-empty">This case has no reference or predicted chunks.（当前样本缺少参考或预测 chunk。）</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {result && <><div className="score-table-wrap"><table className="match-table score-table"><thead><tr><th>K (retrieved chunks)（检索切块数）</th><th>Precision (0–1, unitless)（精确率，0–1，无单位）</th><th>AP (0–1, unitless)（平均精确率，0–1，无单位）</th><th>NDCG (0–1, unitless)（归一化折损累计增益，0–1，无单位）</th><th>Matched Chunks（命中切块）</th></tr></thead><tbody>{result.scores.map((score) => <tr key={score.k}><td>{score.k}</td><td>{score.precision.toFixed(4)}</td><td>{score.ap.toFixed(4)}</td><td>{score.ndcg.toFixed(4)}</td><td>{score.matches.length}</td></tr>)}</tbody></table></div><div className="preview-meta"><code>{result.model_id} · {result.match_rule_version}</code><div className="segmented-control" role="group" aria-label="Match Row Filter（匹配行筛选）"><button type="button" className={!showAll ? 'selected' : ''} onClick={() => setShowAll(false)}>Same Document（同文档）</button><button type="button" className={showAll ? 'selected' : ''} onClick={() => setShowAll(true)}>All（全部）</button></div></div><div className="match-table-wrap"><table className="match-table"><thead><tr><th>Reference（参考）</th><th>Predictions（预测）</th><th>Similarity (-1 to 1, unitless)（相似度，-1 至 1，无单位）</th><th>Decision（判定）</th></tr></thead><tbody>{pairs.map((pair) => <tr key={`${pair.reference_index}-${pair.predicted_index}`}><td>#{pair.reference_index + 1}</td><td>#{pair.predicted_index + 1}</td><td>{pair.similarity === null ? 'Unknown（未知）' : pair.similarity.toFixed(4)}</td><td className={pair.candidate ? 'match-positive' : ''}>{reasons[pair.reason] ?? pair.reason}</td></tr>)}</tbody></table></div></>}
  </section>
}
