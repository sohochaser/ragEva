import type { UsageSummary } from '../api/usage'

const sources = ['actual', 'estimated', 'not_applicable', 'unknown'] as const
const labels: Record<typeof sources[number], string> = {
  actual: 'Actual（实际）', estimated: 'Estimated（估算）', not_applicable: 'Not Applicable（不适用）', unknown: 'Unknown（未知）',
}
const operations: Record<string, string> = {
  generation: 'Candidate Generation（候选生成）', answer_scoring: 'Answer Scoring（回答评分）', embedding: 'Local Embedding（本地向量）', target_rag: 'Target RAG（目标 RAG）',
}

function count(value: number | null, source: typeof sources[number]): string {
  return `${value ?? '—'} · ${labels[source]}`
}

export function UsagePanel({ usage }: { usage: UsageSummary | null }) {
  if (!usage || usage.call_count === 0) return null
  return <section className="usage-panel" aria-label="Model Token Usage（模型 token 用量）">
    <div className="pane-heading"><h3>Model Token Usage（模型 token 用量）</h3><span>{usage.call_count} calls（{usage.call_count} 次调用）</span></div>
    <div className="usage-totals">{(['input', 'output'] as const).map((side) => <div key={side}><strong>{side === 'input' ? 'Input（输入）' : 'Output（输出）'}</strong>{sources.map((source) => usage.totals[side][source].calls > 0 && <span key={source} title={source === 'estimated' ? 'Estimated with the local ByteLevel tokenizer, not actual model billing（本地 ByteLevel 分词估算，非模型实际计费值）' : undefined}>{labels[source]} {source === 'actual' || source === 'estimated' ? `${usage.totals[side][source].tokens} tokens（词元） · ` : ''}{usage.totals[side][source].calls} calls（次调用）</span>)}</div>)}</div>
    <details><summary>Per-Call Usage（逐次调用）</summary><div className="usage-table-wrap"><table className="match-table"><thead><tr><th>Calls（调用）</th><th>Cases（样本）</th><th>Model（模型）</th><th>Input Tokens（输入 token）</th><th>Output Tokens（输出 token）</th></tr></thead><tbody>{usage.calls.map((call) => <tr key={call.id}><td>{operations[call.operation] ?? call.operation}</td><td>{call.case_id ?? '—'}</td><td><code>{call.model_id}</code></td><td>{count(call.input_tokens, call.input_source)}</td><td>{count(call.output_tokens, call.output_source)}</td></tr>)}</tbody></table></div></details>
  </section>
}
