import { useState } from 'react'

import type { RunCase, RunSummary } from '../api/runs'
import { TraceLink } from '../trace/TraceLink'

type Metric = 'precision' | 'map' | 'ndcg'
const metricLabels: Record<Metric, string> = { precision: 'Precision（精确率）', map: 'MAP（平均精确率均值）', ndcg: 'NDCG（归一化折损累计增益）' }
const answerLabels: Record<string, string> = { faithfulness: 'Faithfulness（忠实度）', relevance: 'Relevance（相关性）', correctness: 'Correctness（正确性）' }
const bins = ['0–0.2', '0.2–0.4', '0.4–0.6', '0.6–0.8', '0.8–1']

function showScore(value: number | null | undefined): string {
  return value === null || value === undefined ? 'Not Applicable（不适用）' : value.toFixed(3)
}

export function RunAggregateView({ run }: { run: RunSummary }) {
  const [metric, setMetric] = useState<Metric>('map')
  const [k, setK] = useState<'10' | '20'>('10')
  const aggregate = run.aggregate
  if (!aggregate) return null
  const answerMetrics = aggregate.answer_metrics ?? {}
  const hasRetrieval = run.config.mode !== 'answer'
  const selectedMetrics = (run.config.metrics as Metric[] | undefined) ?? ['precision', 'map', 'ndcg']
  const displayMetric = selectedMetrics.includes(metric) ? metric : selectedMetrics[0]
  const counts = aggregate.distribution?.[displayMetric]?.[k] ?? [0, 0, 0, 0, 0]
  const max = Math.max(...counts, 1)
  return <section className="run-results" aria-label="Overall Metrics（总体指标）">
    <div className="pane-heading"><h3>Overall Metrics（总体指标）</h3>{hasRetrieval && <span>Valid Retrieval（检索有效） {aggregate.valid_count} · Not Applicable（不适用） {aggregate.not_applicable_count}</span>}</div>
    {hasRetrieval && <>
    <div className="score-table-wrap"><table className="match-table"><thead><tr><th>Metrics（指标）</th><th>@10</th><th>@20</th></tr></thead><tbody>
      {selectedMetrics.includes('precision') && <tr><th>{metricLabels.precision}</th><td>{showScore(aggregate.precision_at_k['10'])}</td><td>{showScore(aggregate.precision_at_k['20'])}</td></tr>}
      {selectedMetrics.includes('map') && <tr><th>{metricLabels.map}</th><td>{showScore(aggregate.map_at_k['10'])}</td><td>{showScore(aggregate.map_at_k['20'])}</td></tr>}
      {selectedMetrics.includes('ndcg') && <tr><th>{metricLabels.ndcg}</th><td>{showScore(aggregate.ndcg_at_k['10'])}</td><td>{showScore(aggregate.ndcg_at_k['20'])}</td></tr>}
    </tbody></table></div>
    {aggregate.valid_count > 0 && <div className="run-distribution"><div className="distribution-controls"><strong>Score Distribution（分数分布）</strong><select aria-label="Distribution Metric（分布指标）" value={displayMetric} onChange={(event) => setMetric(event.target.value as Metric)}>{selectedMetrics.map((item) => <option key={item} value={item}>{metricLabels[item]}</option>)}</select><div className="segmented-control" role="group" aria-label="Distribution K Value（分布 K 值）"><button type="button" className={k === '10' ? 'selected' : ''} onClick={() => setK('10')}>@10</button><button type="button" className={k === '20' ? 'selected' : ''} onClick={() => setK('20')}>@20</button></div></div><div className="distribution-bars">{counts.map((count, index) => <div className="distribution-bar" key={index}><div className="distribution-track"><span style={{ height: `${count / max * 100}%` }} /></div><strong>{count}</strong><small>{bins[index]}</small></div>)}</div></div>}
    </>}
    {Object.keys(answerMetrics).length > 0 && <div className="score-table-wrap"><table className="match-table"><thead><tr><th>Answer Metrics（回答指标）</th><th>Average（均分）</th><th>Valid（有效）</th><th>Failed（失败）</th><th>Not Applicable（不适用）</th></tr></thead><tbody>{Object.entries(answerMetrics).map(([key, value]) => <tr key={key}><th>{answerLabels[key] ?? key}</th><td>{showScore(value.mean_score)}</td><td>{value.valid_count}</td><td>{value.failed_count}</td><td>{value.not_applicable_count}</td></tr>)}</tbody></table></div>}
  </section>
}

