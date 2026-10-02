import { useState } from 'react'

import type { RunCase, RunSummary } from '../api/runs'

type Metric = 'precision' | 'map' | 'ndcg'
const metricLabels: Record<Metric, string> = { precision: 'Precision', map: 'MAP', ndcg: 'NDCG' }
const bins = ['0–0.2', '0.2–0.4', '0.4–0.6', '0.6–0.8', '0.8–1']

function showScore(value: number | null | undefined): string {
  return value === null || value === undefined ? '不适用' : value.toFixed(3)
}

export function RunAggregateView({ run }: { run: RunSummary }) {
  const [metric, setMetric] = useState<Metric>('map')
  const [k, setK] = useState<'10' | '20'>('10')
  const aggregate = run.aggregate
  if (!aggregate) return null
  const selectedMetrics = (run.config.metrics as Metric[] | undefined) ?? ['precision', 'map', 'ndcg']
  const displayMetric = selectedMetrics.includes(metric) ? metric : selectedMetrics[0]
  const counts = aggregate.distribution?.[displayMetric]?.[k] ?? [0, 0, 0, 0, 0]
  const max = Math.max(...counts, 1)
  return <section className="run-results" aria-label="总体指标">
    <div className="pane-heading"><h3>总体指标</h3><span>有效 {aggregate.valid_count} · 不适用 {aggregate.not_applicable_count}</span></div>
    <div className="score-table-wrap"><table className="match-table"><thead><tr><th>指标</th><th>@10</th><th>@20</th></tr></thead><tbody>
      {selectedMetrics.includes('precision') && <tr><th>Precision</th><td>{showScore(aggregate.precision_at_k['10'])}</td><td>{showScore(aggregate.precision_at_k['20'])}</td></tr>}
      {selectedMetrics.includes('map') && <tr><th>MAP</th><td>{showScore(aggregate.map_at_k['10'])}</td><td>{showScore(aggregate.map_at_k['20'])}</td></tr>}
      {selectedMetrics.includes('ndcg') && <tr><th>NDCG</th><td>{showScore(aggregate.ndcg_at_k['10'])}</td><td>{showScore(aggregate.ndcg_at_k['20'])}</td></tr>}
    </tbody></table></div>
    {aggregate.valid_count > 0 && <div className="run-distribution"><div className="distribution-controls"><strong>分数分布</strong><select aria-label="分布指标" value={displayMetric} onChange={(event) => setMetric(event.target.value as Metric)}>{selectedMetrics.map((item) => <option key={item} value={item}>{metricLabels[item]}</option>)}</select><div className="segmented-control" role="group" aria-label="分布 K 值"><button type="button" className={k === '10' ? 'selected' : ''} onClick={() => setK('10')}>@10</button><button type="button" className={k === '20' ? 'selected' : ''} onClick={() => setK('20')}>@20</button></div></div><div className="distribution-bars">{counts.map((count, index) => <div className="distribution-bar" key={index}><div className="distribution-track"><span style={{ height: `${count / max * 100}%` }} /></div><strong>{count}</strong><small>{bins[index]}</small></div>)}</div></div>}
  </section>
}

export function RunCaseDetail({ item }: { item: RunCase }) {
  const [k, setK] = useState<'10' | '20'>('10')
  const score = item.score?.scores[k]
  return <section className="run-case-detail" aria-label="逐题详情">
    <div className="detail-heading"><span className="eyebrow">CASE DETAIL</span><code>{item.case_id}</code></div>
    <h3>{item.question}</h3>
    {item.error && <p className="form-error" role="alert">{item.error}</p>}
    <div className="run-answer-grid"><div><h4>标准答案</h4><p>{item.reference_answer ?? '不适用'}</p></div><div><h4>预测答案</h4><p>{item.answer ?? '未提供'}</p></div></div>
    <div className="run-answer-grid"><div><h4>参考 chunk</h4>{item.reference_chunks?.length ? <ol className="chunk-list">{item.reference_chunks.map((chunk, index) => <li key={index}><div className="chunk-meta">#{index + 1} <code>{chunk.document_id}</code></div><p>{chunk.text}</p></li>)}</ol> : <p>不适用</p>}</div><div><h4>预测 chunk</h4>{item.contexts?.length ? <ol className="chunk-list">{item.contexts.map((chunk, index) => <li key={index}><div className="chunk-meta">#{index + 1} <code>{chunk.document_id}</code></div><p>{chunk.text}</p></li>)}</ol> : <p>未提供</p>}</div></div>
    <div className="run-timing"><span>目标耗时：{item.target_latency_ms === null ? '未提供' : `${item.target_latency_ms.toFixed(1)} ms`}</span><span>评分耗时：{item.elapsed_ms === null ? '未提供' : `${item.elapsed_ms.toFixed(1)} ms`}</span></div>
    {item.score && <section className="run-evidence" aria-label="匹配证据"><div className="distribution-controls"><h4>匹配证据</h4><div className="segmented-control" role="group" aria-label="证据 K 值"><button type="button" className={k === '10' ? 'selected' : ''} onClick={() => setK('10')}>@10</button><button type="button" className={k === '20' ? 'selected' : ''} onClick={() => setK('20')}>@20</button></div></div><p className="evidence-meta">模型 {item.score.model_id} · 阈值 {item.score.threshold} · {item.score.match_rule_version} · {item.score.gain_rule_version}</p><div className="run-score-strip"><span>Precision {showScore(score?.precision)}</span><span>AP {showScore(score?.ap)}</span><span>NDCG {showScore(score?.ndcg)}</span></div><div className="match-table-wrap"><table className="match-table"><thead><tr><th>参考</th><th>预测</th><th>相似度</th><th>判定</th></tr></thead><tbody>{score?.decisions.map((decision) => <tr key={`${decision.reference_index}-${decision.predicted_index}`}><td>#{decision.reference_index + 1}</td><td>#{decision.predicted_index + 1}</td><td>{decision.similarity?.toFixed(3) ?? '—'}</td><td className={decision.selected ? 'match-positive' : ''}>{decision.selected ? '命中' : decision.reason}</td></tr>)}</tbody></table></div></section>}
  </section>
}
