import { useState } from 'react'

import type { RunCase, RunSummary } from '../api/runs'
import { TraceLink } from '../trace/TraceLink'

type Metric = 'precision' | 'map' | 'ndcg'
const metricLabels: Record<Metric, string> = { precision: 'Precision', map: 'MAP', ndcg: 'NDCG' }
const answerLabels: Record<string, string> = { faithfulness: '忠实度', relevance: '相关性', correctness: '正确性' }
const bins = ['0–0.2', '0.2–0.4', '0.4–0.6', '0.6–0.8', '0.8–1']

function showScore(value: number | null | undefined): string {
  return value === null || value === undefined ? '不适用' : value.toFixed(3)
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
  return <section className="run-results" aria-label="总体指标">
    <div className="pane-heading"><h3>总体指标</h3>{hasRetrieval && <span>检索有效 {aggregate.valid_count} · 不适用 {aggregate.not_applicable_count}</span>}</div>
    {hasRetrieval && <>
    <div className="score-table-wrap"><table className="match-table"><thead><tr><th>指标</th><th>@10</th><th>@20</th></tr></thead><tbody>
      {selectedMetrics.includes('precision') && <tr><th>Precision</th><td>{showScore(aggregate.precision_at_k['10'])}</td><td>{showScore(aggregate.precision_at_k['20'])}</td></tr>}
      {selectedMetrics.includes('map') && <tr><th>MAP</th><td>{showScore(aggregate.map_at_k['10'])}</td><td>{showScore(aggregate.map_at_k['20'])}</td></tr>}
      {selectedMetrics.includes('ndcg') && <tr><th>NDCG</th><td>{showScore(aggregate.ndcg_at_k['10'])}</td><td>{showScore(aggregate.ndcg_at_k['20'])}</td></tr>}
    </tbody></table></div>
    {aggregate.valid_count > 0 && <div className="run-distribution"><div className="distribution-controls"><strong>分数分布</strong><select aria-label="分布指标" value={displayMetric} onChange={(event) => setMetric(event.target.value as Metric)}>{selectedMetrics.map((item) => <option key={item} value={item}>{metricLabels[item]}</option>)}</select><div className="segmented-control" role="group" aria-label="分布 K 值"><button type="button" className={k === '10' ? 'selected' : ''} onClick={() => setK('10')}>@10</button><button type="button" className={k === '20' ? 'selected' : ''} onClick={() => setK('20')}>@20</button></div></div><div className="distribution-bars">{counts.map((count, index) => <div className="distribution-bar" key={index}><div className="distribution-track"><span style={{ height: `${count / max * 100}%` }} /></div><strong>{count}</strong><small>{bins[index]}</small></div>)}</div></div>}
    </>}
    {Object.keys(answerMetrics).length > 0 && <div className="score-table-wrap"><table className="match-table"><thead><tr><th>回答指标</th><th>均分</th><th>有效</th><th>失败</th><th>不适用</th></tr></thead><tbody>{Object.entries(answerMetrics).map(([key, value]) => <tr key={key}><th>{answerLabels[key] ?? key}</th><td>{showScore(value.mean_score)}</td><td>{value.valid_count}</td><td>{value.failed_count}</td><td>{value.not_applicable_count}</td></tr>)}</tbody></table></div>}
  </section>
}