export function RunCaseDetail({ item }: { item: RunCase }) {
  const [k, setK] = useState<'10' | '20'>('10')
  const score = item.score?.scores[k]
  const answerMetrics = item.answer_metrics ?? {}
  return <section className="run-case-detail" aria-label="Case Details（逐题详情）">
    <div className="detail-heading"><span className="eyebrow">Case Detail（样本详情）</span><code>{item.case_id}</code></div>
    <div className="trace-links"><TraceLink trace={item.trace} label="Scoring Trace（评分 trace）" /><TraceLink trace={item.target_trace} label="Target Call Trace（目标调用 trace）" /></div>
    <h3>{item.question}</h3>
    {item.error && <p className="form-error" role="alert">{item.error}</p>}
    <div className="run-answer-grid"><div><h4>Reference Answer（标准答案）</h4><p>{item.reference_answer ?? 'Not Applicable（不适用）'}</p></div><div><h4>Predicted Answer（预测答案）</h4><p>{item.answer ?? 'Not Provided（未提供）'}</p></div></div>
    {Object.keys(answerMetrics).length > 0 && <section className="run-answer-scores" aria-label="Answer Scoring（回答评分）"><h4>Answer Scoring（回答评分）</h4>{Object.entries(answerMetrics).map(([key, value]) => <div key={key} className="run-answer-score"><strong>{answerLabels[key] ?? key}</strong><span>{value.status === 'success' ? showScore(value.score) : value.status === 'failed' ? 'Failed（失败）' : 'Not Applicable（不适用）'}</span><p>{value.reason ?? value.error ?? ''}</p><small>{value.model_name} · {value.prompt_version} · {value.criteria}</small>{value.raw_response && <details><summary>Raw Model Response（原始模型响应）</summary><pre>{value.raw_response}</pre></details>}</div>)}</section>}
    <div className="run-answer-grid"><div><h4>Reference Chunks（参考 chunk）</h4>{item.reference_chunks?.length ? <ol className="chunk-list">{item.reference_chunks.map((chunk, index) => <li key={index}><div className="chunk-meta">#{index + 1} <code>{chunk.document_id}</code></div><p>{chunk.text}</p></li>)}</ol> : <p>Not Applicable（不适用）</p>}</div><div><h4>Predicted Chunks（预测 chunk）</h4>{item.contexts?.length ? <ol className="chunk-list">{item.contexts.map((chunk, index) => <li key={index}><div className="chunk-meta">#{index + 1} <code>{chunk.document_id}</code></div><p>{chunk.text}</p></li>)}</ol> : <p>Not Provided（未提供）</p>}</div></div>
    <div className="run-timing"><span>Target Latency（目标耗时）：{item.target_latency_ms === null ? 'Not Provided（未提供）' : `${item.target_latency_ms.toFixed(1)} ms（毫秒）`}</span><span>Scoring Time（评分耗时）：{item.elapsed_ms === null ? 'Not Provided（未提供）' : `${item.elapsed_ms.toFixed(1)} ms（毫秒）`}</span>{item.target_usage && <span>Target Tokens（目标词元）：Input（输入） {item.target_usage.input_tokens} tokens（词元） · Output（输出） {item.target_usage.output_tokens} tokens（词元）</span>}</div>
    {item.target_attempts?.length ? <div className="run-attempts"><h4>Target Call（目标调用）</h4>{item.target_attempts.map((attempt, index) => <p key={index}>Attempt {String(attempt.number)}（第 {String(attempt.number)} 次） · {String(attempt.status)} · {Number(attempt.elapsed_ms).toFixed(1)} ms（毫秒）{attempt.ttft_ms !== null && attempt.ttft_ms !== undefined ? ` · TTFT ${Number(attempt.ttft_ms).toFixed(1)} ms（毫秒）` : ''}{attempt.ttlt_ms !== null && attempt.ttlt_ms !== undefined ? ` · TTLT ${Number(attempt.ttlt_ms).toFixed(1)} ms（毫秒）` : ''}{attempt.stream_completed_ms !== null && attempt.stream_completed_ms !== undefined ? ` · Completed（完成） ${Number(attempt.stream_completed_ms).toFixed(1)} ms（毫秒）` : ''}{attempt.error ? ` · ${String(attempt.error)}` : ''}</p>)}</div> : null}
    {item.score && <section className="run-evidence" aria-label="Match Evidence（匹配证据）"><div className="distribution-controls"><h4>Match Evidence（匹配证据）</h4><div className="segmented-control" role="group" aria-label="Evidence K Value（证据 K 值）"><button type="button" className={k === '10' ? 'selected' : ''} onClick={() => setK('10')}>@10</button><button type="button" className={k === '20' ? 'selected' : ''} onClick={() => setK('20')}>@20</button></div></div><p className="evidence-meta">Model（模型） {item.score.model_id} · Threshold（阈值） {item.score.threshold} · {item.score.match_rule_version} · {item.score.gain_rule_version}</p><div className="run-score-strip"><span>Precision（精确率） {showScore(score?.precision)}</span><span>AP（平均精确率） {showScore(score?.ap)}</span><span>NDCG（归一化折损累计增益） {showScore(score?.ndcg)}</span></div><div className="match-table-wrap"><table className="match-table"><thead><tr><th>Reference（参考）</th><th>Predictions（预测）</th><th>Similarity（相似度）</th><th>Decision（判定）</th></tr></thead><tbody>{score?.decisions.map((decision) => <tr key={`${decision.reference_index}-${decision.predicted_index}`}><td>#{decision.reference_index + 1}</td><td>#{decision.predicted_index + 1}</td><td>{decision.similarity?.toFixed(3) ?? '—'}</td><td className={decision.selected ? 'match-positive' : ''}>{decision.selected ? 'Matched（命中）' : decision.reason}</td></tr>)}</tbody></table></div></section>}
  </section>
}
