import type { UsageSummary } from '../api/usage'

const sources = ['actual', 'estimated', 'not_applicable', 'unknown'] as const
const labels: Record<typeof sources[number], string> = {
  actual: '实际', estimated: '估算', not_applicable: '不适用', unknown: '未知',
}
const operations: Record<string, string> = {
  generation: '候选生成', answer_scoring: '回答评分', embedding: '本地向量', target_rag: '目标 RAG',
}

function count(value: number | null, source: typeof sources[number]): string {
  return `${value ?? '—'} · ${labels[source]}`
}

export function UsagePanel({ usage }: { usage: UsageSummary | null }) {
  if (!usage || usage.call_count === 0) return null
  return <section className="usage-panel" aria-label="模型 token 用量">
    <div className="pane-heading"><h3>模型 token 用量</h3><span>{usage.call_count} 次调用</span></div>
    <div className="usage-totals">{(['input', 'output'] as const).map((side) => <div key={side}><strong>{side === 'input' ? '输入' : '输出'}</strong>{sources.map((source) => usage.totals[side][source].calls > 0 && <span key={source} title={source === 'estimated' ? '本地 ByteLevel 分词估算，非模型实际计费值' : undefined}>{labels[source]} {source === 'actual' || source === 'estimated' ? `${usage.totals[side][source].tokens} · ` : ''}{usage.totals[side][source].calls} 次</span>)}</div>)}</div>
    <details><summary>逐次调用</summary><div className="usage-table-wrap"><table className="match-table"><thead><tr><th>调用</th><th>样本</th><th>模型</th><th>输入 token</th><th>输出 token</th></tr></thead><tbody>{usage.calls.map((call) => <tr key={call.id}><td>{operations[call.operation] ?? call.operation}</td><td>{call.case_id ?? '—'}</td><td><code>{call.model_id}</code></td><td>{count(call.input_tokens, call.input_source)}</td><td>{count(call.output_tokens, call.output_source)}</td></tr>)}</tbody></table></div></details>
  </section>
}