export function RunCaseDetail({ item }: { item: RunCase }) {
  const [k, setK] = useState<'10' | '20'>('10')
  const score = item.score?.scores[k]
  const answerMetrics = item.answer_metrics ?? {}
  return <section className="run-case-detail" aria-label="逐题详情">
    <div className="detail-heading"><span className="eyebrow">CASE DETAIL</span><code>{item.case_id}</code></div>
    <div className="trace-links"><TraceLink trace={item.trace} label="评分 trace" /><TraceLink trace={item.target_trace} label="目标调用 trace" /></div>
    <h3>{item.question}</h3>
    {item.error && <p className="form-error" role="alert">{item.error}</p>}
    <div className="run-answer-grid"><div><h4>标准答案</h4><p>{item.reference_answer ?? '不适用'}</p></div><div><h4>预测答案</h4><p>{item.answer ?? '未提供'}</p></div></div>
    {Object.keys(answerMetrics).length > 0 && <section className="run-answer-scores" aria-label="回答评分"><h4>回答评分</h4>{Object.entries(answerMetrics).map(([key, value]) => <div key={key} className="run-answer-score"><strong>{answerLabels[key] ?? key}</strong><span>{value.status === 'success' ? showScore(value.score) : value.status === 'failed' ? '失败' : '不适用'}</span><p>{value.reason ?? value.error ?? ''}</p><small>{value.model_name} · {value.prompt_version} · {value.criteria}</small>{value.raw_response && <details><summary>原始模型响应</summary><pre>{value.raw_response}</pre></details>}</div>)}</section>}
    <div className="run-answer-grid"><div><h4>参考 chunk</h4>{item.reference_chunks?.length ? <ol className="chunk-list">{item.reference_chunks.map((chunk, index) => <li key={index}><div className="chunk-meta">#{index + 1} <code>{chunk.document_id}</code></div><p>{chunk.text}</p></li>)}</ol> : <p>不适用</p>}</div><div><h4>预测 chunk</h4>{item.contexts?.length ? <ol className="chunk-list">{item.contexts.map((chunk, index) => <li key={index}><div className="chunk-meta">#{index + 1} <code>{chunk.document_id}</code></div><p>{chunk.text}</p></li>)}</ol> : <p>未提供</p>}</div></div>
    <div className="run-timing"><span>目标耗时：{item.target_latency_ms === null ? '未提供' : `${item.target_latency_ms.toFixed(1)} ms`}</span><span>评分耗时：{item.elapsed_ms === null ? '未提供' : `${item.elapsed_ms.toFixed(1)} ms`}</span>{item.target_usage && <span>目标 token：输入 {item.target_usage.input_tokens} · 输出 {item.target_usage.output_tokens}</span>}</div>
    {item.target_attempts?.length ? <div className="run-attempts"><h4>目标调用</h4>{item.target_attempts.map((attempt, index) => <p key={index}>第 {String(attempt.number)} 次 · {String(attempt.status)} · {Number(attempt.elapsed_ms).toFixed(1)} ms{attempt.ttft_ms !== null && attempt.ttft_ms !== undefined ? ` · TTFT ${Number(attempt.ttft_ms).toFixed(1)} ms` : ''}{attempt.ttlt_ms !== null && attempt.ttlt_ms !== undefined ? ` · TTLT ${Number(attempt.ttlt_ms).toFixed(1)} ms` : ''}{attempt.stream_completed_ms !== null && attempt.stream_completed_ms !== undefined ? ` · 完成 ${Number(attempt.stream_completed_ms).toFixed(1)} ms` : ''}{attempt.error ? ` · ${String(attempt.error)}` : ''}</p>)}</div> : null}
    {item.score && <section className="run-evidence" aria-label="匹配证据"><div className="distribution-controls"><h4>匹配证据</h4><div className="segmented-control" role="group" aria-label="证据 K 值"><button type="button" className={k === '10' ? 'selected' : ''} onClick={() => setK('10')}>@10</button><button type="button" className={k === '20' ? 'selected' : ''} onClick={() => setK('20')}>@20</button></div></div><p className="evidence-meta">模型 {item.score.model_id} · 阈值 {item.score.threshold} · {item.score.match_rule_version} · {item.score.gain_rule_version}</p><div className="run-score-strip"><span>Precision {showScore(score?.precision)}</span><span>AP {showScore(score?.ap)}</span><span>NDCG {showScore(score?.ndcg)}</span></div><div className="match-table-wrap"><table className="match-table"><thead><tr><th>参考</th><th>预测</th><th>相似度</th><th>判定</th></tr></thead><tbody>{score?.decisions.map((decision) => <tr key={`${decision.reference_index}-${decision.predicted_index}`}><td>#{decision.reference_index + 1}</td><td>#{decision.predicted_index + 1}</td><td>{decision.similarity?.toFixed(3) ?? '—'}</td><td className={decision.selected ? 'match-positive' : ''}>{decision.selected ? '命中' : decision.reason}</td></tr>)}</tbody></table></div></section>}
  </section>
}
