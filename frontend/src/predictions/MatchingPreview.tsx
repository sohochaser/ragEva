import { ScanSearch } from 'lucide-react'
import { useEffect, useState } from 'react'

import { fetchCase, type EvaluationCase } from '../api/datasets'
import { previewMatching, type PreviewResponse } from '../api/matching'
import type { Prediction } from '../api/predictions'

const reasons: Record<string, string> = {
  candidate: '达到阈值',
  below_threshold: '低于阈值',
  document_mismatch: '文档不同',
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
    }).catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '无法读取参考样本') })
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
    } catch (cause) { setError(cause instanceof Error ? cause.message : '匹配预览失败') }
    finally { setBusy(false) }
  }

  const applicable = !!gold?.reference_chunks?.length && !!prediction.contexts?.length
  const threshold = Number(thresholdValue)
  const thresholdValid = thresholdValue.trim() !== '' && Number.isFinite(threshold) && threshold >= -1 && threshold <= 1
  const pairs = result?.pairs.filter((pair) => showAll || pair.reason !== 'document_mismatch') ?? []

  return <section className="matching-preview" aria-labelledby="matching-preview-title">
    <div className="section-heading"><h2 id="matching-preview-title">匹配预览</h2>{result && <span>{result.pairs.filter((pair) => pair.candidate).length} 条候选边</span>}</div>
    <div className="matching-controls">
      <label className="form-group"><span className="form-label">本地模型</span><input list="embedding-models" value={modelName} onChange={(event) => { setModelName(event.target.value); setThresholdValue(''); setResult(null) }} /><datalist id="embedding-models"><option value="BAAI/bge-small-zh-v1.5" /><option value="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" /></datalist></label>
      <label className="form-group threshold-input"><span className="form-label">相似度阈值</span><input type="number" min="-1" max="1" step="0.01" value={thresholdValue} onChange={(event) => setThresholdValue(event.target.value)} /></label>
      <label className="form-group"><span className="form-label">本地模型目录</span><input value={modelPath} onChange={(event) => { setModelPath(event.target.value); setThresholdValue(''); setResult(null) }} placeholder="可选" /></label>
      <label className="offline-option"><input type="checkbox" checked={offline} onChange={(event) => setOffline(event.target.checked)} />仅使用本地文件</label>
      <button className="primary-button" type="button" disabled={!applicable || busy || !modelName.trim() || !thresholdValid} onClick={() => void preview()}><ScanSearch size={16} />{busy ? '匹配中' : '预览'}</button>
    </div>
    {!applicable && <p className="preview-empty">当前样本缺少参考或预测 chunk。</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {result && <><div className="score-table-wrap"><table className="match-table score-table"><thead><tr><th>K</th><th>Precision</th><th>AP</th><th>NDCG</th><th>命中</th></tr></thead><tbody>{result.scores.map((score) => <tr key={score.k}><td>{score.k}</td><td>{score.precision.toFixed(4)}</td><td>{score.ap.toFixed(4)}</td><td>{score.ndcg.toFixed(4)}</td><td>{score.matches.length}</td></tr>)}</tbody></table></div><div className="preview-meta"><code>{result.model_id} · {result.match_rule_version}</code><div className="segmented-control" role="group" aria-label="匹配行筛选"><button type="button" className={!showAll ? 'selected' : ''} onClick={() => setShowAll(false)}>同文档</button><button type="button" className={showAll ? 'selected' : ''} onClick={() => setShowAll(true)}>全部</button></div></div><div className="match-table-wrap"><table className="match-table"><thead><tr><th>参考</th><th>预测</th><th>相似度</th><th>判定</th></tr></thead><tbody>{pairs.map((pair) => <tr key={`${pair.reference_index}-${pair.predicted_index}`}><td>#{pair.reference_index + 1}</td><td>#{pair.predicted_index + 1}</td><td>{pair.similarity === null ? '—' : pair.similarity.toFixed(4)}</td><td className={pair.candidate ? 'match-positive' : ''}>{reasons[pair.reason] ?? pair.reason}</td></tr>)}</tbody></table></div></>}
  </section>
}
